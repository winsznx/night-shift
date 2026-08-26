"""Run one complete incident: injection, agents, field events, reconciliation, evidence.

This is the scenario driver used by the CLI, the drill controller, and the campaign. It
owns the interleaving that a real deployment gets from Pub/Sub: agents plan, responders
scan, agents verify, and the deterministic services decide what is allowed to become
true at every step.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agents.orchestrator import IncidentOrchestrator, RunOutcome
from fixtures.estate import EstateFixture, build_estate, estate_hash, seed_repository
from nightshift.common.clock import now_iso
from nightshift.common.skills import skill_refs
from nightshift.runtime import Runtime, build_runtime
from nightshift.safety_kernel.world import reconciliation_snapshot
from nightshift.schemas.enums import AgentName, CustodyState, IncidentState, ReservationState
from services.common.effects import record_event
from services.gateway.broker import BrokerDeniedError
from services.simulator.ingest import (
    FailureProfile,
    FieldSimulator,
    ingest_sensor_event,
    inject_failure,
)

log = logging.getLogger(__name__)


@dataclass
class IncidentRun:
    incident_id: str
    estate: EstateFixture
    estate_hash: str
    outcome: RunOutcome | None = None
    field_events: list[dict[str, Any]] = field(default_factory=list)
    delivered_event_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    repair_simulated: bool = False
    containers_moved: set[str] = field(default_factory=set)
    """Authoritative across rounds. Recomputing this from custody state each round was
    wrong — a container can leave AT_SOURCE and come back via an exception, and the cap
    has to count attempts, not current state."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "estate_hash": self.estate_hash,
            "outcome": self.outcome.as_dict() if self.outcome else None,
            "field_events": len(self.field_events),
            "delivered_event_ids": self.delivered_event_ids,
            "notes": self.notes,
        }


@dataclass
class ScenarioConfig:
    """Everything a drill can vary without touching product code."""

    seed: int = 20260826
    failed_freezer: str = "F-17"
    profile: FailureProfile | None = None
    duplicate_delivery: bool = False
    contradict_container: str | None = None
    skip_containers: tuple[str, ...] = ()
    stale_memory_note: str | None = None
    warm_destination_after_reservation: str | None = None
    blocked_agent: tuple[AgentName, str] | None = None
    competing_incident_freezer: str | None = None
    max_rounds: int = 5
    max_transfers: int = 50
    """Cap on containers moved per run.

    A 42-container transfer is realistic in the world and pointless in a drill: the
    invariants are proved by the first few. The cap is *always* reported so a run that
    moved 6 of 42 is never read as a complete rescue — the rest are dispositioned
    explicitly, not silently dropped.
    """


async def run_incident(
    *,
    runtime: Runtime | None = None,
    scenario: ScenarioConfig | None = None,
    namespace: str = "demo",
    model: str | None = None,
    driver: str = "agent",
) -> tuple[Runtime, IncidentRun]:
    """Run one incident.

    ``driver="agent"`` uses the real Gemini fleet. ``driver="scripted"`` uses the
    deterministic policy in ``assurance.scripted``, which makes the same tool calls
    through the same broker and services without a model in the loop. Both tiers are
    reported separately and never pooled.
    """
    scenario = scenario or ScenarioConfig()
    runtime = runtime or build_runtime(namespace=namespace)
    model = model or runtime.settings.model_id

    estate = build_estate(scenario.seed)
    seed_repository(runtime.repo, estate)
    fixture_hash = estate_hash(estate)

    profile = scenario.profile or FailureProfile(freezer_id=scenario.failed_freezer)
    inject_failure(runtime.repo, profile, seed=scenario.seed)

    opened = ingest_sensor_event(
        runtime.repo,
        site_id=estate.site.id,
        freezer_id=scenario.failed_freezer,
        source_event_id="evt-sensor-primary",
        namespace=namespace,
    )
    incident_id = opened["incident_id"]
    delivered = ["evt-sensor-primary"]

    if scenario.duplicate_delivery:
        again = ingest_sensor_event(
            runtime.repo,
            site_id=estate.site.id,
            freezer_id=scenario.failed_freezer,
            source_event_id="evt-sensor-primary-redelivered",
            namespace=namespace,
        )
        delivered.append("evt-sensor-primary-redelivered")
        assert again["incident_id"] == incident_id, "duplicate delivery opened a second incident"
        record_event(
            runtime.repo,
            incident_id,
            kind="sensor",
            source="incident-ingestor",
            summary="Duplicate sensor delivery absorbed into the existing incident",
            detail={"joined_existing": again["joined_existing"], "dedupe_key": again["dedupe_key"]},
        )

    run = IncidentRun(
        incident_id=incident_id,
        estate=estate,
        estate_hash=fixture_hash,
        delivered_event_ids=delivered,
    )

    if scenario.stale_memory_note:
        runtime.add_memory_note(incident_id, scenario.stale_memory_note)
        run.notes.append("stale memory note injected")

    if scenario.blocked_agent is not None:
        agent, revision = scenario.blocked_agent
        runtime.set_revision_state(agent, revision, "BLOCKED")
        run.notes.append(f"{agent.value}@{revision} set to BLOCKED")

    if scenario.competing_incident_freezer:
        _open_competing_incident(runtime, estate, scenario, namespace, run)

    simulator = FieldSimulator(
        repo=runtime.repo,
        incident_id=incident_id,
        task_token="",
        responder_id="RESP-01",
        seed=str(scenario.seed),
        contradict_container=scenario.contradict_container,
        skip_containers=scenario.skip_containers,
    )
    simulator.announce()

    orchestrator_cls: Any = IncidentOrchestrator
    if driver == "scripted":
        from assurance.scripted import ScriptedOrchestrator

        orchestrator_cls = ScriptedOrchestrator

    orchestrator = orchestrator_cls(
        runtime.repo,
        runtime.broker,
        incident_id,
        model=model,
        skill_refs=skill_refs(),
        memory_context=runtime.memory_context(incident_id),
        max_rounds=scenario.max_rounds,
        field_hook=lambda round_index: _field_round(runtime, run, simulator, scenario, round_index),
    )
    run.outcome = await orchestrator.run()
    _disposition_remainder(runtime, run, scenario)
    return runtime, run


# --------------------------------------------------------------------------------------


def _field_round(
    runtime: Runtime,
    run: IncidentRun,
    simulator: FieldSimulator,
    scenario: ScenarioConfig,
    round_index: int,
) -> None:
    """Emit responder scans for containers that have a reserved destination.

    Only containers whose placement group actually has an active reservation move. A
    container with nowhere safe to go stays where it is, which is what makes the partial
    and contention drills produce honest outcomes rather than a stuck loop.
    """
    _emit_sensor_tick(runtime)

    state = runtime.repo.load_kernel_state(run.incident_id)
    if state.incident is None or state.impact is None:
        return
    if state.incident.state in {IncidentState.CLOSED, IncidentState.ABORTED_SAFE}:
        return

    # Once nothing is left to move, the physical repair happens and the freezer starts
    # producing post-repair telemetry. Whether that telemetry adds up to a validated
    # recovery is not this function's call.
    recon = reconciliation_snapshot(state)
    if recon.total and not recon.in_flight and not recon.unresolved and not run.repair_simulated:
        run.repair_simulated = True
        simulate_repair_recovery(runtime, run, state.incident.failed_freezer_id)
        return

    dispatches = runtime.repo.list_dispatches(run.incident_id)
    if not dispatches:
        return
    responder_id = dispatches[0].responder_id
    simulator.responder_id = responder_id

    reservations_by_group = {
        r.placement_group_id: r
        for r in state.reservations.values()
        if r.incident_id == run.incident_id
        and r.state in {ReservationState.ACTIVE, ReservationState.CONSUMED}
    }
    if not reservations_by_group:
        return

    for group in state.impact.placement_groups:
        reservation = reservations_by_group.get(group.id)
        if reservation is None:
            continue
        for container_id in group.container_ids:
            if len(run.containers_moved) >= scenario.max_transfers:
                return
            if container_id in scenario.skip_containers:
                continue
            if container_id in run.containers_moved:
                continue
            container = state.containers.get(container_id)
            if container is None or container.custody_state is not CustodyState.AT_SOURCE:
                continue
            run.containers_moved.add(container_id)
            slot = f"{reservation.destination_freezer_id}-SLOT-{container_id[-4:]}"
            _emit(
                runtime,
                run,
                "record_pickup",
                simulator.pickup_payload(
                    container_id,
                    container.freezer_id,
                    reservation.destination_freezer_id,
                    slot,
                    reservation.id,
                ),
            )
            if scenario.warm_destination_after_reservation == reservation.destination_freezer_id:
                _warm_destination(runtime, reservation.destination_freezer_id)
                scenario.warm_destination_after_reservation = None
                run.notes.append(f"{reservation.destination_freezer_id} warmed after reservation")
            _emit(
                runtime,
                run,
                "record_destination_scan",
                simulator.destination_payload(
                    container_id,
                    reservation.destination_freezer_id,
                    slot,
                ),
            )


def _emit_sensor_tick(runtime: Runtime) -> None:
    """Emit a current reading for every healthy freezer, as a real sensor fabric would.

    Without this, the estate's telemetry is written once at seed time and then ages. A
    long run — and a run against real Firestore is long — pushes every destination past
    the N4 freshness window, and the kernel correctly refuses every custody commit with
    "destination reading is 1175s old, limit 900s".

    That refusal was right; the *world* was wrong. A working ULT freezer reports every
    few minutes, so modelling it as reporting once is the bug. This does not fabricate a
    safe temperature: it reports each freezer's current authoritative value with the
    small jitter a real probe has, and a freezer that is failing keeps reporting that it
    is failing.
    """
    from nightshift.schemas.core import TemperatureReading
    from nightshift.schemas.enums import FreezerState

    now = now_iso()
    for freezer in runtime.repo.list_freezers():
        if freezer.state is FreezerState.FAILED:
            # The failed unit's curve is driven by the injected profile, not by this tick.
            continue
        jitter = ((hash((freezer.id, now)) % 21) - 10) / 50.0
        celsius = round(freezer.current_temp_c + jitter, 2)
        reading = TemperatureReading(
            id=f"R-{freezer.id}-TICK-{now.replace(':', '').replace('.', '').replace('-', '')}",
            freezer_id=freezer.id,
            celsius=celsius,
            recorded_at=now,
            source="sensor",
        )
        runtime.repo.store.set("readings", reading.id, reading.model_dump(mode="json"))
        runtime.repo.put(
            "freezers",
            freezer.id,
            freezer.model_copy(update={"current_temp_c": celsius, "last_reading_at": now}),
        )


def simulate_repair_recovery(runtime: Runtime, run: IncidentRun, freezer_id: str) -> int:
    """Emit the telemetry a genuinely repaired freezer would produce.

    This is a simulated *physical* event, exactly like a responder scan, and it is
    labelled as one. What it does not do is assert that the freezer recovered — it
    writes readings, and the deterministic release rule decides whether those readings
    add up to a validated recovery. Writing a "repaired" flag instead would be the
    fabrication this whole system exists to prevent.
    """
    from nightshift.common.clock import shift_iso
    from nightshift.schemas.core import TemperatureReading

    freezer = runtime.repo.get_freezer(freezer_id)
    if freezer is None:
        return 0

    now = now_iso()
    window = 2400  # comfortably longer than the 1800s validation requirement
    interval = 300
    written = 0
    for i in range(window // interval + 1):
        offset = -window + i * interval
        reading = TemperatureReading(
            id=f"R-{freezer_id}-RECOVERY-{i:03d}",
            freezer_id=freezer_id,
            celsius=round(-79.5 - (i % 3) * 0.2, 2),
            recorded_at=shift_iso(now, offset),
            source="sensor",
        )
        runtime.repo.store.set("readings", reading.id, reading.model_dump(mode="json"))
        written += 1

    latest = runtime.repo.list_readings(freezer_id)[-1]
    runtime.repo.put(
        "freezers",
        freezer_id,
        freezer.model_copy(
            update={"current_temp_c": latest.celsius, "last_reading_at": latest.recorded_at}
        ),
    )
    record_event(
        runtime.repo,
        run.incident_id,
        kind="field",
        source="field-simulator",
        summary=(
            f"SIMULATED FIELD EVENT — {freezer_id} repaired; {written} post-repair readings "
            "written. Whether this constitutes a validated recovery is decided by the "
            "deterministic release rule, not by this event."
        ),
        detail={"simulator": True, "freezer_id": freezer_id, "readings_written": written},
    )
    run.notes.append(f"{freezer_id} repair simulated; {written} validation readings written")
    return written


def _emit(runtime: Runtime, run: IncidentRun, tool: str, payload: dict[str, Any]) -> None:
    """Send a simulated responder event through the responder-app principal.

    Deliberately *not* the Custody Agent's principal: a scan comes from the responder's
    device, and the authority separation should be visible in the ledger.
    """
    try:
        result = runtime.broker.call(AgentName.RESPONDER_APP, tool, payload)
    except BrokerDeniedError as denied:
        result = {"denied": True, "reason": denied.decision.reason}
    except Exception as exc:
        result = {"error": f"{type(exc).__name__}: {exc}"}
    run.field_events.append({"tool": tool, "payload": payload, "result": result})


def _warm_destination(runtime: Runtime, freezer_id: str) -> None:
    """D8: the destination warms after the reservation but before receipt."""
    from nightshift.schemas.core import TemperatureReading

    now = now_iso()
    freezer = runtime.repo.get_freezer(freezer_id)
    if freezer is None:
        return
    reading = TemperatureReading(
        id=f"R-{freezer_id}-WARM", freezer_id=freezer_id, celsius=-41.0, recorded_at=now
    )
    runtime.repo.store.set("readings", reading.id, reading.model_dump(mode="json"))
    runtime.repo.put(
        "freezers",
        freezer_id,
        freezer.model_copy(update={"current_temp_c": -41.0, "last_reading_at": now}),
    )


def _open_competing_incident(
    runtime: Runtime,
    estate: EstateFixture,
    scenario: ScenarioConfig,
    namespace: str,
    run: IncidentRun,
) -> None:
    """D4: a second freezer fails and competes for the same backup capacity."""
    other = scenario.competing_incident_freezer
    assert other is not None
    inject_failure(runtime.repo, FailureProfile(freezer_id=other), seed=scenario.seed + 1)
    opened = ingest_sensor_event(
        runtime.repo,
        site_id=estate.site.id,
        freezer_id=other,
        source_event_id="evt-sensor-competing",
        namespace=namespace,
    )
    run.notes.append(f"competing incident {opened['incident_id']} opened on {other}")

    # The competing incident takes its reservation through the real Capacity Service, so
    # the contention is authentic and the resulting effect carries a receipt like any
    # other. Writing the reservation straight into the store would have produced an
    # effect with no receipt, which the ledger/effect agreement check in N2 correctly
    # flags as a mismatch.
    destination = _busiest_backup(runtime)
    if destination is None:
        return
    free = runtime.repo.get_freezer(destination).free_slots  # type: ignore[union-attr]
    take = max(1, free - 2)
    result = runtime.broker.call(
        AgentName.CAPACITY_BROKER,
        "reserve_capacity",
        {
            "incident_id": opened["incident_id"],
            "destination_freezer_id": destination,
            "placement_group_id": "PG-COMPETING",
            "slots": take,
            "evidence_sources": ["capacity:get_capacity"],
        },
    )
    status = result.get("receipt", {}).get("status")
    if status == "COMMITTED":
        run.notes.append(f"competing incident holds {take} slot(s) in {destination}")
    else:
        run.notes.append(
            f"competing incident could not reserve in {destination}: "
            f"{result.get('decision', {}).get('reason', status)}"
        )


def _busiest_backup(runtime: Runtime) -> str | None:
    candidates = sorted(
        (f for f in runtime.repo.list_freezers() if f.is_backup_qualified and f.free_slots > 3),
        key=lambda f: f.free_slots,
        reverse=True,
    )
    return candidates[0].id if candidates else None


def _disposition_remainder(runtime: Runtime, run: IncidentRun, scenario: ScenarioConfig) -> None:
    """Record what the run did not move, explicitly.

    The transfer cap and any skipped containers are real limits. Rather than let them
    sit as an ambiguous AT_SOURCE, the run states plainly how many containers remain and
    why. Nothing here quarantines material to make a number look better — the incident
    stays open exactly as it should.
    """
    state = runtime.repo.load_kernel_state(run.incident_id)
    recon = reconciliation_snapshot(state)
    remaining = len(recon.unresolved) + len(recon.in_flight)
    if remaining == 0:
        return

    at_source = [
        c.id
        for c in state.containers.values()
        if c.incident_id == run.incident_id and c.custody_state is CustodyState.AT_SOURCE
    ]
    note = (
        f"{len(at_source)} container(s) were not moved in this run "
        f"(transfer cap {scenario.max_transfers}"
        + (
            f", {len(scenario.skip_containers)} deliberately skipped"
            if scenario.skip_containers
            else ""
        )
        + "). The incident correctly remains open."
    )
    run.notes.append(note)
    record_event(
        runtime.repo,
        run.incident_id,
        kind="note",
        source="incident-runner",
        summary=note,
        detail={
            "transfer_cap": scenario.max_transfers,
            "not_moved": sorted(at_source)[:20],
            "not_moved_count": len(at_source),
            "reconciliation": recon.as_dict(),
        },
    )
