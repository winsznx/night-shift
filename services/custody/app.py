"""Custody Service (PRD §17.5).

Pickup scans, destination scans, the authoritative location commit, and reconciliation.

Everything consequential here is guarded twice: the custody state machine decides
whether the transition is even shaped correctly, and N3/N4 decide whether the evidence
behind it is good enough. A responder tapping "confirm" twice, a redelivered scan
event, and a resumed agent all converge on the same single transition.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends
from pydantic import BaseModel, Field

from nightshift.common.clock import now_iso
from nightshift.common.ids import scan_action_id, transfer_action_id
from nightshift.common.store import TxnContext
from nightshift.safety_kernel import ActionRequest, KernelState, reconciliation_snapshot
from nightshift.schemas.core import ScanEvidence, Transfer
from nightshift.schemas.enums import (
    ActionType,
    CustodyState,
    ReservationState,
)
from services.common.app import create_app, get_repository, require_tool
from services.common.effects import EffectResult, commit_effect
from services.common.identity import AgentPrincipal
from services.common.repository import Repository

app = create_app(
    service_name="custody",
    title="Night Shift — Custody Service",
    description="Scan evidence, authoritative location commits, and reconciliation.",
)


class PickupRequest(BaseModel):
    incident_id: str
    container_id: str
    responder_id: str
    source_freezer: str
    destination_freezer: str
    destination_slot: str
    reservation_id: str | None = None
    scan_signature: str = ""
    simulated: bool = False
    trace_id: str | None = None


class DestinationScanRequest(BaseModel):
    incident_id: str
    container_id: str
    responder_id: str
    destination_freezer_id: str
    destination_slot: str
    scan_signature: str = ""
    simulated: bool = False
    trace_id: str | None = None


class CommitRequest(BaseModel):
    incident_id: str
    container_id: str
    trace_id: str | None = None


class CommitBatchRequest(BaseModel):
    incident_id: str
    limit: int = Field(default=60, ge=1, le=500)
    trace_id: str | None = None


class ExceptionRequest(BaseModel):
    incident_id: str
    container_id: str
    reason: str = Field(max_length=600)
    disposition: str = Field(default="UNRESOLVED", pattern="^(UNRESOLVED|QUARANTINED)$")
    trace_id: str | None = None


@app.get("/v1/incidents/{incident_id}/custody")
async def get_custody_state(
    incident_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_custody_state")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    state = repo.load_kernel_state(incident_id)
    transfers = repo.list_transfers(incident_id)
    return {
        "incident_id": incident_id,
        "evaluated_at": now_iso(),
        "containers": [
            {
                "container_id": cid,
                "custody_state": (
                    state.containers[cid].custody_state.value
                    if cid in state.containers
                    else "UNKNOWN"
                ),
            }
            for cid in state.incident_container_ids()
        ],
        "transfers": [t.model_dump(mode="json") for t in transfers],
    }


@app.get("/v1/incidents/{incident_id}/reconciliation")
async def reconcile_incident(
    incident_id: str,
    _p: AgentPrincipal = Depends(require_tool("reconcile_incident")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """The deterministic reconciliation snapshot and its hash.

    The hash is what a close request must be keyed on, so a close computed against an
    older reconciliation cannot replay an earlier receipt.
    """
    state = repo.load_kernel_state(incident_id)
    snap = reconciliation_snapshot(state)
    return {**snap.as_dict(), "reconciliation_hash": snap.snapshot_hash,
            "evaluated_at": now_iso()}


@app.post("/v1/pickups")
async def record_pickup(
    body: PickupRequest,
    principal: AgentPrincipal = Depends(require_tool("record_pickup")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    request = ActionRequest(
        action_id=scan_action_id(body.incident_id, body.container_id, "pickup"),
        action_type=ActionType.CUSTODY_PICKUP,
        incident_id=body.incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={
            "container_id": body.container_id,
            "responder_authorized": _responder_authorized(repo, body.incident_id, body.responder_id),
        },
        now=now_iso(),
    )

    def build(ctx: TxnContext, state: KernelState, req: ActionRequest) -> EffectResult:
        evidence = ScanEvidence(
            scan_id=f"SCN-{req.action_id[:12]}",
            container_id=body.container_id,
            location_ref=body.source_freezer,
            scanned_at=req.now,
            responder_id=body.responder_id,
            signature=body.scan_signature or "unsigned-demo-scan",
            simulated=body.simulated,
        )
        existing = state.transfers.get(f"TR-{body.incident_id}-{body.container_id}")
        transfer = Transfer(
            transfer_id=f"TR-{body.incident_id}-{body.container_id}",
            incident_id=body.incident_id,
            container_id=body.container_id,
            source_freezer=body.source_freezer,
            destination_freezer=body.destination_freezer,
            destination_slot=body.destination_slot,
            reservation_id=body.reservation_id or _reservation_for(state, body.destination_freezer),
            pickup_evidence=evidence,
            destination_evidence=existing.destination_evidence if existing else None,
            state=CustodyState.PICKED_UP,
        )
        ctx.set("transfers", transfer.transfer_id, transfer.model_dump(mode="json"))
        container = state.containers[body.container_id]
        ctx.set(
            "containers",
            container.id,
            container.model_copy(update={"custody_state": CustodyState.PICKED_UP}).model_dump(
                mode="json"
            ),
        )
        return EffectResult(
            effect_ref=transfer.transfer_id,
            collection="transfers",
            summary=f"{body.container_id} picked up from {body.source_freezer}",
            evidence_sources=["custody:record_pickup"],
            detail={"destination_freezer": body.destination_freezer,
                    "simulated": body.simulated},
        )

    return commit_effect(repo, request, build, trace_id=body.trace_id).as_dict()


@app.post("/v1/destination-scans")
async def record_destination_scan(
    body: DestinationScanRequest,
    principal: AgentPrincipal = Depends(require_tool("record_destination_scan")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """A destination scan that disagrees with the plan is refused, and the container is
    driven to UNRESOLVED rather than quietly re-pointed (D14)."""
    request = ActionRequest(
        action_id=scan_action_id(body.incident_id, body.container_id, "destination"),
        action_type=ActionType.CUSTODY_DESTINATION_SCAN,
        incident_id=body.incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={
            "container_id": body.container_id,
            "destination_freezer_id": body.destination_freezer_id,
            "responder_authorized": _responder_authorized(repo, body.incident_id, body.responder_id),
        },
        now=now_iso(),
    )

    def build(ctx: TxnContext, state: KernelState, req: ActionRequest) -> EffectResult:
        transfer = state.transfers[f"TR-{body.incident_id}-{body.container_id}"]
        reading = _latest_reading(repo, body.destination_freezer_id)
        evidence = ScanEvidence(
            scan_id=f"SCN-{req.action_id[:12]}",
            container_id=body.container_id,
            location_ref=body.destination_slot,
            scanned_at=req.now,
            responder_id=body.responder_id,
            signature=body.scan_signature or "unsigned-demo-scan",
            simulated=body.simulated,
        )
        updated = transfer.model_copy(
            update={
                "destination_evidence": evidence,
                "state": CustodyState.RECEIVED,
                "destination_temp_reading_id": reading[0],
                "destination_temp_c": reading[1],
                "destination_temp_recorded_at": reading[2],
            }
        )
        ctx.set("transfers", updated.transfer_id, updated.model_dump(mode="json"))
        container = state.containers[body.container_id]
        ctx.set(
            "containers",
            container.id,
            container.model_copy(update={"custody_state": CustodyState.RECEIVED}).model_dump(
                mode="json"
            ),
        )
        return EffectResult(
            effect_ref=updated.transfer_id,
            collection="transfers",
            summary=f"{body.container_id} received at {body.destination_freezer_id}",
            evidence_sources=["custody:record_destination_scan",
                              "telemetry:get_destination_temperature"],
            detail={
                "destination_slot": body.destination_slot,
                "destination_temp_c": reading[1],
                "destination_temp_recorded_at": reading[2],
                "simulated": body.simulated,
            },
        )

    return commit_effect(repo, request, build, trace_id=body.trace_id).as_dict()


@app.post("/v1/commits")
async def commit_transfer(
    body: CommitRequest,
    principal: AgentPrincipal = Depends(require_tool("commit_transfer")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """The authoritative location change. Every N3 and N4 precondition applies here."""
    state = repo.load_kernel_state(body.incident_id)
    transfer = state.transfers.get(f"TR-{body.incident_id}-{body.container_id}")
    destination = transfer.destination_freezer if transfer else ""
    slot = transfer.destination_slot if transfer else ""
    reservation_id = transfer.reservation_id if transfer else None

    # Re-read destination temperature at commit time. The reading captured at the
    # destination scan may already be stale, and D8 turns on exactly that gap.
    reading = _latest_reading(repo, destination) if destination else (None, None, None)

    request = ActionRequest(
        action_id=transfer_action_id(body.incident_id, body.container_id, slot),
        action_type=ActionType.CUSTODY_COMMIT,
        incident_id=body.incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={
            "container_id": body.container_id,
            "destination_freezer_id": destination,
            "reservation_id": reservation_id,
            "responder_authorized": True,
            "destination_temp_c": reading[1],
            "destination_temp_recorded_at": reading[2],
        },
        now=now_iso(),
    )

    def build(ctx: TxnContext, kstate: KernelState, req: ActionRequest) -> EffectResult:
        t = kstate.transfers[f"{'TR'}-{body.incident_id}-{body.container_id}"]
        committed = t.model_copy(
            update={
                "state": CustodyState.COMMITTED,
                "commit_receipt": f"RCP-{req.action_id[:16]}",
                "destination_temp_reading_id": reading[0],
                "destination_temp_c": reading[1],
                "destination_temp_recorded_at": reading[2],
            }
        )
        ctx.set("transfers", committed.transfer_id, committed.model_dump(mode="json"))

        container = kstate.containers[body.container_id]
        ctx.set(
            "containers",
            container.id,
            container.model_copy(
                update={
                    "custody_state": CustodyState.COMMITTED,
                    "freezer_id": committed.destination_freezer,
                    "slot_id": committed.destination_slot,
                }
            ).model_dump(mode="json"),
        )

        # Consume one slot of the backing reservation and move occupancy with it, so
        # capacity arithmetic keeps matching physical reality.
        reservation = kstate.reservations.get(reservation_id or "")
        if reservation is not None:
            remaining = max(0, reservation.held_slots - 1)
            ctx.set(
                "reservations",
                reservation.id,
                reservation.model_copy(
                    update={
                        "slots_remaining": remaining,
                        "state": (
                            ReservationState.CONSUMED if remaining == 0 else reservation.state
                        ),
                        "updated_at": req.now,
                    }
                ).model_dump(mode="json"),
            )
        dest = kstate.freezers.get(committed.destination_freezer)
        if dest is not None:
            ctx.set(
                "freezers",
                dest.id,
                dest.model_copy(
                    update={"occupied_slots": min(dest.total_slots, dest.occupied_slots + 1)}
                ).model_dump(mode="json"),
            )
        source = kstate.freezers.get(committed.source_freezer)
        if source is not None:
            ctx.set(
                "freezers",
                source.id,
                source.model_copy(
                    update={"occupied_slots": max(0, source.occupied_slots - 1)}
                ).model_dump(mode="json"),
            )

        return EffectResult(
            effect_ref=committed.transfer_id,
            collection="transfers",
            summary=(
                f"Custody committed: {body.container_id} now authoritative in "
                f"{committed.destination_freezer} slot {committed.destination_slot}"
            ),
            evidence_sources=[
                "custody:record_pickup",
                "custody:record_destination_scan",
                "telemetry:get_destination_temperature",
                "capacity:get_reservation",
            ],
            detail={
                "destination_freezer": committed.destination_freezer,
                "destination_slot": committed.destination_slot,
                "destination_temp_c": reading[1],
                "destination_temp_recorded_at": reading[2],
                "reservation_id": reservation_id,
            },
        )

    return commit_effect(repo, request, build, trace_id=body.trace_id).as_dict()


@app.post("/v1/commits/batch")
async def commit_ready_transfers(
    body: CommitBatchRequest,
    principal: AgentPrincipal = Depends(require_tool("commit_transfer")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Commit every container whose evidence is complete.

    Not a bulk override. Each container runs the full single-commit path — same action
    ID, same N3/N4 evaluation, same receipt — so a batch where one destination has
    warmed commits the rest and refuses that one, with the reason attached to it
    specifically.
    """
    state = repo.load_kernel_state(body.incident_id)
    ready = sorted(
        t.container_id
        for t in state.transfers.values()
        if t.state is CustodyState.RECEIVED
    )
    committed: list[str] = []
    refused: list[dict[str, Any]] = []
    duplicates: list[str] = []

    for container_id in ready[: body.limit]:
        outcome = await commit_transfer(
            CommitRequest(incident_id=body.incident_id, container_id=container_id,
                          trace_id=body.trace_id),
            principal=principal,
            repo=repo,
        )
        receipt = outcome["receipt"]
        if outcome.get("duplicate_returned"):
            duplicates.append(container_id)
        elif receipt["status"] == "COMMITTED":
            committed.append(container_id)
        else:
            refused.append(
                {
                    "container_id": container_id,
                    "status": receipt["status"],
                    "invariant": outcome["decision"].get("invariant"),
                    "reason": outcome["decision"].get("reason"),
                }
            )

    return {
        "incident_id": body.incident_id,
        "ready_count": len(ready),
        "attempted": len(ready[: body.limit]),
        "committed": committed,
        "committed_count": len(committed),
        "duplicates": duplicates,
        "refused": refused,
        "refused_count": len(refused),
    }


@app.post("/v1/exceptions")
async def flag_custody_exception(
    body: ExceptionRequest,
    principal: AgentPrincipal = Depends(require_tool("flag_custody_exception")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Record an unresolved or contradictory movement.

    This is how a container reaches an honest terminal state without anyone inventing
    a reconciliation. UNRESOLVED keeps the incident open; QUARANTINED is a real
    disposition and counts as resolved.
    """
    disposition = CustodyState(body.disposition)
    request = ActionRequest(
        action_id=scan_action_id(body.incident_id, body.container_id, f"exception:{body.disposition}"),
        action_type=ActionType.CUSTODY_EXCEPTION,
        incident_id=body.incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={"container_id": body.container_id, "disposition": body.disposition},
        now=now_iso(),
    )

    def build(ctx: TxnContext, state: KernelState, req: ActionRequest) -> EffectResult:
        container = state.containers[body.container_id]
        ctx.set(
            "containers",
            container.id,
            container.model_copy(update={"custody_state": disposition}).model_dump(mode="json"),
        )
        transfer = state.transfers.get(f"TR-{body.incident_id}-{body.container_id}")
        if transfer is not None:
            ctx.set(
                "transfers",
                transfer.transfer_id,
                transfer.model_copy(
                    update={"state": disposition, "exception_reason": body.reason}
                ).model_dump(mode="json"),
            )
        return EffectResult(
            effect_ref=f"EXC-{req.action_id[:12]}",
            collection="containers",
            summary=f"{body.container_id} marked {body.disposition}: {body.reason}",
            evidence_sources=["custody:get_custody_state"],
            detail={"disposition": body.disposition, "reason": body.reason},
        )

    return commit_effect(repo, request, build, trace_id=body.trace_id).as_dict()


# --------------------------------------------------------------------------------------


def _responder_authorized(repo: Repository, incident_id: str, responder_id: str) -> bool:
    """A responder is authorized when an open dispatch for this incident names them."""
    return any(
        d.responder_id == responder_id and d.status != "CANCELLED"
        for d in repo.list_dispatches(incident_id)
    )


def _reservation_for(state: KernelState, destination: str) -> str | None:
    live = [
        r
        for r in state.reservations.values()
        if r.destination_freezer_id == destination
        and r.state in {ReservationState.ACTIVE, ReservationState.CONSUMED}
        and state.incident is not None
        and r.incident_id == state.incident.id
    ]
    return live[0].id if live else None


def _latest_reading(repo: Repository, freezer_id: str) -> tuple[str | None, float | None, str | None]:
    readings = repo.list_readings(freezer_id)
    if readings:
        latest = readings[-1]
        return latest.id, latest.celsius, latest.recorded_at
    f = repo.get_freezer(freezer_id)
    if f is None:
        return None, None, None
    return None, f.current_temp_c, f.last_reading_at
