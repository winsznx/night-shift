"""Deterministic builders for kernel-level tests.

These construct ``KernelState`` directly. They deliberately do *not* reimplement any
kernel logic — tests assert against the kernel's own functions (PRD §15).
"""

from __future__ import annotations

from typing import Any

from nightshift.common.canonical import sha256_of
from nightshift.common.ids import (
    close_action_id,
    reservation_action_id,
    transfer_action_id,
)
from nightshift.safety_kernel.world import KernelState, reconciliation_snapshot
from nightshift.schemas.core import (
    ActionReceipt,
    Container,
    ContainmentHold,
    Dispatch,
    Freezer,
    ImpactSnapshot,
    Incident,
    PlacementGroup,
    Reservation,
    ScanEvidence,
    Transfer,
    WorkOrder,
)
from nightshift.schemas.enums import (
    ActionStatus,
    ActionType,
    AgentName,
    CustodyState,
    FaultClass,
    FreezerState,
    IncidentState,
    ReservationState,
    ResponderRole,
    ResponsePhase,
    Severity,
)

T0 = "2026-08-26T02:00:00.000Z"
T_NOW = "2026-08-26T02:10:00.000Z"
ZERO_HASH = "0" * 64


def freezer(
    fid: str = "F-17",
    *,
    total: int = 100,
    occupied: int = 40,
    temp: float = -78.0,
    backup: bool = False,
    state: FreezerState = FreezerState.HEALTHY,
    last_reading_at: str = T_NOW,
) -> Freezer:
    return Freezer(
        id=fid,
        site_id="SITE-1",
        label=f"ULT {fid}",
        model="Synthetic ULT-700",
        zone="B2",
        setpoint_c=-80.0,
        alarm_high_c=-65.0,
        total_slots=total,
        occupied_slots=occupied,
        state=state,
        current_temp_c=temp,
        last_reading_at=last_reading_at,
        is_backup_qualified=backup,
    )


def container(
    cid: str,
    *,
    freezer_id: str = "F-17",
    incident_id: str | None = "INC-1",
    custody: CustodyState = CustodyState.AT_SOURCE,
    priority: int = 1,
    specimens: int = 81,
) -> Container:
    return Container(
        id=cid,
        freezer_id=freezer_id,
        slot_id=f"{freezer_id}-S{cid[-3:]}",
        study_id="STUDY-A",
        owner_ref="owner-synthetic-1",
        priority_class=priority,
        specimen_count=specimens,
        required_temp_c=-80.0,
        custody_state=custody,
        incident_id=incident_id,
    )


def incident(
    *,
    state: IncidentState = IncidentState.OBSERVING,
    iid: str = "INC-1",
    freezer_id: str = "F-17",
) -> Incident:
    return Incident(
        id=iid,
        site_id="SITE-1",
        failed_freezer_id=freezer_id,
        state=state,
        severity=Severity.SEV1,
        opened_at=T0,
        last_evidence_at=T_NOW,
    )


def placement_group(
    gid: str = "PG-1", *, incident_id: str = "INC-1", containers: list[str] | None = None
) -> PlacementGroup:
    cids = containers or ["C-001", "C-002"]
    return PlacementGroup(
        id=gid,
        incident_id=incident_id,
        priority_class=1,
        required_temp_c=-80.0,
        container_ids=cids,
        slot_count=len(cids),
    )


def impact(
    *, incident_id: str = "INC-1", containers: list[str] | None = None, groups: list[PlacementGroup] | None = None
) -> ImpactSnapshot:
    cids = containers or ["C-001", "C-002"]
    body: dict[str, Any] = {
        "incident_id": incident_id,
        "container_ids": sorted(cids),
        "specimen_total": 81 * len(cids),
    }
    return ImpactSnapshot(
        id="IMP-1",
        incident_id=incident_id,
        created_at=T0,
        freezer_id="F-17",
        container_ids=cids,
        specimen_total=81 * len(cids),
        study_ids=["STUDY-A"],
        priority_breakdown={"1": len(cids)},
        placement_groups=groups or [placement_group(containers=cids)],
        snapshot_hash=sha256_of(body),
    )


def reservation(
    *,
    incident_id: str = "INC-1",
    destination: str = "F-03",
    group_id: str = "PG-1",
    slots: int = 2,
    state: ReservationState = ReservationState.ACTIVE,
    rid: str | None = None,
) -> Reservation:
    action_id = reservation_action_id(incident_id, destination, group_id)
    return Reservation(
        id=rid or f"RES-{action_id[:8]}",
        action_id=action_id,
        incident_id=incident_id,
        destination_freezer_id=destination,
        placement_group_id=group_id,
        slots=slots,
        state=state,
        created_at=T0,
        updated_at=T0,
    )


def scan(container_id: str, location: str, *, at: str = T_NOW) -> ScanEvidence:
    return ScanEvidence(
        scan_id=f"SCAN-{container_id}-{location}",
        container_id=container_id,
        location_ref=location,
        scanned_at=at,
        responder_id="RESP-1",
        signature="sig-synthetic",
        simulated=True,
    )


def transfer(
    container_id: str,
    *,
    incident_id: str = "INC-1",
    destination: str = "F-03",
    reservation_id: str | None = None,
    state: CustodyState = CustodyState.AT_SOURCE,
    with_pickup: bool = False,
    with_destination: bool = False,
    dest_temp: float | None = -79.0,
    dest_temp_at: str | None = T_NOW,
) -> Transfer:
    return Transfer(
        transfer_id=f"TR-{container_id}",
        incident_id=incident_id,
        container_id=container_id,
        source_freezer="F-17",
        destination_freezer=destination,
        destination_slot=f"{destination}-SLOT-{container_id[-3:]}",
        reservation_id=reservation_id,
        pickup_evidence=scan(container_id, "F-17") if with_pickup else None,
        destination_evidence=scan(container_id, destination) if with_destination else None,
        destination_temp_reading_id="R-1" if dest_temp is not None else None,
        destination_temp_c=dest_temp,
        destination_temp_recorded_at=dest_temp_at,
        state=state,
    )


def receipt(
    action_id: str,
    action_type: ActionType,
    *,
    actor: str = "capacity-broker",
    status: ActionStatus = ActionStatus.COMMITTED,
    effect_ref: str | None = None,
    agent: AgentName | None = AgentName.CAPACITY_BROKER,
    revision: str | None = "rev-1",
    evidence_sources: list[str] | None = None,
    duplicate: bool = False,
) -> ActionReceipt:
    from nightshift.schemas.enums import FailureClass

    return ActionReceipt(
        receipt_id=f"RCP-{action_id[:10]}",
        action_id=action_id,
        incident_id="INC-1",
        action_type=action_type,
        actor_identity=actor,
        requested_by_agent=agent,
        requested_by_agent_revision=revision,
        request_hash=ZERO_HASH,
        effect_ref=effect_ref,
        status=status,
        failure_class=FailureClass.NONE if status is ActionStatus.COMMITTED else FailureClass.AGENT_DECISION,
        committed_at=T_NOW,
        duplicate_returned=duplicate,
        evidence_sources=evidence_sources or ["firestore:reservations"],
    )


def work_order(*, incident_id: str = "INC-1", freezer_id: str = "F-17") -> WorkOrder:
    from nightshift.common.ids import work_order_action_id

    aid = work_order_action_id(incident_id, freezer_id, FaultClass.COMPRESSOR_FAILURE)
    return WorkOrder(
        id=f"WO-{aid[:8]}",
        action_id=aid,
        incident_id=incident_id,
        freezer_id=freezer_id,
        fault_class=FaultClass.COMPRESSOR_FAILURE,
        summary="Compressor not maintaining setpoint",
        created_at=T0,
    )


def dispatch(*, incident_id: str = "INC-1") -> Dispatch:
    from nightshift.common.ids import dispatch_action_id

    aid = dispatch_action_id(incident_id, ResponsePhase.TRANSFER, ResponderRole.LAB_TECH)
    return Dispatch(
        id=f"DSP-{aid[:8]}",
        action_id=aid,
        incident_id=incident_id,
        responder_id="RESP-1",
        responder_role=ResponderRole.LAB_TECH,
        response_phase=ResponsePhase.TRANSFER,
        task_token="tok-synthetic",
        created_at=T0,
    )


def hold(*, freezer_id: str = "F-17", active: bool = True, evidence: str | None = None) -> ContainmentHold:
    return ContainmentHold(
        id=f"HOLD-{freezer_id}",
        incident_id="INC-1",
        freezer_id=freezer_id,
        active=active,
        placed_at=T0,
        released_at=None if active else T_NOW,
        release_evidence_ref=evidence,
    )


def qualified_revisions() -> dict[str, str]:
    return {f"{a.value}@rev-1": "ACTIVE" for a in AgentName}


def base_state(**overrides: Any) -> KernelState:
    """A healthy mid-incident snapshot: two containers, one backup freezer with room."""
    containers = {
        "C-001": container("C-001"),
        "C-002": container("C-002"),
    }
    freezers = {
        "F-17": freezer("F-17", temp=-52.0, state=FreezerState.FAILED),
        "F-03": freezer("F-03", total=60, occupied=50, temp=-79.0, backup=True),
    }
    defaults: dict[str, Any] = {
        "incident": incident(state=IncidentState.RESCUE_PLANNING),
        "freezers": freezers,
        "containers": containers,
        "impact": impact(),
        "revision_states": qualified_revisions(),
        "holds": {"F-17": hold()},
    }
    defaults.update(overrides)
    return KernelState(**defaults)


def closed_state_all_committed() -> KernelState:
    """A snapshot that legitimately reached CLOSED."""
    res = reservation()
    containers = {
        cid: container(cid, custody=CustodyState.COMMITTED, freezer_id="F-03")
        for cid in ("C-001", "C-002")
    }
    transfers = {}
    receipts = {}
    for cid in ("C-001", "C-002"):
        t = transfer(
            cid,
            reservation_id=res.id,
            state=CustodyState.COMMITTED,
            with_pickup=True,
            with_destination=True,
        )
        transfers[t.transfer_id] = t
        aid = transfer_action_id("INC-1", cid, t.destination_slot)
        receipts[aid] = receipt(
            aid,
            ActionType.CUSTODY_COMMIT,
            actor="custody-agent",
            agent=AgentName.CUSTODY_AGENT,
            effect_ref=t.transfer_id,
        )
    receipts[res.action_id] = receipt(
        res.action_id, ActionType.CAPACITY_RESERVE, effect_ref=res.id
    )

    state = KernelState(
        incident=incident(state=IncidentState.RECONCILING),
        freezers={
            "F-17": freezer("F-17", temp=-52.0, state=FreezerState.FAILED),
            "F-03": freezer("F-03", total=60, occupied=50, temp=-79.0, backup=True),
        },
        containers=containers,
        impact=impact(),
        reservations={res.id: res},
        transfers=transfers,
        receipts=receipts,
        revision_states=qualified_revisions(),
        holds={"F-17": hold(active=False, evidence="VALIDATION-1")},
    )
    snap = reconciliation_snapshot(state)
    close_aid = close_action_id("INC-1", snap.snapshot_hash)
    receipts[close_aid] = receipt(
        close_aid,
        ActionType.INCIDENT_CLOSE,
        actor="incident-commander",
        agent=AgentName.COMMANDER,
    )
    closed = state.incident.model_copy(update={"state": IncidentState.CLOSED})  # type: ignore[union-attr]
    return KernelState(
        incident=closed,
        freezers=state.freezers,
        containers=state.containers,
        impact=state.impact,
        reservations=state.reservations,
        transfers=state.transfers,
        receipts=receipts,
        revision_states=state.revision_states,
        holds=state.holds,
    )
