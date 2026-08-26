"""The immutable state snapshot the kernel reasons over.

``KernelState`` is the *entire* input to every invariant. Nothing is fetched lazily and
nothing is read from a clock or a network, which is what lets the offline verifier
recompute a live incident's verdict from a stored snapshot and get the same answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nightshift.common.canonical import sha256_of
from nightshift.schemas.core import (
    ActionReceipt,
    Container,
    ContainmentHold,
    Dispatch,
    Freezer,
    ImpactSnapshot,
    Incident,
    Reservation,
    TemperatureReading,
    Transfer,
    WorkOrder,
)
from nightshift.schemas.enums import (
    CAPACITY_CONSUMING_RESERVATION_STATES,
    TERMINAL_CUSTODY_STATES,
    ActionStatus,
    ActionType,
    AgentName,
    CustodyState,
    ReservationState,
)


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """A proposed consequential action, before any effect exists."""

    action_id: str
    action_type: ActionType
    incident_id: str
    actor_identity: str
    payload: dict[str, Any] = field(default_factory=dict)
    requested_by_agent: AgentName | None = None
    requested_by_agent_revision: str | None = None
    now: str = ""
    """Caller-supplied evaluation time. The kernel never reads a clock itself."""

    @property
    def request_hash(self) -> str:
        return sha256_of(
            {
                "action_id": self.action_id,
                "action_type": self.action_type.value,
                "incident_id": self.incident_id,
                "payload": self.payload,
            }
        )


@dataclass(frozen=True, slots=True)
class KernelState:
    """Everything the kernel is allowed to know."""

    incident: Incident | None = None
    freezers: dict[str, Freezer] = field(default_factory=dict)
    containers: dict[str, Container] = field(default_factory=dict)
    reservations: dict[str, Reservation] = field(default_factory=dict)
    work_orders: dict[str, WorkOrder] = field(default_factory=dict)
    dispatches: dict[str, Dispatch] = field(default_factory=dict)
    transfers: dict[str, Transfer] = field(default_factory=dict)
    receipts: dict[str, ActionReceipt] = field(default_factory=dict)
    """Keyed by ``action_id``, not receipt id — this is the exactly-once index."""
    holds: dict[str, ContainmentHold] = field(default_factory=dict)
    """Keyed by freezer id."""
    impact: ImpactSnapshot | None = None
    readings: dict[str, TemperatureReading] = field(default_factory=dict)
    revision_states: dict[str, str] = field(default_factory=dict)
    """``"<agent>@<revision>" -> RevisionState`` for N10."""
    memory_notes: list[dict[str, Any]] = field(default_factory=list)
    """Non-authoritative Memory Bank context. Never a basis for a transition (N8)."""
    unavailable_sources: frozenset[str] = frozenset()
    """Domains whose authoritative read failed. Drives N11 fail-closed behaviour."""

    # ---- derived views ---------------------------------------------------------

    def receipt_for(self, action_id: str) -> ActionReceipt | None:
        return self.receipts.get(action_id)

    def committed_receipt_for(self, action_id: str) -> ActionReceipt | None:
        r = self.receipts.get(action_id)
        return r if r is not None and r.status is ActionStatus.COMMITTED else None

    def active_reservations_for(self, freezer_id: str) -> list[Reservation]:
        return [
            r
            for r in self.reservations.values()
            if r.destination_freezer_id == freezer_id
            and r.state in CAPACITY_CONSUMING_RESERVATION_STATES
        ]

    def reserved_slots(self, freezer_id: str) -> int:
        return sum(r.slots for r in self.active_reservations_for(freezer_id))

    def verified_available_slots(self, freezer_id: str) -> int:
        f = self.freezers.get(freezer_id)
        return 0 if f is None else f.free_slots

    def incident_container_ids(self) -> list[str]:
        if self.impact is not None:
            return list(self.impact.container_ids)
        if self.incident is None:
            return []
        return sorted(
            c.id for c in self.containers.values() if c.incident_id == self.incident.id
        )

    def unresolved_container_ids(self) -> list[str]:
        """Containers that have not reached a terminal custody state (N5)."""
        out: list[str] = []
        for cid in self.incident_container_ids():
            container = self.containers.get(cid)
            if container is None:
                out.append(cid)
                continue
            if container.custody_state not in TERMINAL_CUSTODY_STATES:
                out.append(cid)
        return out

    def transfers_for_container(self, container_id: str) -> list[Transfer]:
        return [t for t in self.transfers.values() if t.container_id == container_id]

    def active_hold(self, freezer_id: str) -> ContainmentHold | None:
        hold = self.holds.get(freezer_id)
        return hold if hold is not None and hold.active else None


@dataclass(frozen=True, slots=True)
class ReconciliationSnapshot:
    """The deterministic answer to 'is every container accounted for?'.

    Its hash is part of the close action's semantic key, so a close request computed
    against a different reconciliation cannot replay an earlier close receipt.
    """

    incident_id: str
    total: int
    committed: list[str]
    quarantined: list[str]
    unresolved: list[str]
    in_flight: list[str]
    complete: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "total": self.total,
            "committed": self.committed,
            "quarantined": self.quarantined,
            "unresolved": self.unresolved,
            "in_flight": self.in_flight,
            "complete": self.complete,
        }

    @property
    def snapshot_hash(self) -> str:
        return sha256_of(self.as_dict())


def reconciliation_snapshot(state: KernelState) -> ReconciliationSnapshot:
    incident_id = state.incident.id if state.incident else ""
    committed: list[str] = []
    quarantined: list[str] = []
    unresolved: list[str] = []
    in_flight: list[str] = []

    for cid in state.incident_container_ids():
        container = state.containers.get(cid)
        if container is None:
            unresolved.append(cid)
            continue
        match container.custody_state:
            case CustodyState.COMMITTED:
                committed.append(cid)
            case CustodyState.QUARANTINED:
                quarantined.append(cid)
            case CustodyState.UNRESOLVED:
                unresolved.append(cid)
            case _:
                in_flight.append(cid)

    total = len(state.incident_container_ids())
    return ReconciliationSnapshot(
        incident_id=incident_id,
        total=total,
        committed=sorted(committed),
        quarantined=sorted(quarantined),
        unresolved=sorted(unresolved),
        in_flight=sorted(in_flight),
        complete=total > 0 and not unresolved and not in_flight,
    )


def reservation_is_capacity_consuming(reservation: Reservation) -> bool:
    return reservation.state in CAPACITY_CONSUMING_RESERVATION_STATES


def reservation_is_live(reservation: Reservation) -> bool:
    """Live means 'can still back a custody commit' — PROPOSED does not qualify."""
    return reservation.state in {ReservationState.ACTIVE, ReservationState.CONSUMED}
