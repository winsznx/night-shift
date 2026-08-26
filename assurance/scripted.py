"""Scripted incident driver — the deterministic tier of the drill range.

The hard invariants are properties of the deterministic layer: the Safety Kernel, the
domain services, and the effect commit sequence. Whether *those* hold under fault
injection does not depend on a model being in the loop, and running a model to find out
costs minutes per drill and introduces variance that has nothing to do with the property
under test.

So the corpus runs in two tiers, and both are published:

* **scripted** — this module. A fixed policy plays each specialist role, calling exactly
  the same broker, the same tools, and the same services. Fast enough for a hundreds-run
  campaign across many seeds.
* **agent** — the real Gemini fleet through ``IncidentOrchestrator``. Slower, so a
  smaller disclosed sample, proving the agents actually drive the same machinery.

The scripted tier is not a mock. It makes real tool calls through the real broker with
real authorization and real fault injection; only the choice of *which* call to make
next is fixed instead of reasoned. Results from the two tiers are reported separately
and never pooled into a single headline number.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from nightshift.safety_kernel.transitions import next_natural_state
from nightshift.safety_kernel.world import reconciliation_snapshot
from nightshift.schemas.enums import (
    AgentName,
    CustodyState,
    FaultClass,
    IncidentState,
    ResponderRole,
    ResponsePhase,
)
from services.common.effects import record_event
from services.common.repository import Repository
from services.gateway.broker import BrokerDeniedError, ToolBroker

log = logging.getLogger(__name__)


@dataclass
class ScriptedOutcome:
    incident_id: str
    final_state: str
    rounds: int
    specialists_run: list[str] = field(default_factory=list)
    stopped_because: str = ""
    model_calls: int = 0
    wall_clock_s: float = 0.0
    escalations: list[str] = field(default_factory=list)
    specialist_results: list[Any] = field(default_factory=list)
    commander_plans: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "final_state": self.final_state,
            "rounds": self.rounds,
            "specialists_run": self.specialists_run,
            "specialist_failures": [],
            "escalations": self.escalations,
            "stopped_because": self.stopped_because,
            "model_calls": 0,
            "wall_clock_s": round(self.wall_clock_s, 2),
            "driver": "scripted",
        }


class ScriptedOrchestrator:
    """Deterministic stand-in for the Commander and its specialists.

    Same interface as ``IncidentOrchestrator`` so ``run_incident`` can drive either.
    """

    def __init__(
        self,
        repo: Repository,
        broker: ToolBroker,
        incident_id: str,
        *,
        model: str = "",
        max_rounds: int = 6,
        field_hook: Any = None,
        **_ignored: Any,
    ) -> None:
        self.repo = repo
        self.broker = broker
        self.incident_id = incident_id
        self.max_rounds = max_rounds
        self.field_hook = field_hook
        self._ran: list[str] = []
        self._escalations: list[str] = []

    async def run(self) -> ScriptedOutcome:
        import time

        started = time.perf_counter()
        stopped = "round budget exhausted"

        for round_index in range(self.max_rounds):
            need = self._next_role()
            if need is not None:
                self._tick_world(round_index)
                self._play(need)
                self._ran.append(need.value)
            self._advance()

            self._tick_world(round_index)
            self._advance()

            state = self.repo.load_kernel_state(self.incident_id)
            recon = reconciliation_snapshot(state)
            ready_to_close = recon.total and recon.complete and self._containment_settled(state)
            if ready_to_close and self._close():
                stopped = "incident closed"
                break
            if state.incident and state.incident.state in {
                IncidentState.CLOSED,
                IncidentState.ABORTED_SAFE,
            }:
                stopped = f"incident reached {state.incident.state.value}"
                break

        if self._close_if_evidence_supports_it():
            stopped = "incident closed on final evidence sweep"

        incident = self.repo.get_incident(self.incident_id)
        return ScriptedOutcome(
            incident_id=self.incident_id,
            final_state=incident.state.value if incident else "UNKNOWN",
            rounds=min(self.max_rounds, len(self._ran) + 1),
            specialists_run=self._ran,
            stopped_because=stopped,
            escalations=self._escalations,
            wall_clock_s=time.perf_counter() - started,
        )

    def _tick_world(self, round_index: int) -> None:
        if self.field_hook is None:
            return
        try:
            self.field_hook(round_index)
        except Exception as exc:
            log.warning("field hook failed: %s", exc)

    # -- policy ----------------------------------------------------------------------

    def _next_role(self) -> AgentName | None:
        state = self.repo.load_kernel_state(self.incident_id)
        if state.incident is None:
            return None
        freezer_id = state.incident.failed_freezer_id

        if not self._signal_done:
            return AgentName.SIGNAL_INVESTIGATOR
        if state.holds.get(freezer_id) is None:
            return None  # signal said it was not an equipment failure; nothing to do
        if state.impact is None:
            return AgentName.IMPACT_ANALYST
        if self._unplaced(state):
            return AgentName.CAPACITY_BROKER
        if not state.dispatches:
            return AgentName.DISPATCH_AGENT
        if any(t.state is CustodyState.RECEIVED for t in state.transfers.values()):
            return AgentName.CUSTODY_AGENT
        return None

    _signal_done = False

    def _play(self, role: AgentName) -> None:
        match role:
            case AgentName.SIGNAL_INVESTIGATOR:
                self._play_signal()
            case AgentName.IMPACT_ANALYST:
                self._play_impact()
            case AgentName.CAPACITY_BROKER:
                self._play_capacity()
            case AgentName.DISPATCH_AGENT:
                self._play_dispatch()
            case AgentName.CUSTODY_AGENT:
                self._play_custody()
            case _:
                pass

    def _play_signal(self) -> None:
        self._signal_done = True
        incident = self.repo.get_incident(self.incident_id)
        if incident is None:
            return
        freezer_id = incident.failed_freezer_id

        window = self._call(
            AgentName.SIGNAL_INVESTIGATOR,
            "get_temperature_window",
            {"freezer_id": freezer_id, "minutes": 180},
        )
        doors = self._call(
            AgentName.SIGNAL_INVESTIGATOR,
            "get_recent_door_events",
            {"freezer_id": freezer_id, "hours": 6},
        )
        self._call(
            AgentName.SIGNAL_INVESTIGATOR, "get_equipment_history", {"freezer_id": freezer_id}
        )

        sustained = bool(window.get("sustained_warming_confirmed"))
        latest = window.get("latest_celsius")
        recovering = (
            latest is not None
            and window.get("max_celsius") is not None
            and latest < float(window["max_celsius"]) - 3.0
        )
        door_explains = bool(doors.get("events")) and recovering

        classification = (
            "EQUIPMENT_FAILURE"
            if sustained and not door_explains
            else "DOOR_EVENT"
            if door_explains
            else "TRANSIENT_EXCURSION"
            if not sustained
            else "INCONCLUSIVE"
        )
        record_event(
            self.repo,
            self.incident_id,
            kind="agent_decision",
            source=AgentName.SIGNAL_INVESTIGATOR.value,
            summary=f"{classification} (scripted driver)",
            detail={
                "classification": classification,
                "sustained_warming_confirmed": sustained,
                "door_explains": door_explains,
                "driver": "scripted",
            },
            agent=AgentName.SIGNAL_INVESTIGATOR,
        )
        if classification != "EQUIPMENT_FAILURE":
            return

        self._advance()
        self._ingestor(
            "apply_containment_hold",
            {
                "incident_id": self.incident_id,
                "freezer_id": freezer_id,
                "reason": "sustained warming with no door explanation (scripted driver)",
            },
        )

    def _play_impact(self) -> None:
        incident = self.repo.get_incident(self.incident_id)
        if incident is None:
            return
        listing = self._call(
            AgentName.IMPACT_ANALYST,
            "list_impacted_containers",
            {"freezer_id": incident.failed_freezer_id, "incident_id": self.incident_id},
        )
        if listing.get("denied") or listing.get("unavailable"):
            self._escalations.append("inventory enumeration unavailable")
            record_event(
                self.repo,
                self.incident_id,
                kind="agent_decision",
                source=AgentName.IMPACT_ANALYST.value,
                summary="Inventory enumeration unavailable; no impact snapshot recorded",
                detail={"driver": "scripted", "reason": listing.get("reason")},
                agent=AgentName.IMPACT_ANALYST,
            )
            return

        container_ids = [c["container_id"] for c in listing.get("containers", [])]
        record_event(
            self.repo,
            self.incident_id,
            kind="agent_decision",
            source=AgentName.IMPACT_ANALYST.value,
            summary=f"Impact: {len(container_ids)} container(s) (scripted driver)",
            detail={
                "container_ids": container_ids[:20],
                "inventory_complete": bool(listing.get("enumeration_complete")),
                "driver": "scripted",
            },
            agent=AgentName.IMPACT_ANALYST,
        )
        self._ingestor(
            "record_impact_snapshot",
            {
                "incident_id": self.incident_id,
                "container_ids": container_ids,
                "inventory_complete": bool(listing.get("enumeration_complete")),
            },
        )

    def _play_capacity(self) -> None:
        state = self.repo.load_kernel_state(self.incident_id)
        if state.impact is None:
            return
        listing = self._call(
            AgentName.CAPACITY_BROKER,
            "list_qualified_destinations",
            {"incident_id": self.incident_id, "required_temp_c": -80.0},
        )
        if listing.get("denied") or listing.get("unavailable"):
            self._escalations.append("destination listing unavailable")
            return

        eligible = [d for d in listing.get("destinations", []) if d.get("eligible")]
        placed = 0
        for group in state.impact.placement_groups:
            if group.id in self._covered(state):
                continue
            for destination in eligible:
                free = int(destination.get("unreserved_free_slots", 0))
                if free < group.slot_count:
                    continue
                result = self._call(
                    AgentName.CAPACITY_BROKER,
                    "reserve_capacity",
                    {
                        "incident_id": self.incident_id,
                        "destination_freezer_id": destination["freezer_id"],
                        "placement_group_id": group.id,
                        "slots": group.slot_count,
                        "evidence_sources": [
                            "capacity:get_capacity",
                            "capacity:list_qualified_destinations",
                        ],
                    },
                )
                if result.get("receipt", {}).get("status") == "COMMITTED":
                    destination["unreserved_free_slots"] = free - group.slot_count
                    placed += 1
                    break
                # A refusal carries the real numbers. Re-plan against the next candidate
                # rather than retrying the same request.
        record_event(
            self.repo,
            self.incident_id,
            kind="agent_decision",
            source=AgentName.CAPACITY_BROKER.value,
            summary=f"Capacity plan: {placed} group(s) placed (scripted driver)",
            detail={
                "placed": placed,
                "eligible_destinations": [d["freezer_id"] for d in eligible],
                "driver": "scripted",
            },
            agent=AgentName.CAPACITY_BROKER,
        )

    def _play_dispatch(self) -> None:
        incident = self.repo.get_incident(self.incident_id)
        if incident is None:
            return
        self._call(
            AgentName.DISPATCH_AGENT,
            "get_equipment_history",
            {"freezer_id": incident.failed_freezer_id},
        )
        self._call(
            AgentName.DISPATCH_AGENT,
            "create_work_order",
            {
                "incident_id": self.incident_id,
                "freezer_id": incident.failed_freezer_id,
                "fault_class": FaultClass.COMPRESSOR_FAILURE.value,
                "summary": "Sustained warming; compressor suspected (scripted driver)",
            },
        )
        state = self.repo.load_kernel_state(self.incident_id)
        containers = state.incident_container_ids()
        self._call(
            AgentName.DISPATCH_AGENT,
            "dispatch_responder",
            {
                "incident_id": self.incident_id,
                "responder_role": ResponderRole.LAB_TECH.value,
                "response_phase": ResponsePhase.TRANSFER.value,
                "container_ids": containers[:50],
            },
        )
        record_event(
            self.repo,
            self.incident_id,
            kind="agent_decision",
            source=AgentName.DISPATCH_AGENT.value,
            summary="Work order opened and lab tech dispatched (scripted driver)",
            detail={"driver": "scripted"},
            agent=AgentName.DISPATCH_AGENT,
        )

    def _play_custody(self) -> None:
        result = self._call(
            AgentName.CUSTODY_AGENT,
            "commit_ready_transfers",
            {"incident_id": self.incident_id, "limit": 60},
        )
        record_event(
            self.repo,
            self.incident_id,
            kind="agent_decision",
            source=AgentName.CUSTODY_AGENT.value,
            summary=(
                f"Committed {result.get('committed_count', 0)} of "
                f"{result.get('ready_count', 0)} ready container(s), "
                f"{result.get('refused_count', 0)} refused (scripted driver)"
            ),
            detail={
                "driver": "scripted",
                **{
                    k: v
                    for k, v in result.items()
                    if k in {"committed_count", "refused_count", "ready_count", "refused"}
                },
            },
            agent=AgentName.CUSTODY_AGENT,
        )
        # Anything refused for an unfixable reason gets an honest disposition rather
        # than being left ambiguous.
        for refusal in result.get("refused", []):
            if refusal.get("invariant") in {"N4", "N3"}:
                self._call(
                    AgentName.CUSTODY_AGENT,
                    "flag_custody_exception",
                    {
                        "incident_id": self.incident_id,
                        "container_id": refusal["container_id"],
                        "reason": f"commit refused: {refusal.get('reason', '')[:200]}",
                        "disposition": "UNRESOLVED",
                    },
                )

    # -- helpers ----------------------------------------------------------------------

    @staticmethod
    def _covered(state: Any) -> set[str]:
        return {
            r.placement_group_id
            for r in state.reservations.values()
            if state.incident is not None
            and r.incident_id == state.incident.id
            and r.state.value in {"ACTIVE", "CONSUMED"}
        }

    def _unplaced(self, state: Any) -> list[str]:
        if state.impact is None:
            return []
        covered = self._covered(state)
        return [g.id for g in state.impact.placement_groups if g.id not in covered]

    def _containment_settled(self, state: Any) -> bool:
        if state.incident is None:
            return False
        hold = state.holds.get(state.incident.failed_freezer_id)
        return hold is not None and not hold.active

    def _call(self, agent: AgentName, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.broker.call(agent, tool, payload)
        except BrokerDeniedError as denied:
            return {
                "denied": True,
                "reason": denied.decision.reason,
                "invariant": denied.decision.invariant,
            }
        except Exception as exc:
            return {"unavailable": True, "reason": f"{type(exc).__name__}: {exc}"}

    def _ingestor(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        from fastapi.testclient import TestClient

        from nightshift.common.config import get_settings
        from services.common.identity import PRINCIPAL_HEADER, issue_principal_token
        from services.inventory.app import app as inventory_app

        inventory_app.state.repository = self.repo
        client = TestClient(inventory_app, raise_server_exceptions=False)
        token = issue_principal_token(
            AgentName.INGESTOR, "rev-1", get_settings().agent_shared_secret
        )
        route = {
            "apply_containment_hold": "/v1/holds",
            "record_impact_snapshot": "/v1/impact",
            "release_containment_hold": f"/v1/holds/{payload.get('freezer_id')}/release",
        }[operation]
        response = client.post(route, json=payload, headers={PRINCIPAL_HEADER: token})
        try:
            return dict(response.json())
        except ValueError:
            return {"error": f"non-JSON {response.status_code}"}

    def _advance(self) -> None:
        self._release_if_recovered()
        for _ in range(len(IncidentState)):
            state = self.repo.load_kernel_state(self.incident_id)
            target = next_natural_state(state)
            if target is None or target is IncidentState.CLOSED:
                return
            result = self._call(
                AgentName.COMMANDER,
                "request_incident_transition",
                {
                    "incident_id": self.incident_id,
                    "to_state": target.value,
                    "reason": "evidence supports this transition",
                },
            )
            if result.get("receipt", {}).get("status") != "COMMITTED":
                return

    def _release_if_recovered(self) -> None:
        incident = self.repo.get_incident(self.incident_id)
        if incident is None:
            return
        freezer_id = incident.failed_freezer_id
        hold = self.repo.get_hold(freezer_id)
        if hold is None or not hold.active:
            return
        window = [
            {"recorded_at": r.recorded_at, "celsius": r.celsius}
            for r in self.repo.list_readings(freezer_id)
            if r.id.startswith(f"R-{freezer_id}-RECOVERY")
        ]
        if not window:
            return
        self._ingestor(
            "release_containment_hold",
            {
                "incident_id": self.incident_id,
                "freezer_id": freezer_id,
                "validation_readings": window,
            },
        )

    def _close_if_evidence_supports_it(self) -> bool:
        """Same final sweep the agent orchestrator makes: close only if N6 already holds."""
        from nightshift.safety_kernel.invariants import n6_would_hold
        from nightshift.schemas.enums import TERMINAL_INCIDENT_STATES

        incident = self.repo.get_incident(self.incident_id)
        if incident is None or incident.state in TERMINAL_INCIDENT_STATES:
            return False
        self._advance()
        ok, _reason = n6_would_hold(self.repo.load_kernel_state(self.incident_id))
        return self._close() if ok else False

    def _close(self) -> bool:
        self._advance()
        incident = self.repo.get_incident(self.incident_id)
        if incident is not None and incident.state is not IncidentState.RECONCILING:
            self._call(
                AgentName.COMMANDER,
                "request_incident_transition",
                {
                    "incident_id": self.incident_id,
                    "to_state": IncidentState.RECONCILING.value,
                    "reason": "all containers accounted for",
                },
            )
        result = self._call(
            AgentName.COMMANDER,
            "request_incident_close",
            {"incident_id": self.incident_id, "reason": "all impacted containers reconciled"},
        )
        return bool(result.get("receipt", {}).get("status") == "COMMITTED")
