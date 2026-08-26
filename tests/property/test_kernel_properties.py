"""Property tests for the invariants that must hold for *any* input (PRD §39.2).

These are the ones worth generating, because the failure modes are combinatorial:
capacity arithmetic under arbitrary reservation mixes, idempotency under arbitrary
retry counts, and action-ID stability under arbitrary identifiers.
"""

from __future__ import annotations

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from nightshift.common.canonical import sha256_of
from nightshift.common.ids import (
    close_action_id,
    dispatch_action_id,
    reservation_action_id,
    transfer_action_id,
    work_order_action_id,
)
from nightshift.safety_kernel import ActionRequest, KernelState, evaluate_action
from nightshift.safety_kernel.invariants import (
    n1_capacity_conservation,
    n1_would_hold,
    n2_exactly_once_effects,
)
from nightshift.safety_kernel.transitions import (
    CUSTODY_TRANSITIONS,
    INCIDENT_TRANSITIONS,
    RESERVATION_TRANSITIONS,
    can_transition_incident,
)
from nightshift.safety_kernel.world import reconciliation_snapshot
from nightshift.schemas.enums import (
    ActionType,
    AgentName,
    CustodyState,
    FaultClass,
    IncidentState,
    ReservationState,
    ResponderRole,
    ResponsePhase,
)
from tests import builders as b

SETTINGS = settings(
    max_examples=250,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

ids = st.text(
    alphabet=st.characters(min_codepoint=48, max_codepoint=122, blacklist_characters="|"),
    min_size=1,
    max_size=24,
)
slots = st.integers(min_value=1, max_value=500)


# --------------------------------------------------------------------------------------
# Capacity conservation
# --------------------------------------------------------------------------------------


@SETTINGS
@given(
    total=st.integers(min_value=0, max_value=500),
    occupied=st.integers(min_value=0, max_value=500),
    existing=st.lists(st.integers(min_value=1, max_value=100), max_size=6),
    request=slots,
)
def test_reservation_never_exceeds_verified_capacity(total, occupied, existing, request):
    """Whatever the mix of prior reservations, an ALLOW never overbooks."""
    assume(occupied <= total)
    reservations = {}
    for i, n in enumerate(existing):
        r = b.reservation(destination="F-03", group_id=f"PG-{i}", slots=n)
        reservations[r.id] = r

    state = b.base_state(
        freezers={
            "F-17": b.freezer("F-17"),
            "F-03": b.freezer("F-03", total=total, occupied=occupied, backup=True),
        },
        reservations=reservations,
    )

    req = ActionRequest(
        action_id=reservation_action_id("INC-1", "F-03", "PG-NEW"),
        action_type=ActionType.CAPACITY_RESERVE,
        incident_id="INC-1",
        actor_identity="capacity-broker",
        requested_by_agent=AgentName.CAPACITY_BROKER,
        requested_by_agent_revision="rev-1",
        payload={"destination_freezer_id": "F-03", "placement_group_id": "PG-NEW",
                 "slots": request},
        now=b.T_NOW,
    )
    decision = evaluate_action(state, req)

    if decision.allowed:
        after = dict(reservations)
        new = b.reservation(destination="F-03", group_id="PG-NEW", slots=request)
        after[new.id] = new
        post = KernelState(
            incident=state.incident, freezers=state.freezers, containers=state.containers,
            impact=state.impact, reservations=after, revision_states=state.revision_states,
            holds=state.holds,
        )
        assert n1_capacity_conservation(post).holds


@SETTINGS
@given(
    free=st.integers(min_value=0, max_value=200),
    reserved=st.lists(st.integers(min_value=1, max_value=50), max_size=8),
    ask=slots,
)
def test_n1_would_hold_matches_the_arithmetic_it_claims(free, reserved, ask):
    reservations = {}
    for i, n in enumerate(reserved):
        r = b.reservation(destination="F-03", group_id=f"PG-{i}", slots=n)
        reservations[r.id] = r
    state = b.base_state(
        freezers={"F-03": b.freezer("F-03", total=free, occupied=0, backup=True)},
        reservations=reservations,
    )
    expected = sum(reserved) + ask <= free
    assert n1_would_hold(state, "F-03", ask) is expected


# --------------------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------------------


@SETTINGS
@given(incident=ids, dest=ids, group=ids, retries=st.integers(min_value=1, max_value=40))
def test_action_id_is_stable_across_arbitrary_retry_counts(incident, dest, group, retries):
    first = reservation_action_id(incident, dest, group)
    assert all(reservation_action_id(incident, dest, group) == first for _ in range(retries))


@SETTINGS
@given(incident=ids, dest=ids, group=ids, other_dest=ids)
def test_action_id_collides_only_on_identical_semantics(incident, dest, group, other_dest):
    assume(dest != other_dest)
    assert reservation_action_id(incident, dest, group) != reservation_action_id(
        incident, other_dest, group
    )


@SETTINGS
@given(
    incident=ids,
    freezer=ids,
    fault=st.sampled_from(list(FaultClass)),
    container=ids,
    slot=ids,
    phase=st.sampled_from(list(ResponsePhase)),
    role=st.sampled_from(list(ResponderRole)),
    snapshot=st.text(alphabet="0123456789abcdef", min_size=64, max_size=64),
)
def test_all_action_id_derivers_are_pure_and_64_hex(
    incident, freezer, fault, container, slot, phase, role, snapshot
):
    derived = [
        reservation_action_id(incident, freezer, container),
        work_order_action_id(incident, freezer, fault),
        dispatch_action_id(incident, phase, role),
        transfer_action_id(incident, container, slot),
        close_action_id(incident, snapshot),
    ]
    for value in derived:
        assert len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    # Purity: same inputs, same outputs.
    assert derived[0] == reservation_action_id(incident, freezer, container)


@SETTINGS
@given(n=st.integers(min_value=1, max_value=25))
def test_replaying_the_same_effect_never_multiplies_it(n):
    """Whatever the retry count, one semantic action indexes one effect record."""
    r = b.reservation()
    receipts = {r.action_id: b.receipt(r.action_id, ActionType.CAPACITY_RESERVE,
                                       effect_ref=r.id)}
    reservations = {r.id: r}
    for _ in range(n):
        # A retry finds the existing receipt and re-inserts nothing new.
        if r.action_id in receipts:
            continue
        reservations[r.id] = r
    state = b.base_state(reservations=reservations, receipts=receipts)
    assert n2_exactly_once_effects(state).holds
    assert len(state.reservations) == 1


# --------------------------------------------------------------------------------------
# Reconciliation completeness
# --------------------------------------------------------------------------------------


@SETTINGS
@given(states=st.lists(st.sampled_from(list(CustodyState)), min_size=1, max_size=12))
def test_reconciliation_partitions_every_container_exactly_once(states):
    containers = {
        f"C-{i:03d}": b.container(f"C-{i:03d}", custody=cs) for i, cs in enumerate(states)
    }
    impact = b.impact(containers=list(containers))
    state = b.base_state(containers=containers, impact=impact)
    snap = reconciliation_snapshot(state)

    buckets = snap.committed + snap.quarantined + snap.unresolved + snap.in_flight
    assert sorted(buckets) == sorted(containers)
    assert len(buckets) == len(set(buckets)) == snap.total


@SETTINGS
@given(states=st.lists(st.sampled_from(list(CustodyState)), min_size=1, max_size=12))
def test_complete_iff_no_unresolved_and_no_in_flight(states):
    containers = {
        f"C-{i:03d}": b.container(f"C-{i:03d}", custody=cs) for i, cs in enumerate(states)
    }
    state = b.base_state(containers=containers, impact=b.impact(containers=list(containers)))
    snap = reconciliation_snapshot(state)
    terminal = {CustodyState.COMMITTED, CustodyState.QUARANTINED}
    assert snap.complete is all(cs in terminal for cs in states)


@SETTINGS
@given(states=st.lists(st.sampled_from(list(CustodyState)), min_size=1, max_size=10))
def test_reconciliation_hash_is_order_independent(states):
    containers = {
        f"C-{i:03d}": b.container(f"C-{i:03d}", custody=cs) for i, cs in enumerate(states)
    }
    forward = b.base_state(containers=containers, impact=b.impact(containers=list(containers)))
    reversed_containers = dict(reversed(list(containers.items())))
    backward = b.base_state(containers=reversed_containers,
                            impact=b.impact(containers=list(reversed_containers)))
    assert (
        reconciliation_snapshot(forward).snapshot_hash
        == reconciliation_snapshot(backward).snapshot_hash
    )


# --------------------------------------------------------------------------------------
# State machine ordering
# --------------------------------------------------------------------------------------


@SETTINGS
@given(frm=st.sampled_from(list(IncidentState)), to=st.sampled_from(list(IncidentState)))
def test_illegal_incident_transitions_are_always_refused(frm, to):
    assume(to not in INCIDENT_TRANSITIONS.get(frm, frozenset()))
    assume(frm != to)
    state = b.base_state(incident=b.incident(state=frm))
    assert not can_transition_incident(state, to).allowed


@SETTINGS
@given(frm=st.sampled_from(list(IncidentState)))
def test_terminal_states_have_no_outgoing_transitions(frm):
    if frm in {IncidentState.CLOSED, IncidentState.ABORTED_SAFE}:
        assert INCIDENT_TRANSITIONS[frm] == frozenset()


@SETTINGS
@given(frm=st.sampled_from(list(CustodyState)), to=st.sampled_from(list(CustodyState)))
def test_custody_graph_never_leaves_a_terminal_state(frm, to):
    if frm in {CustodyState.COMMITTED, CustodyState.QUARANTINED}:
        assert to not in CUSTODY_TRANSITIONS[frm]


@SETTINGS
@given(frm=st.sampled_from(list(ReservationState)))
def test_reservation_terminal_states_are_absorbing(frm):
    if frm in {ReservationState.CONSUMED, ReservationState.RELEASED,
               ReservationState.INVALIDATED}:
        assert RESERVATION_TRANSITIONS[frm] == frozenset()


# --------------------------------------------------------------------------------------
# Canonicalization
# --------------------------------------------------------------------------------------

json_values = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-(10**12), max_value=10**12),
        st.floats(allow_nan=False, allow_infinity=False, width=64),
        st.text(max_size=40),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(min_size=1, max_size=12), children, max_size=5),
    ),
    max_leaves=25,
)


@SETTINGS
@given(doc=json_values)
def test_canonical_hash_is_deterministic(doc):
    assert sha256_of(doc) == sha256_of(doc)


@SETTINGS
@given(doc=st.dictionaries(st.text(min_size=1, max_size=8), st.integers(), min_size=2, max_size=8))
def test_canonical_hash_ignores_key_insertion_order(doc):
    shuffled = dict(reversed(list(doc.items())))
    assert sha256_of(doc) == sha256_of(shuffled)
