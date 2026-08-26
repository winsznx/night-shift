"""Reference model cases for N1-N13 (PRD §15.2).

Every case in the PRD's list appears here. Assertions run against the kernel's own
functions — there is no second implementation of "what should happen".
"""

from __future__ import annotations

import pytest

from nightshift.common.ids import close_action_id, reservation_action_id
from nightshift.safety_kernel import (
    ActionRequest,
    KernelState,
    check_all_invariants,
    evaluate_action,
    reconciliation_snapshot,
)
from nightshift.safety_kernel.invariants import (
    failed_invariants,
    n1_capacity_conservation,
    n2_exactly_once_effects,
    n4_fresh_destination_evidence,
    n5_complete_reconciliation,
    n6_no_premature_close,
    n7_least_privilege_effect_authority,
    n8_memory_non_authority,
    n9_duplicate_event_safety,
    n10_revision_qualification,
    n11_fail_closed_on_contradiction,
    n12_failure_attribution,
    n13_containment_integrity,
    n13_release_would_hold,
)
from nightshift.schemas.enums import (
    ActionStatus,
    ActionType,
    AgentName,
    CustodyState,
    FailureClass,
    IncidentState,
    ReservationState,
)
from tests import builders as b

NOW = b.T_NOW


# --------------------------------------------------------------------------------------
# N1 — capacity conservation
# --------------------------------------------------------------------------------------


def _reserve(slots: int, *, dest: str = "F-03", group: str = "PG-1", incident: str = "INC-1"):
    return ActionRequest(
        action_id=reservation_action_id(incident, dest, group),
        action_type=ActionType.CAPACITY_RESERVE,
        incident_id=incident,
        actor_identity="capacity-broker",
        requested_by_agent=AgentName.CAPACITY_BROKER,
        requested_by_agent_revision="rev-1",
        payload={"destination_freezer_id": dest, "placement_group_id": group, "slots": slots},
        now=NOW,
    )


def test_n1_zero_capacity_refuses():
    state = b.base_state(
        freezers={
            "F-17": b.freezer("F-17"),
            "F-03": b.freezer("F-03", total=50, occupied=50, backup=True),
        }
    )
    d = evaluate_action(state, _reserve(1))
    assert not d.allowed and d.invariant == "N1"


def test_n1_exact_capacity_boundary_is_allowed():
    state = b.base_state(
        freezers={
            "F-17": b.freezer("F-17"),
            "F-03": b.freezer("F-03", total=50, occupied=48, backup=True),
        }
    )
    assert evaluate_action(state, _reserve(2)).allowed


def test_n1_one_over_boundary_refuses():
    state = b.base_state(
        freezers={
            "F-17": b.freezer("F-17"),
            "F-03": b.freezer("F-03", total=50, occupied=48, backup=True),
        }
    )
    d = evaluate_action(state, _reserve(3))
    assert not d.allowed and d.invariant == "N1"


def test_n1_concurrent_reservations_exceeding_capacity_refuse_the_second():
    """D4: two incidents competing for the same backup freezer."""
    existing = b.reservation(incident_id="INC-OTHER", destination="F-03", group_id="PG-X", slots=8)
    state = b.base_state(
        freezers={
            "F-17": b.freezer("F-17"),
            "F-03": b.freezer("F-03", total=60, occupied=50, backup=True),
        },
        reservations={existing.id: existing},
    )
    assert state.verified_available_slots("F-03") == 10
    assert state.reserved_slots("F-03") == 8
    assert evaluate_action(state, _reserve(2)).allowed
    d = evaluate_action(state, _reserve(3))
    assert not d.allowed and d.invariant == "N1"


def test_n1_released_reservations_free_their_slots():
    released = b.reservation(
        destination="F-03", group_id="PG-X", slots=10, state=ReservationState.RELEASED
    )
    state = b.base_state(
        freezers={
            "F-17": b.freezer("F-17"),
            "F-03": b.freezer("F-03", total=60, occupied=50, backup=True),
        },
        reservations={released.id: released},
    )
    assert state.reserved_slots("F-03") == 0
    assert evaluate_action(state, _reserve(10)).allowed


def test_n1_snapshot_check_detects_overbooking():
    over = b.reservation(destination="F-03", slots=99)
    state = b.base_state(
        freezers={"F-03": b.freezer("F-03", total=10, occupied=5, backup=True)},
        reservations={over.id: over},
    )
    assert not n1_capacity_conservation(state).holds


# --------------------------------------------------------------------------------------
# N2 — exactly once
# --------------------------------------------------------------------------------------


def test_n2_duplicate_semantic_reservation_derives_the_same_key():
    """Two callers with different request IDs land on one action_id."""
    a = _reserve(2)
    c = _reserve(2)
    assert a.action_id == c.action_id


def test_n2_mismatched_action_id_is_refused():
    """A retry that invents a fresh key would create a second effect — refuse it."""
    state = b.base_state()
    bad = ActionRequest(
        action_id="f" * 64,
        action_type=ActionType.CAPACITY_RESERVE,
        incident_id="INC-1",
        actor_identity="capacity-broker",
        requested_by_agent=AgentName.CAPACITY_BROKER,
        requested_by_agent_revision="rev-1",
        payload={"destination_freezer_id": "F-03", "placement_group_id": "PG-1", "slots": 2},
        now=NOW,
    )
    d = evaluate_action(state, bad)
    assert not d.allowed and d.invariant == "N2"


def test_n2_duplicate_effect_records_are_detected():
    r1 = b.reservation()
    r2 = r1.model_copy(update={"id": "RES-DUPE"})
    state = b.base_state(
        reservations={r1.id: r1, r2.id: r2},
        receipts={
            r1.action_id: b.receipt(r1.action_id, ActionType.CAPACITY_RESERVE, effect_ref=r1.id)
        },
    )
    res = n2_exactly_once_effects(state)
    assert not res.holds and res.evidence["duplicate_effects"]


def test_n2_effect_committed_but_response_lost_returns_one_effect():
    """D5: the effect exists; a retry must find it rather than make another."""
    r = b.reservation()
    state = b.base_state(
        reservations={r.id: r},
        receipts={
            r.action_id: b.receipt(r.action_id, ActionType.CAPACITY_RESERVE, effect_ref=r.id)
        },
    )
    assert state.committed_receipt_for(r.action_id) is not None
    assert n2_exactly_once_effects(state).holds


def test_n2_receipt_without_effect_is_a_mismatch():
    """Agent reports success but the effect store contains no effect."""
    aid = reservation_action_id("INC-1", "F-03", "PG-1")
    state = b.base_state(
        receipts={aid: b.receipt(aid, ActionType.CAPACITY_RESERVE, effect_ref="RES-GHOST")}
    )
    res = n2_exactly_once_effects(state)
    assert not res.holds and res.evidence["receipts_without_effect"] == [aid]


def test_n2_effect_without_receipt_is_a_mismatch():
    r = b.reservation()
    state = b.base_state(reservations={r.id: r}, receipts={})
    res = n2_exactly_once_effects(state)
    assert not res.holds and res.evidence["effects_without_receipt"] == [r.action_id]


def test_n2_duplicate_committed_transfer_is_detected():
    t1 = b.transfer("C-001", state=CustodyState.COMMITTED, with_pickup=True, with_destination=True)
    t2 = t1.model_copy(update={"transfer_id": "TR-DUPE"})
    state = b.base_state(transfers={t1.transfer_id: t1, t2.transfer_id: t2})
    assert not n2_exactly_once_effects(state).holds


# --------------------------------------------------------------------------------------
# N3 / N4 — custody prerequisites and destination freshness
# --------------------------------------------------------------------------------------


def _commit(
    container_id="C-001",
    *,
    dest="F-03",
    reservation_id=None,
    temp=-79.0,
    temp_at=NOW,
    authorized=True,
):
    from nightshift.common.ids import transfer_action_id

    return ActionRequest(
        action_id=transfer_action_id("INC-1", container_id, f"{dest}-SLOT-001"),
        action_type=ActionType.CUSTODY_COMMIT,
        incident_id="INC-1",
        actor_identity="custody-agent",
        requested_by_agent=AgentName.CUSTODY_AGENT,
        requested_by_agent_revision="rev-1",
        payload={
            "container_id": container_id,
            "destination_freezer_id": dest,
            "reservation_id": reservation_id,
            "responder_authorized": authorized,
            "destination_temp_c": temp,
            "destination_temp_recorded_at": temp_at,
        },
        now=NOW,
    )


def _ready_state(**over):
    res = b.reservation()
    t = b.transfer(
        "C-001",
        reservation_id=res.id,
        state=CustodyState.RECEIVED,
        with_pickup=True,
        with_destination=True,
    )
    kw = {
        "reservations": {res.id: res},
        "transfers": {t.transfer_id: t},
        "containers": {
            "C-001": b.container("C-001", custody=CustodyState.RECEIVED),
            "C-002": b.container("C-002"),
        },
    }
    kw.update(over)
    return b.base_state(**kw), res


def test_n3_happy_path_commit_allowed():
    state, res = _ready_state()
    assert evaluate_action(state, _commit(reservation_id=res.id)).allowed


def test_n3_commit_without_reservation_refused():
    state, _ = _ready_state()
    d = evaluate_action(state, _commit(reservation_id=None))
    assert not d.allowed and d.invariant == "N3"


def test_n3_commit_for_foreign_container_refused():
    state, res = _ready_state()
    d = evaluate_action(state, _commit("C-999", reservation_id=res.id))
    assert not d.allowed and d.invariant == "N3"


def test_n3_commit_without_responder_credential_refused():
    state, res = _ready_state()
    d = evaluate_action(state, _commit(reservation_id=res.id, authorized=False))
    assert not d.allowed and d.invariant == "N3"


def test_n3_commit_without_pickup_evidence_refused():
    res = b.reservation()
    t = b.transfer(
        "C-001",
        reservation_id=res.id,
        state=CustodyState.RECEIVED,
        with_pickup=False,
        with_destination=True,
    )
    state = b.base_state(
        reservations={res.id: res},
        transfers={t.transfer_id: t},
        containers={
            "C-001": b.container("C-001", custody=CustodyState.RECEIVED),
            "C-002": b.container("C-002"),
        },
    )
    d = evaluate_action(state, _commit(reservation_id=res.id))
    assert not d.allowed and d.invariant == "N3"
    assert "source scan evidence missing" in d.reason


def test_n3_invalidated_reservation_cannot_back_a_commit():
    res = b.reservation(state=ReservationState.INVALIDATED)
    t = b.transfer(
        "C-001",
        reservation_id=res.id,
        state=CustodyState.RECEIVED,
        with_pickup=True,
        with_destination=True,
    )
    state = b.base_state(
        reservations={res.id: res},
        transfers={t.transfer_id: t},
        containers={
            "C-001": b.container("C-001", custody=CustodyState.RECEIVED),
            "C-002": b.container("C-002"),
        },
    )
    d = evaluate_action(state, _commit(reservation_id=res.id))
    assert not d.allowed and d.invariant == "N3"


def test_n4_stale_destination_temperature_refuses():
    state, res = _ready_state()
    stale = "2026-08-26T01:00:00.000Z"  # 70 minutes before NOW
    d = evaluate_action(state, _commit(reservation_id=res.id, temp_at=stale))
    assert not d.allowed and d.invariant == "N4"
    assert "old" in d.reason


def test_n4_warm_destination_refuses():
    """D8: destination warms after reservation but before receipt."""
    state, res = _ready_state()
    d = evaluate_action(state, _commit(reservation_id=res.id, temp=-45.0))
    assert not d.allowed and d.invariant == "N4"
    assert "ceiling" in d.reason


def test_n4_implausibly_cold_reading_refuses():
    state, res = _ready_state()
    d = evaluate_action(state, _commit(reservation_id=res.id, temp=-140.0))
    assert not d.allowed and d.invariant == "N4"


def test_n4_missing_evidence_refuses():
    state, res = _ready_state()
    d = evaluate_action(state, _commit(reservation_id=res.id, temp=None, temp_at=None))
    assert not d.allowed and d.invariant == "N4"


def test_n4_boundary_age_exactly_at_limit_is_allowed():
    from nightshift.common.clock import shift_iso
    from nightshift.safety_kernel.config import DEFAULT_CONFIG

    state, res = _ready_state()
    at = shift_iso(NOW, -DEFAULT_CONFIG.destination_temp_max_age_s)
    assert evaluate_action(state, _commit(reservation_id=res.id, temp_at=at)).allowed


def test_n4_snapshot_check_flags_a_committed_transfer_with_stale_evidence():
    t = b.transfer(
        "C-001",
        state=CustodyState.COMMITTED,
        with_pickup=True,
        with_destination=True,
        dest_temp_at="2026-08-26T00:00:00.000Z",
    )
    state = b.base_state(transfers={t.transfer_id: t})
    assert not n4_fresh_destination_evidence(state, NOW).holds


def test_contradictory_scan_forces_unresolved():
    """D14: container scanned at an unexpected destination."""
    res = b.reservation()
    t = b.transfer(
        "C-001",
        reservation_id=res.id,
        destination="F-03",
        state=CustodyState.PICKED_UP,
        with_pickup=True,
    )
    state = b.base_state(
        reservations={res.id: res},
        transfers={t.transfer_id: t},
        containers={
            "C-001": b.container("C-001", custody=CustodyState.PICKED_UP),
            "C-002": b.container("C-002"),
        },
    )
    req = ActionRequest(
        action_id="a" * 64,
        action_type=ActionType.CUSTODY_DESTINATION_SCAN,
        incident_id="INC-1",
        actor_identity="custody-agent",
        requested_by_agent=AgentName.CUSTODY_AGENT,
        requested_by_agent_revision="rev-1",
        payload={
            "container_id": "C-001",
            "destination_freezer_id": "F-09",
            "responder_authorized": True,
        },
        now=NOW,
    )
    d = evaluate_action(state, req)
    assert not d.allowed and d.invariant == "N11"
    assert d.detail["required_disposition"] == "UNRESOLVED"


def test_duplicate_scan_is_rejected_by_the_custody_state_machine():
    """D12: the second identical scan cannot re-drive the same transition."""
    res = b.reservation()
    t = b.transfer(
        "C-001",
        reservation_id=res.id,
        state=CustodyState.RECEIVED,
        with_pickup=True,
        with_destination=True,
    )
    state = b.base_state(
        reservations={res.id: res},
        transfers={t.transfer_id: t},
        containers={
            "C-001": b.container("C-001", custody=CustodyState.RECEIVED),
            "C-002": b.container("C-002"),
        },
    )
    req = ActionRequest(
        action_id="a" * 64,
        action_type=ActionType.CUSTODY_PICKUP,
        incident_id="INC-1",
        actor_identity="custody-agent",
        requested_by_agent=AgentName.CUSTODY_AGENT,
        requested_by_agent_revision="rev-1",
        payload={"container_id": "C-001", "responder_authorized": True},
        now=NOW,
    )
    d = evaluate_action(state, req)
    assert not d.allowed and d.invariant == "SM-CUSTODY"


# --------------------------------------------------------------------------------------
# N5 / N6 — reconciliation and closure
# --------------------------------------------------------------------------------------


def _close_request(state: KernelState):
    snap = reconciliation_snapshot(state)
    return ActionRequest(
        action_id=close_action_id("INC-1", snap.snapshot_hash),
        action_type=ActionType.INCIDENT_CLOSE,
        incident_id="INC-1",
        actor_identity="incident-commander",
        requested_by_agent=AgentName.COMMANDER,
        requested_by_agent_revision="rev-1",
        payload={},
        now=NOW,
    )


def test_n6_close_with_one_unresolved_container_refused():
    """D13: partial transfer — some containers move, one does not."""
    containers = {
        "C-001": b.container("C-001", custody=CustodyState.COMMITTED),
        "C-002": b.container("C-002", custody=CustodyState.UNRESOLVED),
    }
    state = b.base_state(
        incident=b.incident(state=IncidentState.RECONCILING),
        containers=containers,
        holds={"F-17": b.hold(active=False, evidence="VAL-1")},
    )
    d = evaluate_action(state, _close_request(state))
    assert not d.allowed and d.invariant == "N6"
    assert "unresolved" in d.reason


def test_n6_close_with_in_flight_transfer_refused():
    containers = {
        "C-001": b.container("C-001", custody=CustodyState.COMMITTED),
        "C-002": b.container("C-002", custody=CustodyState.IN_TRANSIT),
    }
    state = b.base_state(
        incident=b.incident(state=IncidentState.RECONCILING),
        containers=containers,
        holds={"F-17": b.hold(active=False, evidence="VAL-1")},
    )
    d = evaluate_action(state, _close_request(state))
    assert not d.allowed and "in flight" in d.reason


def test_n6_close_with_active_containment_hold_refused():
    containers = {c: b.container(c, custody=CustodyState.COMMITTED) for c in ("C-001", "C-002")}
    state = b.base_state(
        incident=b.incident(state=IncidentState.RECONCILING),
        containers=containers,
        holds={"F-17": b.hold(active=True)},
    )
    d = evaluate_action(state, _close_request(state))
    assert not d.allowed and "containment hold" in d.reason


def test_n6_close_with_uncertain_effect_refused():
    containers = {c: b.container(c, custody=CustodyState.COMMITTED) for c in ("C-001", "C-002")}
    aid = reservation_action_id("INC-1", "F-03", "PG-1")
    state = b.base_state(
        incident=b.incident(state=IncidentState.RECONCILING),
        containers=containers,
        holds={"F-17": b.hold(active=False, evidence="VAL-1")},
        receipts={aid: b.receipt(aid, ActionType.CAPACITY_RESERVE, status=ActionStatus.ERROR)},
    )
    d = evaluate_action(state, _close_request(state))
    assert not d.allowed and "uncertain" in d.reason


def test_n6_close_without_impact_snapshot_refused():
    containers = {c: b.container(c, custody=CustodyState.COMMITTED) for c in ("C-001", "C-002")}
    state = b.base_state(
        incident=b.incident(state=IncidentState.RECONCILING),
        containers=containers,
        impact=None,
        holds={"F-17": b.hold(active=False, evidence="VAL-1")},
    )
    d = evaluate_action(state, _close_request(state))
    assert not d.allowed


def test_n6_full_reconciliation_permits_closure():
    # Committed containers have physically moved to the destination. Leaving them in
    # F-17 would be resolved-on-paper only, which closure now refuses.
    containers = {
        c: b.container(c, custody=CustodyState.COMMITTED, freezer_id="F-03")
        for c in ("C-001", "C-002")
    }
    state = b.base_state(
        incident=b.incident(state=IncidentState.RECONCILING),
        containers=containers,
        holds={"F-17": b.hold(active=False, evidence="VAL-1")},
    )
    assert evaluate_action(state, _close_request(state)).allowed


def test_n6_stale_close_action_id_refused():
    """A close computed against an older reconciliation cannot replay."""
    containers = {c: b.container(c, custody=CustodyState.COMMITTED) for c in ("C-001", "C-002")}
    state = b.base_state(
        incident=b.incident(state=IncidentState.RECONCILING),
        containers=containers,
        holds={"F-17": b.hold(active=False, evidence="VAL-1")},
    )
    stale = ActionRequest(
        action_id=close_action_id("INC-1", "0" * 64),
        action_type=ActionType.INCIDENT_CLOSE,
        incident_id="INC-1",
        actor_identity="incident-commander",
        requested_by_agent=AgentName.COMMANDER,
        requested_by_agent_revision="rev-1",
        payload={},
        now=NOW,
    )
    d = evaluate_action(state, stale)
    assert not d.allowed and "reconciliation snapshot" in d.reason


def test_n5_quarantined_counts_as_resolved():
    containers = {
        "C-001": b.container("C-001", custody=CustodyState.COMMITTED),
        "C-002": b.container("C-002", custody=CustodyState.QUARANTINED),
    }
    state = b.base_state(containers=containers)
    assert reconciliation_snapshot(state).complete


def test_n5_flags_closed_incident_with_open_containers():
    containers = {
        "C-001": b.container("C-001", custody=CustodyState.IN_TRANSIT),
        "C-002": b.container("C-002", custody=CustodyState.COMMITTED),
    }
    state = b.base_state(incident=b.incident(state=IncidentState.CLOSED), containers=containers)
    assert not n5_complete_reconciliation(state).holds
    assert not n6_no_premature_close(state).holds


def test_n5_holds_on_a_legitimately_closed_incident():
    state = b.closed_state_all_committed()
    assert n5_complete_reconciliation(state).holds
    assert n6_no_premature_close(state).holds


# --------------------------------------------------------------------------------------
# N7 / N8 / N10 — authority, memory, qualification
# --------------------------------------------------------------------------------------


def test_n7_wrong_identity_cannot_reserve_capacity():
    state = b.base_state()
    req = _reserve(2)
    bad = ActionRequest(
        action_id=req.action_id,
        action_type=req.action_type,
        incident_id=req.incident_id,
        actor_identity="dispatch-agent",
        requested_by_agent=AgentName.DISPATCH_AGENT,
        requested_by_agent_revision="rev-1",
        payload=req.payload,
        now=NOW,
    )
    d = evaluate_action(state, bad)
    assert not d.allowed and d.invariant == "N7"


def test_n7_commander_cannot_commit_custody():
    state, res = _ready_state()
    req = _commit(reservation_id=res.id)
    bad = ActionRequest(
        action_id=req.action_id,
        action_type=req.action_type,
        incident_id=req.incident_id,
        actor_identity="incident-commander",
        requested_by_agent=AgentName.COMMANDER,
        requested_by_agent_revision="rev-1",
        payload=req.payload,
        now=NOW,
    )
    d = evaluate_action(state, bad)
    assert not d.allowed and d.invariant == "N7"


def test_n7_snapshot_check_flags_wrong_actor():
    r = b.reservation()
    state = b.base_state(
        reservations={r.id: r},
        receipts={
            r.action_id: b.receipt(
                r.action_id, ActionType.CAPACITY_RESERVE, actor="dispatch-agent", effect_ref=r.id
            )
        },
    )
    assert not n7_least_privilege_effect_authority(state).holds


def test_n8_memory_only_evidence_is_refused():
    """D9: stale Memory Bank says F-03 has capacity; authoritative state says otherwise."""
    state = b.base_state()
    req = _reserve(2)
    memory_only = ActionRequest(
        action_id=req.action_id,
        action_type=req.action_type,
        incident_id=req.incident_id,
        actor_identity="capacity-broker",
        requested_by_agent=AgentName.CAPACITY_BROKER,
        requested_by_agent_revision="rev-1",
        payload={**req.payload, "evidence_sources": ["memory:F-03 usually has room"]},
        now=NOW,
    )
    d = evaluate_action(state, memory_only)
    assert not d.allowed and d.invariant == "N8"


def test_n8_memory_plus_authoritative_source_is_fine():
    state = b.base_state()
    req = _reserve(2)
    mixed = ActionRequest(
        action_id=req.action_id,
        action_type=req.action_type,
        incident_id=req.incident_id,
        actor_identity="capacity-broker",
        requested_by_agent=AgentName.CAPACITY_BROKER,
        requested_by_agent_revision="rev-1",
        payload={
            **req.payload,
            "evidence_sources": ["memory:F-03 usually has room", "capacity:get_capacity"],
        },
        now=NOW,
    )
    assert evaluate_action(state, mixed).allowed


def test_n8_snapshot_check_flags_memory_only_receipt():
    r = b.reservation()
    state = b.base_state(
        reservations={r.id: r},
        receipts={
            r.action_id: b.receipt(
                r.action_id,
                ActionType.CAPACITY_RESERVE,
                effect_ref=r.id,
                evidence_sources=["memory:remembered capacity"],
            )
        },
    )
    assert not n8_memory_non_authority(state).holds


def test_n10_blocked_revision_cannot_act():
    """D16: a blocked revision attempts an action."""
    state = b.base_state(
        revision_states={**b.qualified_revisions(), "capacity-broker@rev-1": "BLOCKED"}
    )
    d = evaluate_action(state, _reserve(2))
    assert not d.allowed and d.invariant == "N10"


def test_n10_unknown_revision_is_treated_as_unqualified():
    state = b.base_state(revision_states={})
    d = evaluate_action(state, _reserve(2))
    assert not d.allowed and d.invariant == "N10"
    assert "missing is not qualified" in d.reason


def test_n10_deprecated_revision_cannot_act():
    state = b.base_state(
        revision_states={**b.qualified_revisions(), "capacity-broker@rev-1": "DEPRECATED"}
    )
    assert not evaluate_action(state, _reserve(2)).allowed


def test_n10_snapshot_check_flags_unqualified_effect():
    r = b.reservation()
    state = b.base_state(
        reservations={r.id: r},
        revision_states={},
        receipts={
            r.action_id: b.receipt(r.action_id, ActionType.CAPACITY_RESERVE, effect_ref=r.id)
        },
    )
    assert not n10_revision_qualification(state).holds


# --------------------------------------------------------------------------------------
# N9 / N11 / N12 / N13
# --------------------------------------------------------------------------------------


def test_n9_duplicate_delivery_without_duplicate_effect_holds():
    r = b.reservation()
    state = b.base_state(
        reservations={r.id: r},
        receipts={
            r.action_id: b.receipt(r.action_id, ActionType.CAPACITY_RESERVE, effect_ref=r.id)
        },
    )
    res = n9_duplicate_event_safety(state, ["evt-1", "evt-1", "evt-2"])
    assert res.holds and res.evidence["duplicate_deliveries"] == 1


def test_n9_duplicate_delivery_with_duplicate_effect_fails():
    r1 = b.reservation()
    r2 = r1.model_copy(update={"id": "RES-DUPE"})
    state = b.base_state(
        reservations={r1.id: r1, r2.id: r2},
        receipts={
            r1.action_id: b.receipt(r1.action_id, ActionType.CAPACITY_RESERVE, effect_ref=r1.id)
        },
    )
    assert not n9_duplicate_event_safety(state, ["evt-1", "evt-1"]).holds


def test_n11_unavailable_adapter_cannot_reach_closed():
    """D15: inventory adapter unavailable — no hallucinated impact set."""
    state = KernelState(
        incident=b.incident(state=IncidentState.CLOSED),
        unavailable_sources=frozenset({"inventory"}),
    )
    assert not n11_fail_closed_on_contradiction(state).holds


def test_n11_unavailable_adapter_while_open_is_acceptable():
    state = KernelState(
        incident=b.incident(state=IncidentState.NEEDS_REASSESSMENT),
        unavailable_sources=frozenset({"inventory"}),
    )
    assert n11_fail_closed_on_contradiction(state).holds


def test_n11_impact_snapshot_refused_when_inventory_incomplete():
    state = b.base_state(impact=None)
    req = ActionRequest(
        action_id="c" * 64,
        action_type=ActionType.IMPACT_SNAPSHOT,
        incident_id="INC-1",
        actor_identity="incident-ingestor",
        payload={"inventory_complete": False, "container_ids": ["C-001"]},
        now=NOW,
    )
    d = evaluate_action(state, req)
    assert not d.allowed and d.invariant == "N11"


def test_n12_unattributed_failure_is_flagged():
    aid = reservation_action_id("INC-1", "F-03", "PG-1")
    r = b.receipt(aid, ActionType.CAPACITY_RESERVE, status=ActionStatus.ERROR)
    r = r.model_copy(update={"failure_class": FailureClass.NONE})
    state = b.base_state(receipts={aid: r})
    assert not n12_failure_attribution(state).holds


def test_n12_infrastructure_failure_is_attributed_not_blamed_on_the_agent():
    """D17: a tool proxy failure is an infrastructure error, not an agent safety failure."""
    aid = reservation_action_id("INC-1", "F-03", "PG-1")
    r = b.receipt(aid, ActionType.CAPACITY_RESERVE, status=ActionStatus.UNAVAILABLE)
    r = r.model_copy(update={"failure_class": FailureClass.INFRASTRUCTURE})
    state = b.base_state(receipts={aid: r})
    res = n12_failure_attribution(state)
    assert res.holds
    assert state.receipts[aid].failure_class is FailureClass.INFRASTRUCTURE


def test_n13_hold_blocks_normal_inventory_operation():
    from nightshift.safety_kernel.preconditions import check_normal_inventory_operation

    state = b.base_state(holds={"F-17": b.hold()})
    assert not check_normal_inventory_operation(state, "F-17").allowed
    assert check_normal_inventory_operation(state, "F-03").allowed


def test_n13_hold_blocks_reserving_into_a_held_freezer():
    state = b.base_state(holds={"F-03": b.hold(freezer_id="F-03")})
    d = evaluate_action(state, _reserve(2))
    assert not d.allowed and d.invariant == "N13"


def test_n13_release_requires_a_sustained_validation_window():
    """D18: a recovered freezer that has not yet proven itself keeps its hold."""
    state = b.base_state()
    short = [("2026-08-26T02:00:00.000Z", -80.0), ("2026-08-26T02:05:00.000Z", -80.0)]
    ok, reason = n13_release_would_hold(state, "F-17", short, NOW)
    assert not ok and "validation window" in reason


def test_n13_release_refuses_a_warm_validation_reading():
    state = b.base_state()
    readings = [("2026-08-26T01:00:00.000Z", -80.0), ("2026-08-26T02:00:00.000Z", -55.0)]
    ok, reason = n13_release_would_hold(state, "F-17", readings, NOW)
    assert not ok and "above" in reason


def test_n13_release_allowed_after_a_clean_window():
    state = b.base_state()
    readings = [("2026-08-26T01:30:00.000Z", -80.0), ("2026-08-26T02:05:00.000Z", -80.1)]
    ok, reason = n13_release_would_hold(state, "F-17", readings, NOW)
    assert ok, reason


def test_n13_released_hold_without_evidence_is_flagged():
    state = b.base_state(holds={"F-17": b.hold(active=False, evidence=None)})
    assert not n13_containment_integrity(state).holds


# --------------------------------------------------------------------------------------
# Aggregate
# --------------------------------------------------------------------------------------


def test_all_invariants_hold_on_a_clean_closed_incident():
    state = b.closed_state_all_committed()
    results = check_all_invariants(state, NOW, delivered_event_ids=["e1", "e1"])
    assert failed_invariants(results) == [], [r.as_dict() for r in results if not r.holds]


def test_check_all_invariants_returns_every_invariant_in_stable_order():
    results = check_all_invariants(b.base_state(), NOW)
    assert [r.invariant for r in results] == [f"N{i}" for i in range(1, 14)]


@pytest.mark.parametrize("n", [f"N{i}" for i in range(1, 14)])
def test_every_invariant_has_a_title(n):
    results = check_all_invariants(b.base_state(), NOW)
    match = next(r for r in results if r.invariant == n)
    assert match.title and match.detail
