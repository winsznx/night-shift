"""Closure requires the failed freezer to be empty of incident material.

Found by drill D8 on the live agent tier: when the reserved destination warmed, the
Custody Agent quarantined all 42 containers. Quarantine is a terminal custody state, so
reconciliation reported complete and the incident closed — with every specimen still
sitting inside the failing freezer.

N11 caught the run because the transfers carried exception reasons, but the underlying
rule was wrong: "resolved on paper" is not "rescued".
"""

from __future__ import annotations

from nightshift.common.ids import close_action_id
from nightshift.safety_kernel import ActionRequest, evaluate_action
from nightshift.safety_kernel.invariants import n6_no_premature_close, n6_would_hold
from nightshift.safety_kernel.world import reconciliation_snapshot
from nightshift.schemas.enums import ActionType, AgentName, CustodyState, IncidentState
from tests import builders as b


def _state(*, custody: CustodyState, freezer_id: str, incident_state: IncidentState):
    containers = {
        cid: b.container(cid, custody=custody, freezer_id=freezer_id) for cid in ("C-001", "C-002")
    }
    return b.base_state(
        incident=b.incident(state=incident_state),
        containers=containers,
        holds={"F-17": b.hold(active=False, evidence="VALIDATION-1")},
    )


def test_quarantining_everything_in_place_does_not_permit_closure():
    """The exact shape the live D8 run produced."""
    state = _state(
        custody=CustodyState.QUARANTINED,
        freezer_id="F-17",
        incident_state=IncidentState.RECONCILING,
    )
    # Reconciliation genuinely is complete — every container has a terminal disposition.
    assert reconciliation_snapshot(state).complete

    ok, reason = n6_would_hold(state)
    assert not ok
    assert "still located in F-17" in reason
    assert "has not been rescued" in reason


def test_quarantined_material_that_actually_moved_permits_closure():
    """Quarantine is still a legitimate terminal disposition once material is out."""
    state = _state(
        custody=CustodyState.QUARANTINED,
        freezer_id="F-03",
        incident_state=IncidentState.RECONCILING,
    )
    ok, reason = n6_would_hold(state)
    assert ok, reason


def test_committed_material_that_moved_permits_closure():
    state = _state(
        custody=CustodyState.COMMITTED,
        freezer_id="F-03",
        incident_state=IncidentState.RECONCILING,
    )
    assert n6_would_hold(state)[0]


def test_close_request_is_refused_while_material_is_stranded():
    state = _state(
        custody=CustodyState.QUARANTINED,
        freezer_id="F-17",
        incident_state=IncidentState.RECONCILING,
    )
    snap = reconciliation_snapshot(state)
    request = ActionRequest(
        action_id=close_action_id("INC-1", snap.snapshot_hash),
        action_type=ActionType.INCIDENT_CLOSE,
        incident_id="INC-1",
        actor_identity="incident-commander",
        requested_by_agent=AgentName.COMMANDER,
        requested_by_agent_revision="rev-1",
        payload={},
        now=b.T_NOW,
    )
    decision = evaluate_action(state, request)
    assert not decision.allowed
    assert decision.invariant == "N6"


def test_a_closed_incident_with_stranded_material_fails_the_snapshot_check():
    """The verifier must catch this in a published manifest, not only at commit time."""
    state = _state(
        custody=CustodyState.QUARANTINED,
        freezer_id="F-17",
        incident_state=IncidentState.CLOSED,
    )
    result = n6_no_premature_close(state)
    assert not result.holds
    assert "still located in F-17" in result.detail
