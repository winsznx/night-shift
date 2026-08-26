"""Deterministic transition guards for every state machine (PRD §18, §19).

States never advance because an agent said so. They advance because a guard here looked
at the snapshot and agreed. The Commander may *request* a transition; the Incident
Control Service owns transition truth and asks this module.
"""

from __future__ import annotations

from nightshift.safety_kernel.config import DEFAULT_CONFIG, KernelConfig
from nightshift.safety_kernel.decision import Decision, allow, refuse
from nightshift.safety_kernel.invariants import n6_would_hold
from nightshift.safety_kernel.world import KernelState, reconciliation_snapshot
from nightshift.schemas.enums import (
    ActionStatus,
    ActionType,
    CustodyState,
    FreezerState,
    IncidentState,
    ReservationState,
)

# --------------------------------------------------------------------------------------
# Incident
# --------------------------------------------------------------------------------------

_S = IncidentState

INCIDENT_TRANSITIONS: dict[IncidentState, frozenset[IncidentState]] = {
    _S.OBSERVING: frozenset({
        _S.CONFIRMED, _S.ABORTED_SAFE, _S.NEEDS_REASSESSMENT, _S.ESCALATED,
    }),
    _S.CONFIRMED: frozenset({
        _S.CONTAINED, _S.NEEDS_REASSESSMENT, _S.ESCALATED, _S.ABORTED_SAFE,
    }),
    _S.CONTAINED: frozenset({
        _S.RESCUE_PLANNING, _S.NEEDS_REASSESSMENT, _S.ESCALATED, _S.PARTIAL,
    }),
    _S.RESCUE_PLANNING: frozenset({
        _S.CAPACITY_RESERVED, _S.NEEDS_REASSESSMENT, _S.ESCALATED, _S.PARTIAL,
    }),
    _S.CAPACITY_RESERVED: frozenset({
        _S.DISPATCHED, _S.RESCUE_PLANNING, _S.NEEDS_REASSESSMENT, _S.ESCALATED, _S.PARTIAL,
    }),
    _S.DISPATCHED: frozenset({
        _S.TRANSFER_IN_PROGRESS, _S.RESCUE_PLANNING, _S.NEEDS_REASSESSMENT,
        _S.ESCALATED, _S.PARTIAL,
    }),
    _S.TRANSFER_IN_PROGRESS: frozenset({
        _S.RECOVERY_MONITORING, _S.RECONCILING, _S.RESCUE_PLANNING,
        _S.NEEDS_REASSESSMENT, _S.ESCALATED, _S.PARTIAL,
    }),
    _S.RECOVERY_MONITORING: frozenset({
        _S.RECONCILING, _S.NEEDS_REASSESSMENT, _S.ESCALATED, _S.PARTIAL,
    }),
    _S.RECONCILING: frozenset({
        _S.CLOSED, _S.PARTIAL, _S.NEEDS_REASSESSMENT, _S.ESCALATED,
    }),
    _S.CLOSED: frozenset(),
    _S.ABORTED_SAFE: frozenset(),

    # Non-success states are recoverable — that is the point of having them.
    _S.NEEDS_REASSESSMENT: frozenset({
        _S.OBSERVING, _S.CONFIRMED, _S.CONTAINED, _S.RESCUE_PLANNING,
        _S.CAPACITY_RESERVED, _S.DISPATCHED, _S.TRANSFER_IN_PROGRESS,
        _S.RECOVERY_MONITORING, _S.RECONCILING, _S.ESCALATED, _S.ABORTED_SAFE,
    }),
    _S.ESCALATED: frozenset({
        _S.RESCUE_PLANNING, _S.RECONCILING, _S.PARTIAL, _S.ABORTED_SAFE,
        _S.NEEDS_REASSESSMENT,
    }),
    _S.PARTIAL: frozenset({
        _S.RECONCILING, _S.ESCALATED, _S.NEEDS_REASSESSMENT, _S.ABORTED_SAFE,
    }),
}


def can_transition_incident(
    state: KernelState,
    to_state: IncidentState,
    *,
    config: KernelConfig = DEFAULT_CONFIG,
) -> Decision:
    """Guard one incident transition against the snapshot."""
    if state.incident is None:
        return refuse("SM-INCIDENT", "no incident to transition")

    frm = state.incident.state
    if to_state == frm:
        return allow({"noop": True})

    allowed = INCIDENT_TRANSITIONS.get(frm, frozenset())
    if to_state not in allowed:
        return refuse(
            "SM-INCIDENT",
            f"{frm.value} -> {to_state.value} is not a legal transition",
            detail={"from": frm.value, "to": to_state.value,
                    "legal": sorted(s.value for s in allowed)},
        )

    guard = _INCIDENT_ENTRY_GUARDS.get(to_state)
    if guard is not None:
        return guard(state, config)
    return allow({"from": frm.value, "to": to_state.value})


def _guard_contained(state: KernelState, _c: KernelConfig) -> Decision:
    assert state.incident is not None
    if state.active_hold(state.incident.failed_freezer_id) is None:
        return refuse("SM-INCIDENT", "CONTAINED requires an active containment hold")
    return allow()


def _guard_rescue_planning(state: KernelState, _c: KernelConfig) -> Decision:
    if state.impact is None:
        return refuse(
            "SM-INCIDENT",
            "RESCUE_PLANNING requires an authoritative impact snapshot; "
            "an unknown impact set may not be planned against (D15)",
        )
    return allow()


def _guard_capacity_reserved(state: KernelState, _c: KernelConfig) -> Decision:
    assert state.incident is not None
    live = [
        r for r in state.reservations.values()
        if r.incident_id == state.incident.id
        and r.state in {ReservationState.ACTIVE, ReservationState.CONSUMED}
    ]
    if not live:
        return refuse("SM-INCIDENT", "CAPACITY_RESERVED requires at least one active reservation")
    if state.impact is not None:
        needed = {g.id for g in state.impact.placement_groups}
        covered = {r.placement_group_id for r in live}
        missing = sorted(needed - covered)
        if missing:
            return refuse(
                "SM-INCIDENT",
                f"{len(missing)} placement group(s) have no active reservation",
                detail={"missing_groups": missing},
            )
    return allow()


def _guard_dispatched(state: KernelState, _c: KernelConfig) -> Decision:
    assert state.incident is not None
    if not [d for d in state.dispatches.values() if d.incident_id == state.incident.id]:
        return refuse("SM-INCIDENT", "DISPATCHED requires at least one dispatch record")
    return allow()


def _guard_transfer_in_progress(state: KernelState, _c: KernelConfig) -> Decision:
    if not state.transfers:
        return refuse("SM-INCIDENT", "TRANSFER_IN_PROGRESS requires at least one transfer record")
    return allow()


def _guard_reconciling(state: KernelState, _c: KernelConfig) -> Decision:
    if state.impact is None:
        return refuse("SM-INCIDENT", "RECONCILING requires an impact snapshot to reconcile against")
    return allow()


def _guard_closed(state: KernelState, _c: KernelConfig) -> Decision:
    ok, reason = n6_would_hold(state)
    if not ok:
        return refuse("N6", f"incident may not close: {reason}")
    return allow({"reconciliation": reconciliation_snapshot(state).as_dict()})


def _guard_partial(state: KernelState, _c: KernelConfig) -> Decision:
    """PARTIAL is always reachable when something is genuinely unresolved.

    It is never a success state, so the guard only refuses the nonsensical case of
    declaring PARTIAL when everything actually reconciled.
    """
    snap = reconciliation_snapshot(state)
    if snap.complete:
        return refuse(
            "SM-INCIDENT",
            "PARTIAL claimed while every container is in a terminal state; "
            "use RECONCILING -> CLOSED instead",
        )
    return allow({"reconciliation": snap.as_dict()})


_INCIDENT_ENTRY_GUARDS = {
    _S.CONTAINED: _guard_contained,
    _S.RESCUE_PLANNING: _guard_rescue_planning,
    _S.CAPACITY_RESERVED: _guard_capacity_reserved,
    _S.DISPATCHED: _guard_dispatched,
    _S.TRANSFER_IN_PROGRESS: _guard_transfer_in_progress,
    _S.RECONCILING: _guard_reconciling,
    _S.CLOSED: _guard_closed,
    _S.PARTIAL: _guard_partial,
}


# --------------------------------------------------------------------------------------
# Freezer
# --------------------------------------------------------------------------------------

FREEZER_TRANSITIONS: dict[FreezerState, frozenset[FreezerState]] = {
    FreezerState.HEALTHY: frozenset({FreezerState.SUSPECT, FreezerState.FAILED}),
    FreezerState.SUSPECT: frozenset({FreezerState.HEALTHY, FreezerState.FAILED}),
    FreezerState.FAILED: frozenset({FreezerState.RECOVERING}),
    FreezerState.RECOVERING: frozenset({FreezerState.VALIDATED, FreezerState.FAILED}),
    FreezerState.VALIDATED: frozenset({FreezerState.HEALTHY, FreezerState.SUSPECT}),
}


def freezer_transition_allowed(frm: FreezerState, to: FreezerState) -> bool:
    return to in FREEZER_TRANSITIONS.get(frm, frozenset())


# --------------------------------------------------------------------------------------
# Reservation
# --------------------------------------------------------------------------------------

RESERVATION_TRANSITIONS: dict[ReservationState, frozenset[ReservationState]] = {
    ReservationState.PROPOSED: frozenset({
        ReservationState.ACTIVE, ReservationState.RELEASED, ReservationState.INVALIDATED,
    }),
    ReservationState.ACTIVE: frozenset({
        ReservationState.CONSUMED, ReservationState.RELEASED, ReservationState.INVALIDATED,
    }),
    ReservationState.CONSUMED: frozenset(),
    ReservationState.RELEASED: frozenset(),
    ReservationState.INVALIDATED: frozenset(),
}


def reservation_transition_allowed(frm: ReservationState, to: ReservationState) -> bool:
    return to in RESERVATION_TRANSITIONS.get(frm, frozenset())


# --------------------------------------------------------------------------------------
# Container custody
# --------------------------------------------------------------------------------------

CUSTODY_TRANSITIONS: dict[CustodyState, frozenset[CustodyState]] = {
    CustodyState.AT_SOURCE: frozenset({
        CustodyState.PICKED_UP, CustodyState.QUARANTINED, CustodyState.UNRESOLVED,
    }),
    CustodyState.PICKED_UP: frozenset({
        CustodyState.IN_TRANSIT, CustodyState.RECEIVED,
        CustodyState.QUARANTINED, CustodyState.UNRESOLVED,
    }),
    CustodyState.IN_TRANSIT: frozenset({
        CustodyState.RECEIVED, CustodyState.QUARANTINED, CustodyState.UNRESOLVED,
    }),
    CustodyState.RECEIVED: frozenset({
        CustodyState.COMMITTED, CustodyState.QUARANTINED, CustodyState.UNRESOLVED,
    }),
    CustodyState.COMMITTED: frozenset(),
    # An unresolved container can still be dispositioned by a human — that is how it
    # eventually reaches a terminal state without inventing a reconciliation.
    CustodyState.UNRESOLVED: frozenset({CustodyState.QUARANTINED, CustodyState.RECEIVED}),
    CustodyState.QUARANTINED: frozenset(),
}


def custody_transition_allowed(frm: CustodyState, to: CustodyState) -> bool:
    return to in CUSTODY_TRANSITIONS.get(frm, frozenset())


def custody_transition(frm: CustodyState, to: CustodyState) -> Decision:
    if custody_transition_allowed(frm, to):
        return allow({"from": frm.value, "to": to.value})
    return refuse(
        "SM-CUSTODY",
        f"custody transition {frm.value} -> {to.value} is not legal",
        detail={"from": frm.value, "to": to.value},
    )


# --------------------------------------------------------------------------------------
# Derived incident state (used by the ingestor and the Commander's requested plan)
# --------------------------------------------------------------------------------------


def next_natural_state(state: KernelState) -> IncidentState | None:
    """The state the deterministic evidence already supports, if any.

    The Commander proposes; this function is what actually decides whether the
    evidence is there. Returning ``None`` means 'stay put'.
    """
    if state.incident is None:
        return None
    current = state.incident.state
    for candidate in INCIDENT_TRANSITIONS.get(current, frozenset()):
        if candidate in {
            IncidentState.NEEDS_REASSESSMENT,
            IncidentState.ESCALATED,
            IncidentState.PARTIAL,
            IncidentState.ABORTED_SAFE,
        }:
            continue
        if can_transition_incident(state, candidate).allowed:
            return candidate
    return None


def uncertain_effects(state: KernelState) -> list[str]:
    return sorted(
        aid
        for aid, r in state.receipts.items()
        if r.status in {ActionStatus.ERROR, ActionStatus.UNAVAILABLE}
        and r.action_type
        in {
            ActionType.CAPACITY_RESERVE,
            ActionType.WORK_ORDER_CREATE,
            ActionType.DISPATCH_RESPONDER,
            ActionType.CUSTODY_COMMIT,
        }
    )
