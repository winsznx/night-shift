"""Authoritative domain objects.

Every field here is deterministic state. No LLM output lands in these models without
passing through a domain service that validates it against the Safety Kernel first.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nightshift.schemas.enums import (
    ActionStatus,
    ActionType,
    AgentName,
    CustodyState,
    FailureClass,
    FaultClass,
    FreezerState,
    IncidentState,
    ReservationState,
    ResponderRole,
    ResponsePhase,
    Severity,
)

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Timestamp = Annotated[str, Field(description="RFC3339 UTC, e.g. 2026-08-26T01:02:03.000Z")]


class Strict(BaseModel):
    """Base model: reject unknown fields so drifted payloads fail loudly."""

    model_config = ConfigDict(extra="forbid", frozen=False, use_enum_values=False)


# --------------------------------------------------------------------------------------
# Estate
# --------------------------------------------------------------------------------------


class Site(Strict):
    id: str
    name: str
    timezone: str
    synthetic: Literal[True] = True


class TemperatureReading(Strict):
    id: str
    freezer_id: str
    celsius: float
    recorded_at: Timestamp
    source: str = "sensor"
    synthetic: Literal[True] = True


class DoorEvent(Strict):
    id: str
    freezer_id: str
    opened_at: Timestamp
    closed_at: Timestamp | None = None
    duration_s: int | None = None
    badge_ref: str | None = Field(
        default=None, description="Synthetic badge id, never a real person"
    )


class MaintenanceRecord(Strict):
    id: str
    freezer_id: str
    occurred_at: Timestamp
    summary: str
    fault_class: FaultClass = FaultClass.UNKNOWN


class Freezer(Strict):
    id: str
    site_id: str
    label: str
    model: str
    zone: str
    setpoint_c: float
    alarm_high_c: float
    total_slots: int = Field(ge=0)
    occupied_slots: int = Field(ge=0)
    state: FreezerState = FreezerState.HEALTHY
    current_temp_c: float
    last_reading_at: Timestamp
    is_backup_qualified: bool = False
    maintenance: list[MaintenanceRecord] = Field(default_factory=list)
    synthetic: Literal[True] = True

    @property
    def free_slots(self) -> int:
        return max(0, self.total_slots - self.occupied_slots)


class Responder(Strict):
    id: str
    display_name: str
    role: ResponderRole
    on_call: bool = False
    site_id: str
    synthetic: Literal[True] = True


# --------------------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------------------


class Container(Strict):
    """A rack/box level unit. Specimen records nest under it and are never exposed
    wholesale to agents that lack inventory authority."""

    id: str
    freezer_id: str
    slot_id: str
    kind: Literal["rack", "box", "cryobox"] = "box"
    study_id: str
    owner_ref: str
    priority_class: int = Field(ge=1, le=3, description="1 = most critical")
    specimen_count: int = Field(ge=0)
    required_temp_c: float
    custody_state: CustodyState = CustodyState.AT_SOURCE
    incident_id: str | None = None
    synthetic: Literal[True] = True


class PlacementGroup(Strict):
    """A set of containers the Capacity Broker wants to place together.

    `id` is stable for a given (incident, priority class, required temperature) so the
    derived reservation action_id is stable across retries (PRD §16).
    """

    id: str
    incident_id: str
    priority_class: int
    required_temp_c: float
    container_ids: list[str]
    slot_count: int = Field(ge=0)


class ImpactSnapshot(Strict):
    """Immutable per-incident impact record. Hash is what the manifest references."""

    id: str
    incident_id: str
    created_at: Timestamp
    freezer_id: str
    container_ids: list[str]
    specimen_total: int
    study_ids: list[str]
    priority_breakdown: dict[str, int]
    placement_groups: list[PlacementGroup]
    snapshot_hash: Sha256

    @field_validator("container_ids", "study_ids")
    @classmethod
    def _sorted_unique(cls, v: list[str]) -> list[str]:
        return sorted(set(v))


class ContainmentHold(Strict):
    """N13. While active, non-rescue placement/withdrawal on the freezer is refused."""

    id: str
    incident_id: str
    freezer_id: str
    active: bool
    placed_at: Timestamp
    released_at: Timestamp | None = None
    release_evidence_ref: str | None = None


# --------------------------------------------------------------------------------------
# Rescue effects
# --------------------------------------------------------------------------------------


class Reservation(Strict):
    id: str
    action_id: Sha256
    incident_id: str
    destination_freezer_id: str
    placement_group_id: str
    slots: int = Field(gt=0, description="Slots originally reserved. Never changes.")
    slots_remaining: int | None = Field(
        default=None,
        ge=0,
        description="Slots still held but not yet filled. Defaults to `slots`. Each "
        "committed transfer decrements it: that capacity has become real occupancy, so "
        "continuing to count it as reserved would double-book the destination against "
        "itself (N1).",
    )
    slot_ids: list[str] = Field(default_factory=list)
    state: ReservationState = ReservationState.ACTIVE
    created_at: Timestamp
    updated_at: Timestamp
    invalidation_reason: str | None = None

    @property
    def held_slots(self) -> int:
        """Capacity this reservation is currently withholding from other incidents."""
        return self.slots if self.slots_remaining is None else self.slots_remaining


class WorkOrder(Strict):
    id: str
    action_id: Sha256
    incident_id: str
    freezer_id: str
    fault_class: FaultClass
    summary: str
    status: Literal["OPEN", "IN_PROGRESS", "RESOLVED", "CANCELLED"] = "OPEN"
    created_at: Timestamp
    vendor_ref: str | None = None
    repair_events: list[dict[str, Any]] = Field(default_factory=list)


class Dispatch(Strict):
    id: str
    action_id: Sha256
    incident_id: str
    responder_id: str
    responder_role: ResponderRole
    response_phase: ResponsePhase
    task_token: str = Field(description="Unguessable, drill/incident scoped (threat model §31)")
    status: Literal["SENT", "ACKNOWLEDGED", "COMPLETED", "CANCELLED"] = "SENT"
    created_at: Timestamp
    container_ids: list[str] = Field(default_factory=list)


class ScanEvidence(Strict):
    scan_id: str
    container_id: str
    location_ref: str
    scanned_at: Timestamp
    responder_id: str
    signature: str = Field(description="HMAC over the scan body using the task token secret")
    simulated: bool = False


class Transfer(Strict):
    transfer_id: str
    incident_id: str
    container_id: str
    source_freezer: str
    destination_freezer: str
    destination_slot: str
    reservation_id: str | None = None
    pickup_evidence: ScanEvidence | None = None
    destination_evidence: ScanEvidence | None = None
    destination_temp_reading_id: str | None = None
    destination_temp_c: float | None = None
    destination_temp_recorded_at: Timestamp | None = None
    state: CustodyState = CustodyState.AT_SOURCE
    commit_receipt: str | None = None
    exception_reason: str | None = None


# --------------------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------------------


class ActionReceipt(Strict):
    """The authoritative answer to 'did this actually happen?'.

    A tool call is not successful until one of these exists (PRD §9 rule 5).
    """

    receipt_id: str
    action_id: Sha256
    incident_id: str
    action_type: ActionType
    actor_identity: str
    requested_by_agent: AgentName | None = None
    requested_by_agent_revision: str | None = None
    request_hash: Sha256
    effect_ref: str | None = None
    status: ActionStatus
    failure_class: FailureClass = FailureClass.NONE
    refusal_reason: str | None = None
    evidence_sources: list[str] = Field(
        default_factory=list,
        description="Authoritative reads this effect relied on, e.g. 'firestore:reservations' "
        "or 'telemetry:F-03'. Memory Bank context is prefixed 'memory:' and can never be "
        "the sole entry (N8).",
    )
    committed_at: Timestamp
    duplicate_returned: bool = False
    trace_id: str | None = None


class IncidentEvent(Strict):
    """Append-only incident timeline entry. Agent reasoning and deterministic receipts
    are kept visually and structurally distinct (PRD §35.2)."""

    event_id: str
    incident_id: str
    occurred_at: Timestamp
    source: str
    kind: Literal[
        "sensor",
        "state_transition",
        "agent_decision",
        "agent_delegation",
        "tool_call",
        "receipt",
        "refusal",
        "policy",
        "security",
        "fault_injection",
        "field",
        "note",
    ]
    correlation_id: str
    payload_version: int = 1
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)
    action_id: str | None = None
    agent: AgentName | None = None
    trace_id: str | None = None


class StateTransition(Strict):
    from_state: IncidentState
    to_state: IncidentState
    at: Timestamp
    source_event_id: str | None = None
    source_action_id: str | None = None
    reason: str


class Incident(Strict):
    id: str
    site_id: str
    failed_freezer_id: str
    state: IncidentState = IncidentState.OBSERVING
    severity: Severity = Severity.INFO
    opened_at: Timestamp
    last_evidence_at: Timestamp
    closed_at: Timestamp | None = None
    impact_snapshot_hash: Sha256 | None = None
    impact_snapshot_id: str | None = None
    active_skill_revisions: dict[str, str] = Field(default_factory=dict)
    active_agent_revisions: dict[str, str] = Field(default_factory=dict)
    containment_hold_id: str | None = None
    unresolved_count: int = 0
    trace_root_id: str | None = None
    namespace: str = "demo"
    synthetic: Literal[True] = True
    transitions: list[StateTransition] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    dedupe_key: str | None = Field(
        default=None, description="sha256(site|freezer|window) — D3 duplicate sensor delivery"
    )


class AgentRevision(Strict):
    """PRD §19.4 + §23.5. Missing qualification is not qualification."""

    agent: AgentName
    revision_id: str
    state: str
    source_commit: str
    adk_version: str
    model_id: str
    skill_revisions: dict[str, str] = Field(default_factory=dict)
    runtime_resource: str | None = None
    identity: str | None = None
    traffic_percent: int = 0
    qualified_at: Timestamp | None = None
    qualification_run_id: str | None = None
    blocked_reason: str | None = None
