"""Capacity Service (PRD §17.3).

Owns backup freezer availability and reservations. The reservation path is the sharpest
edge in the product: the capacity read and the reservation write happen inside one
Firestore transaction, so two incidents racing for the last slots cannot both win.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends
from pydantic import BaseModel, Field

from nightshift.common.clock import now_iso
from nightshift.common.ids import release_reservation_action_id, reservation_action_id
from nightshift.common.store import TxnContext
from nightshift.safety_kernel import ActionRequest, KernelState
from nightshift.safety_kernel.config import DEFAULT_CONFIG
from nightshift.safety_kernel.invariants import n4_would_hold
from nightshift.schemas.core import Reservation
from nightshift.schemas.enums import ActionType, ReservationState
from services.common.app import create_app, get_repository, require_tool
from services.common.effects import EffectResult, commit_effect
from services.common.identity import AgentPrincipal
from services.common.repository import Repository

app = create_app(
    service_name="capacity",
    title="Night Shift — Capacity Service",
    description="Verified backup capacity and transactional reservations.",
)


class ReserveRequest(BaseModel):
    incident_id: str
    destination_freezer_id: str
    placement_group_id: str
    slots: int = Field(gt=0)
    slot_ids: list[str] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)
    trace_id: str | None = None


class ReleaseRequest(BaseModel):
    incident_id: str
    reservation_id: str
    reason: str = ""
    trace_id: str | None = None


@app.get("/v1/destinations")
async def list_qualified_destinations(
    incident_id: str,
    required_temp_c: float = -80.0,
    _p: AgentPrincipal = Depends(require_tool("list_qualified_destinations")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Backup freezers that are actually usable right now.

    'Qualified' is not a label on the freezer record alone — a freezer that is
    nominally a backup but currently sitting above the ULT ceiling is reported as
    ineligible with the reason attached, so the Broker plans against reality rather
    than against a flag.
    """
    incident = repo.get_incident(incident_id)
    failed = incident.failed_freezer_id if incident else ""
    now = now_iso()

    out = []
    for f in repo.list_freezers():
        if f.id == failed:
            continue
        reserved = sum(
            r.held_slots
            for r in repo.list_reservations(destination_freezer_id=f.id)
            if r.state
            in {ReservationState.PROPOSED, ReservationState.ACTIVE, ReservationState.CONSUMED}
        )
        temp_ok, temp_reason = n4_would_hold(f.current_temp_c, f.last_reading_at, now)
        held = repo.get_hold(f.id)
        reasons = []
        if not f.is_backup_qualified:
            reasons.append("not designated as a backup destination")
        if not temp_ok:
            reasons.append(temp_reason)
        if held is not None and held.active:
            reasons.append("under an active containment hold")
        free = max(0, f.free_slots - reserved)
        if free <= 0:
            reasons.append("no unreserved slots")

        out.append(
            {
                "freezer_id": f.id,
                "label": f.label,
                "zone": f.zone,
                "current_temp_c": f.current_temp_c,
                "last_reading_at": f.last_reading_at,
                "total_slots": f.total_slots,
                "occupied_slots": f.occupied_slots,
                "reserved_slots": reserved,
                "unreserved_free_slots": free,
                "eligible": not reasons,
                "ineligible_reasons": reasons,
            }
        )
    out.sort(key=lambda r: (not bool(r["eligible"]), -int(str(r["unreserved_free_slots"]))))
    return {
        "incident_id": incident_id,
        "required_temp_c": required_temp_c,
        "evaluated_at": now,
        "destination_temp_ceiling_c": DEFAULT_CONFIG.destination_temp_ceiling_c,
        "destinations": out,
    }


@app.get("/v1/capacity/{freezer_id}")
async def get_capacity(
    freezer_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_capacity")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    freezer = repo.get_freezer(freezer_id)
    if freezer is None:
        return {"freezer_id": freezer_id, "known": False}
    reserved = sum(
        r.held_slots
        for r in repo.list_reservations(destination_freezer_id=freezer_id)
        if r.state
        in {ReservationState.PROPOSED, ReservationState.ACTIVE, ReservationState.CONSUMED}
    )
    return {
        "freezer_id": freezer_id,
        "known": True,
        "verified_available_slots": freezer.free_slots,
        "reserved_slots": reserved,
        "unreserved_free_slots": max(0, freezer.free_slots - reserved),
        "current_temp_c": freezer.current_temp_c,
        "last_reading_at": freezer.last_reading_at,
        "source": "authoritative",
    }


@app.get("/v1/reservations/{reservation_id}")
async def get_reservation(
    reservation_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_reservation")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    reservation = repo.get_reservation(reservation_id)
    if reservation is None:
        return {"reservation_id": reservation_id, "found": False}
    return {"found": True, "reservation": reservation.model_dump(mode="json")}


@app.post("/v1/reservations")
async def reserve_capacity(
    body: ReserveRequest,
    principal: AgentPrincipal = Depends(require_tool("reserve_capacity")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Reserve slots. Idempotent on (incident, destination, placement group)."""
    outcome: dict[str, Any] = reserve_capacity_op(repo, principal, body).as_dict()
    return outcome


def reserve_capacity_op(repo: Repository, principal: AgentPrincipal, body: ReserveRequest) -> Any:
    action_id = reservation_action_id(
        body.incident_id, body.destination_freezer_id, body.placement_group_id
    )
    request = ActionRequest(
        action_id=action_id,
        action_type=ActionType.CAPACITY_RESERVE,
        incident_id=body.incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={
            "destination_freezer_id": body.destination_freezer_id,
            "placement_group_id": body.placement_group_id,
            "slots": body.slots,
            "evidence_sources": body.evidence_sources or ["capacity:get_capacity"],
        },
        now=now_iso(),
    )

    def build(ctx: TxnContext, state: KernelState, req: ActionRequest) -> EffectResult:
        reservation = Reservation(
            id=f"RES-{req.action_id[:12]}",
            action_id=req.action_id,
            incident_id=req.incident_id,
            destination_freezer_id=body.destination_freezer_id,
            placement_group_id=body.placement_group_id,
            slots=body.slots,
            slots_remaining=body.slots,
            slot_ids=body.slot_ids,
            state=ReservationState.ACTIVE,
            created_at=req.now,
            updated_at=req.now,
        )
        ctx.set("reservations", reservation.id, reservation.model_dump(mode="json"))
        return EffectResult(
            effect_ref=reservation.id,
            collection="reservations",
            summary=(
                f"Reserved {body.slots} slot(s) in {body.destination_freezer_id} "
                f"for group {body.placement_group_id}"
            ),
            evidence_sources=req.payload["evidence_sources"],
            detail={
                "destination_freezer_id": body.destination_freezer_id,
                "slots": body.slots,
                "verified_available_at_commit": state.verified_available_slots(
                    body.destination_freezer_id
                ),
                "already_reserved_at_commit": state.reserved_slots(body.destination_freezer_id),
            },
        )

    return commit_effect(repo, request, build, trace_id=body.trace_id)


@app.post("/v1/reservations/{reservation_id}/release")
async def release_reservation(
    reservation_id: str,
    body: ReleaseRequest,
    principal: AgentPrincipal = Depends(require_tool("release_reservation")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    action_id = release_reservation_action_id(body.incident_id, reservation_id)
    request = ActionRequest(
        action_id=action_id,
        action_type=ActionType.CAPACITY_RELEASE,
        incident_id=body.incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={"reservation_id": reservation_id, "reason": body.reason},
        now=now_iso(),
    )

    def build(ctx: TxnContext, state: KernelState, req: ActionRequest) -> EffectResult:
        current = state.reservations.get(reservation_id)
        if current is None:
            raise ValueError(f"reservation {reservation_id!r} does not exist")
        released = current.model_copy(
            update={
                "state": ReservationState.RELEASED,
                "updated_at": req.now,
                "invalidation_reason": body.reason or "released by capacity broker",
            }
        )
        ctx.set("reservations", released.id, released.model_dump(mode="json"))
        return EffectResult(
            effect_ref=released.id,
            collection="reservations",
            summary=f"Released reservation {released.id} on {released.destination_freezer_id}",
            evidence_sources=["capacity:get_reservation"],
            detail={"reason": body.reason},
        )

    return commit_effect(repo, request, build, trace_id=body.trace_id).as_dict()


TOOL_ROUTES: dict[str, tuple[str, str]] = {
    "list_qualified_destinations": ("GET", "/v1/destinations"),
    "get_capacity": ("GET", "/v1/capacity/{freezer_id}"),
    "get_reservation": ("GET", "/v1/reservations/{reservation_id}"),
    "reserve_capacity": ("POST", "/v1/reservations"),
    "release_reservation": ("POST", "/v1/reservations/{reservation_id}/release"),
}
