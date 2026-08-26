"""One entry point: ``evaluate_action``.

Every mutating domain service runs the same seven-step sequence from PRD §16, and step
five is this function. Keeping it in one place is what makes the offline verifier able
to re-derive whether a committed effect *should* have been allowed.
"""

from __future__ import annotations

from typing import Any

from nightshift.common.ids import close_action_id, reservation_action_id
from nightshift.safety_kernel.config import DEFAULT_CONFIG, KernelConfig
from nightshift.safety_kernel.decision import Decision, allow, refuse
from nightshift.safety_kernel.invariants import (
    n1_would_hold,
    n3_would_hold,
    n4_would_hold,
    n6_would_hold,
    n7_would_hold,
    n8_would_hold,
    n10_would_hold,
    n13_blocks_operation,
    n13_release_would_hold,
)
from nightshift.safety_kernel.transitions import can_transition_incident, custody_transition
from nightshift.safety_kernel.world import ActionRequest, KernelState, reconciliation_snapshot
from nightshift.schemas.enums import (
    ActionType,
    CustodyState,
    IncidentState,
    ReservationState,
)


def evaluate_action(
    state: KernelState,
    request: ActionRequest,
    *,
    config: KernelConfig = DEFAULT_CONFIG,
) -> Decision:
    """Decide whether ``request`` may commit against ``state``.

    Returns ALLOW, REFUSE, or UNAVAILABLE. Never raises for a business reason — a
    refusal is data, and it ends up in the ledger and on screen.
    """
    # N7 — the identity must be allowed to produce this class of effect at all.
    ok, reason = n7_would_hold(request.action_type, request.actor_identity)
    if not ok:
        return refuse("N7", reason, detail={"action_type": request.action_type.value})

    # N10 — an unqualified revision may not take consequential work.
    if request.requested_by_agent is not None:
        ok, reason = n10_would_hold(
            state, request.requested_by_agent.value, request.requested_by_agent_revision
        )
        if not ok:
            from nightshift.schemas.enums import DenialReason, FailureClass

            return refuse(
                "N10",
                reason,
                denial_reason=DenialReason.REVISION_NOT_QUALIFIED,
                failure_class=FailureClass.POLICY_DENIAL,
            )

    # N8 — nothing commits on memory alone.
    sources = [str(s) for s in request.payload.get("evidence_sources", [])]
    ok, reason = n8_would_hold(sources)
    if not ok:
        return refuse("N8", reason, detail={"evidence_sources": sources})

    handler = _HANDLERS.get(request.action_type)
    if handler is None:
        return allow({"note": "no additional preconditions for this action type"})
    return handler(state, request, config)


# --------------------------------------------------------------------------------------
# Per-action preconditions
# --------------------------------------------------------------------------------------


def _pre_capacity_reserve(
    state: KernelState, req: ActionRequest, config: KernelConfig
) -> Decision:
    freezer_id = str(req.payload.get("destination_freezer_id", ""))
    group_id = str(req.payload.get("placement_group_id", ""))
    slots = int(req.payload.get("slots", 0))

    if slots <= 0:
        return refuse("N1", "reservation must request a positive number of slots")

    expected = reservation_action_id(req.incident_id, freezer_id, group_id)
    if req.action_id != expected:
        return refuse(
            "N2",
            "reservation action_id does not match its semantic key; a retry with a "
            "different key would create a second effect",
            detail={"expected": expected, "received": req.action_id},
        )

    freezer = state.freezers.get(freezer_id)
    if freezer is None:
        return refuse("N1", f"destination freezer {freezer_id!r} is unknown")
    if not freezer.is_backup_qualified:
        return refuse("N1", f"{freezer_id} is not qualified to receive rescued material")

    # Destination must be cold enough *now* to be worth reserving. The freshness
    # re-check happens again at commit time (N4) because it can warm in between (D8).
    ok, reason = n4_would_hold(freezer.current_temp_c, freezer.last_reading_at, req.now, config)
    if not ok:
        return refuse("N4", f"destination {freezer_id} is not a safe target: {reason}")

    if state.active_hold(freezer_id) is not None:
        return refuse("N13", f"{freezer_id} is under a containment hold and cannot receive material")

    # One live reservation per placement group. Without this, a broker that loses a
    # reservation response and re-plans to a different destination derives a *different*
    # action id and legitimately creates a second reservation — booking space for the
    # same boxes in two freezers and withholding capacity a competing incident needs.
    # Re-planning is still allowed; it just has to release the first reservation.
    existing = [
        r
        for r in state.reservations.values()
        if r.incident_id == req.incident_id
        and r.placement_group_id == group_id
        and r.state in {ReservationState.PROPOSED, ReservationState.ACTIVE}
        and r.destination_freezer_id != freezer_id
    ]
    if existing:
        held = existing[0]
        return refuse(
            "N1",
            f"placement group {group_id} already holds a live reservation on "
            f"{held.destination_freezer_id} ({held.id}); release it before reserving "
            f"the same material into {freezer_id}",
            detail={
                "placement_group_id": group_id,
                "existing_reservation_id": held.id,
                "existing_destination": held.destination_freezer_id,
                "requested_destination": freezer_id,
            },
        )

    if not n1_would_hold(state, freezer_id, slots):
        return refuse(
            "N1",
            f"{freezer_id} has {state.verified_available_slots(freezer_id)} verified free slot(s) "
            f"with {state.reserved_slots(freezer_id)} already reserved; "
            f"cannot also reserve {slots}",
            detail={
                "freezer_id": freezer_id,
                "requested": slots,
                "already_reserved": state.reserved_slots(freezer_id),
                "verified_available": state.verified_available_slots(freezer_id),
            },
        )
    return allow({"freezer_id": freezer_id, "slots": slots})


def _pre_containment_hold(
    state: KernelState, req: ActionRequest, _config: KernelConfig
) -> Decision:
    if state.incident is None:
        return refuse("N13", "cannot place a containment hold without an incident")
    freezer_id = str(req.payload.get("freezer_id", ""))
    if freezer_id != state.incident.failed_freezer_id:
        return refuse(
            "N13",
            "containment hold must target the incident's failed freezer",
            detail={"requested": freezer_id, "incident_freezer": state.incident.failed_freezer_id},
        )
    if freezer_id not in state.freezers:
        return refuse("N13", f"unknown freezer {freezer_id!r}")
    return allow({"freezer_id": freezer_id})


def _pre_release_hold(state: KernelState, req: ActionRequest, config: KernelConfig) -> Decision:
    freezer_id = str(req.payload.get("freezer_id", ""))
    hold = state.active_hold(freezer_id)
    if hold is None:
        return refuse("N13", f"no active containment hold on {freezer_id}")
    readings = [
        (str(r["recorded_at"]), float(r["celsius"]))
        for r in req.payload.get("validation_readings", [])
    ]
    ok, reason = n13_release_would_hold(state, freezer_id, readings, req.now, config)
    if not ok:
        return refuse("N13", f"containment hold on {freezer_id} may not release: {reason}")
    return allow({"freezer_id": freezer_id, "validation_readings": len(readings)})


def _pre_work_order(state: KernelState, req: ActionRequest, _config: KernelConfig) -> Decision:
    freezer_id = str(req.payload.get("freezer_id", ""))
    if freezer_id not in state.freezers:
        return refuse("N2", f"work order references unknown freezer {freezer_id!r}")
    if state.incident is None:
        return refuse("N2", "work order requires an incident")
    return allow({"freezer_id": freezer_id})


def _pre_dispatch(state: KernelState, req: ActionRequest, _config: KernelConfig) -> Decision:
    if state.incident is None:
        return refuse("N2", "dispatch requires an incident")
    responder_id = str(req.payload.get("responder_id", ""))
    if not responder_id:
        return refuse("N2", "dispatch requires a responder")
    return allow({"responder_id": responder_id})


def _pre_custody_pickup(state: KernelState, req: ActionRequest, _config: KernelConfig) -> Decision:
    container_id = str(req.payload.get("container_id", ""))
    if container_id not in set(state.incident_container_ids()):
        return refuse("N3", f"{container_id} is not part of this incident")
    container = state.containers.get(container_id)
    if container is None:
        return refuse("N3", f"container {container_id!r} record unavailable")
    if not bool(req.payload.get("responder_authorized", False)):
        return refuse("N3", "responder credential is not valid for this incident")
    return custody_transition(container.custody_state, CustodyState.PICKED_UP)


def _pre_custody_destination_scan(
    state: KernelState, req: ActionRequest, _config: KernelConfig
) -> Decision:
    container_id = str(req.payload.get("container_id", ""))
    container = state.containers.get(container_id)
    if container is None:
        return refuse("N3", f"container {container_id!r} record unavailable")
    if container_id not in set(state.incident_container_ids()):
        return refuse("N3", f"{container_id} is not part of this incident")
    if not bool(req.payload.get("responder_authorized", False)):
        return refuse("N3", "responder credential is not valid for this incident")

    scanned_destination = str(req.payload.get("destination_freezer_id", ""))
    transfers = state.transfers_for_container(container_id)
    if transfers and transfers[0].destination_freezer != scanned_destination:
        # D14: contradictory scan. Never invent a reconciliation.
        return refuse(
            "N11",
            f"{container_id} scanned at {scanned_destination} but its transfer plan targets "
            f"{transfers[0].destination_freezer}; container must be marked UNRESOLVED",
            detail={
                "container_id": container_id,
                "scanned_at": scanned_destination,
                "planned": transfers[0].destination_freezer,
                "required_disposition": CustodyState.UNRESOLVED.value,
            },
        )
    return custody_transition(container.custody_state, CustodyState.RECEIVED)


def _pre_custody_commit(state: KernelState, req: ActionRequest, config: KernelConfig) -> Decision:
    container_id = str(req.payload.get("container_id", ""))
    destination = str(req.payload.get("destination_freezer_id", ""))
    reservation_id = req.payload.get("reservation_id")
    responder_authorized = bool(req.payload.get("responder_authorized", False))

    ok, reason = n3_would_hold(
        state, container_id, destination, reservation_id, responder_authorized
    )
    if not ok:
        return refuse("N3", f"custody commit refused: {reason}",
                      detail={"container_id": container_id})

    ok, reason = n4_would_hold(
        req.payload.get("destination_temp_c"),
        req.payload.get("destination_temp_recorded_at"),
        req.now,
        config,
    )
    if not ok:
        return refuse("N4", f"custody commit refused: {reason}",
                      detail={"container_id": container_id, "destination": destination})

    container = state.containers.get(container_id)
    assert container is not None  # n3_would_hold already proved it exists
    return custody_transition(container.custody_state, CustodyState.COMMITTED)


def _pre_incident_close(state: KernelState, req: ActionRequest, _config: KernelConfig) -> Decision:
    if state.incident is None:
        return refuse("N6", "no incident to close")

    snap = reconciliation_snapshot(state)
    expected = close_action_id(req.incident_id, snap.snapshot_hash)
    if req.action_id != expected:
        return refuse(
            "N6",
            "close action_id does not match the current reconciliation snapshot; "
            "a stale close request cannot replay an earlier receipt",
            detail={"expected": expected, "received": req.action_id},
        )

    ok, reason = n6_would_hold(state)
    if not ok:
        return refuse("N6", reason, detail=snap.as_dict())

    return can_transition_incident(state, IncidentState.CLOSED)


def _pre_incident_transition(
    state: KernelState, req: ActionRequest, config: KernelConfig
) -> Decision:
    raw = str(req.payload.get("to_state", ""))
    try:
        to_state = IncidentState(raw)
    except ValueError:
        return refuse("SM-INCIDENT", f"{raw!r} is not a known incident state")
    return can_transition_incident(state, to_state, config=config)


def _pre_impact_snapshot(state: KernelState, req: ActionRequest, _config: KernelConfig) -> Decision:
    if not bool(req.payload.get("inventory_complete", False)):
        # D15: the adapter could not enumerate everything. Refuse rather than record a
        # partial impact set that would later read as authoritative.
        return refuse(
            "N11",
            "inventory enumeration was incomplete; an authoritative impact snapshot may "
            "not be recorded from a partial read",
        )
    container_ids = req.payload.get("container_ids", [])
    if not container_ids:
        return refuse("N11", "impact snapshot with zero containers is not a usable impact set")
    return allow({"containers": len(container_ids)})


def _pre_inventory_operation(
    state: KernelState, req: ActionRequest, _config: KernelConfig
) -> Decision:
    """N13: normal placement/withdrawal on a held freezer is refused."""
    freezer_id = str(req.payload.get("freezer_id", ""))
    is_rescue = bool(req.payload.get("is_rescue_operation", False))
    if n13_blocks_operation(state, freezer_id, is_rescue):
        return refuse(
            "N13",
            f"{freezer_id} is under an active containment hold; normal inventory operations "
            "are refused until the hold releases through a valid recovery transition",
        )
    return allow()


_HANDLERS: dict[ActionType, Any] = {
    ActionType.CAPACITY_RESERVE: _pre_capacity_reserve,
    ActionType.CONTAINMENT_HOLD: _pre_containment_hold,
    ActionType.RELEASE_HOLD: _pre_release_hold,
    ActionType.WORK_ORDER_CREATE: _pre_work_order,
    ActionType.DISPATCH_RESPONDER: _pre_dispatch,
    ActionType.CUSTODY_PICKUP: _pre_custody_pickup,
    ActionType.CUSTODY_DESTINATION_SCAN: _pre_custody_destination_scan,
    ActionType.CUSTODY_COMMIT: _pre_custody_commit,
    ActionType.INCIDENT_CLOSE: _pre_incident_close,
    ActionType.INCIDENT_TRANSITION: _pre_incident_transition,
    ActionType.IMPACT_SNAPSHOT: _pre_impact_snapshot,
}


def check_normal_inventory_operation(state: KernelState, freezer_id: str) -> Decision:
    """Public helper for the Inventory Service's non-rescue paths (N13)."""
    return _pre_inventory_operation(
        state,
        ActionRequest(
            action_id="",
            action_type=ActionType.CONTAINMENT_HOLD,
            incident_id="",
            actor_identity="incident-ingestor",
            payload={"freezer_id": freezer_id, "is_rescue_operation": False},
        ),
        DEFAULT_CONFIG,
    )
