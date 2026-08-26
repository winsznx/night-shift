"""Closed vocabularies for every Night Shift state machine.

These are the only legal values that may appear in authoritative state. Anything an
LLM produces is validated against them before it reaches a domain service.
"""

from __future__ import annotations

from enum import StrEnum


class IncidentState(StrEnum):
    """PRD §18. Advance only through deterministic transition guards."""

    OBSERVING = "OBSERVING"
    CONFIRMED = "CONFIRMED"
    CONTAINED = "CONTAINED"
    RESCUE_PLANNING = "RESCUE_PLANNING"
    CAPACITY_RESERVED = "CAPACITY_RESERVED"
    DISPATCHED = "DISPATCHED"
    TRANSFER_IN_PROGRESS = "TRANSFER_IN_PROGRESS"
    RECOVERY_MONITORING = "RECOVERY_MONITORING"
    RECONCILING = "RECONCILING"
    CLOSED = "CLOSED"

    # Explicit non-success states. None of these may ever be presented as success.
    NEEDS_REASSESSMENT = "NEEDS_REASSESSMENT"
    ESCALATED = "ESCALATED"
    PARTIAL = "PARTIAL"
    ABORTED_SAFE = "ABORTED_SAFE"


TERMINAL_INCIDENT_STATES: frozenset[IncidentState] = frozenset(
    {IncidentState.CLOSED, IncidentState.ABORTED_SAFE}
)

NON_SUCCESS_INCIDENT_STATES: frozenset[IncidentState] = frozenset(
    {
        IncidentState.NEEDS_REASSESSMENT,
        IncidentState.ESCALATED,
        IncidentState.PARTIAL,
        IncidentState.ABORTED_SAFE,
    }
)


class FreezerState(StrEnum):
    """PRD §19.1."""

    HEALTHY = "HEALTHY"
    SUSPECT = "SUSPECT"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"
    VALIDATED = "VALIDATED"


class ReservationState(StrEnum):
    """PRD §19.2. Only ACTIVE reservations consume capacity."""

    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    INVALIDATED = "INVALIDATED"


CAPACITY_CONSUMING_RESERVATION_STATES: frozenset[ReservationState] = frozenset(
    {ReservationState.PROPOSED, ReservationState.ACTIVE, ReservationState.CONSUMED}
)


class CustodyState(StrEnum):
    """PRD §19.3."""

    AT_SOURCE = "AT_SOURCE"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    COMMITTED = "COMMITTED"

    QUARANTINED = "QUARANTINED"
    UNRESOLVED = "UNRESOLVED"


TERMINAL_CUSTODY_STATES: frozenset[CustodyState] = frozenset(
    {CustodyState.COMMITTED, CustodyState.QUARANTINED}
)
"""A container is *resolved* only in a terminal custody state (N5).

QUARANTINED counts as resolved because it is an explicit, human-visible terminal
disposition — the container is accounted for even though it did not reach its
planned destination. UNRESOLVED is deliberately not terminal.
"""


class RevisionState(StrEnum):
    """PRD §19.4. Missing qualification is not qualification."""

    DRAFT = "DRAFT"
    DRILLING = "DRILLING"
    QUALIFIED = "QUALIFIED"
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    DEPRECATED = "DEPRECATED"


REVISION_STATES_ELIGIBLE_FOR_WORK: frozenset[RevisionState] = frozenset(
    {RevisionState.QUALIFIED, RevisionState.ACTIVE}
)


class Severity(StrEnum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    INFO = "INFO"


class ActionType(StrEnum):
    """Consequential actions. Each one is guarded by N2 exactly-once semantics."""

    CONTAINMENT_HOLD = "CONTAINMENT_HOLD"
    RELEASE_HOLD = "RELEASE_HOLD"
    CAPACITY_RESERVE = "CAPACITY_RESERVE"
    CAPACITY_RELEASE = "CAPACITY_RELEASE"
    WORK_ORDER_CREATE = "WORK_ORDER_CREATE"
    DISPATCH_RESPONDER = "DISPATCH_RESPONDER"
    REPAIR_STATUS = "REPAIR_STATUS"
    CUSTODY_PICKUP = "CUSTODY_PICKUP"
    CUSTODY_DESTINATION_SCAN = "CUSTODY_DESTINATION_SCAN"
    CUSTODY_COMMIT = "CUSTODY_COMMIT"
    CUSTODY_EXCEPTION = "CUSTODY_EXCEPTION"
    IMPACT_SNAPSHOT = "IMPACT_SNAPSHOT"
    INCIDENT_TRANSITION = "INCIDENT_TRANSITION"
    INCIDENT_CLOSE = "INCIDENT_CLOSE"


class ActionStatus(StrEnum):
    COMMITTED = "COMMITTED"
    REFUSED = "REFUSED"
    ERROR = "ERROR"
    UNAVAILABLE = "UNAVAILABLE"


class AgentName(StrEnum):
    """The operational fleet. Each name is a distinct authority principal (N7)."""

    COMMANDER = "incident-commander"
    SIGNAL_INVESTIGATOR = "signal-investigator"
    IMPACT_ANALYST = "impact-analyst"
    CAPACITY_BROKER = "capacity-broker"
    DISPATCH_AGENT = "dispatch-agent"
    CUSTODY_AGENT = "custody-agent"

    # Non-agent principals that may also call domain services.
    INGESTOR = "incident-ingestor"
    RESPONDER_APP = "responder-app"
    DRILL_CONTROLLER = "drill-controller"


class ToolDomain(StrEnum):
    """Coarse authority domains used by the permission matrix (PRD §11.3)."""

    TELEMETRY_SUMMARY = "telemetry.summary"
    TELEMETRY_READ = "telemetry.read"
    TELEMETRY_BACKUP_READ = "telemetry.backup_read"
    TELEMETRY_DESTINATION_READ = "telemetry.destination_read"
    TELEMETRY_EQUIPMENT_READ = "telemetry.equipment_read"

    INVENTORY_SCOPED_READ = "inventory.scoped_read"
    INVENTORY_PLACEMENT_VIEW = "inventory.placement_view"
    INVENTORY_INCIDENT_READ = "inventory.incident_read"
    INVENTORY_WRITE = "inventory.write"

    CAPACITY_READ = "capacity.read"
    CAPACITY_WRITE = "capacity.write"

    FACILITIES_READ = "facilities.read"
    FACILITIES_WRITE = "facilities.write"

    CUSTODY_READ = "custody.read"
    CUSTODY_WRITE = "custody.write"

    INCIDENT_READ = "incident.read"
    INCIDENT_TRANSITION = "incident.transition"


class DenialReason(StrEnum):
    """Why an authorization or precondition check said no. Never invent success."""

    UNREGISTERED_TOOL = "UNREGISTERED_TOOL"
    IDENTITY_NOT_PERMITTED = "IDENTITY_NOT_PERMITTED"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"
    SEMANTIC_POLICY_DENY = "SEMANTIC_POLICY_DENY"
    CONTENT_SCREEN_BLOCK = "CONTENT_SCREEN_BLOCK"
    REVISION_NOT_QUALIFIED = "REVISION_NOT_QUALIFIED"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


class FailureClass(StrEnum):
    """N12 failure attribution. Infrastructure failure is not an agent safety failure."""

    NONE = "NONE"
    AGENT_DECISION = "AGENT_DECISION"
    POLICY_DENIAL = "POLICY_DENIAL"
    INVARIANT_REJECTION = "INVARIANT_REJECTION"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    SIMULATED_FIELD = "SIMULATED_FIELD"


class FaultClass(StrEnum):
    """Equipment fault taxonomy used in work-order semantic keys."""

    COMPRESSOR_FAILURE = "COMPRESSOR_FAILURE"
    DOOR_SEAL = "DOOR_SEAL"
    CONTROLLER_FAULT = "CONTROLLER_FAULT"
    POWER_LOSS = "POWER_LOSS"
    UNKNOWN = "UNKNOWN"


class ResponsePhase(StrEnum):
    """Dispatch phases; part of the dispatch semantic key."""

    INITIAL_ASSESSMENT = "INITIAL_ASSESSMENT"
    TRANSFER = "TRANSFER"
    REPAIR = "REPAIR"
    VALIDATION = "VALIDATION"


class ResponderRole(StrEnum):
    LAB_TECH = "LAB_TECH"
    FACILITIES_TECH = "FACILITIES_TECH"
    ONCALL_MANAGER = "ONCALL_MANAGER"
    VENDOR_ENGINEER = "VENDOR_ENGINEER"
