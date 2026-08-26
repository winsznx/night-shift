"""Structured output contracts for machine-consumed agent decisions (PRD §9 rule 9).

Anything an agent produces that a deterministic component will act on must validate
against one of these. Malformed output is rejected, never coerced (PRD §32.5).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nightshift.schemas.enums import (
    AgentName,
    FaultClass,
    ResponderRole,
    ResponsePhase,
    Severity,
)


class AgentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignalAssessment(AgentOut):
    """Signal Investigator verdict. Read-only domain: telemetry + equipment history."""

    incident_id: str
    classification: Literal[
        "TRANSIENT_EXCURSION", "DOOR_EVENT", "EQUIPMENT_FAILURE", "INCONCLUSIVE"
    ]
    recommended_severity: Severity
    suspected_fault_class: FaultClass
    confidence: float = Field(ge=0.0, le=1.0)
    reobserve_in_seconds: int = Field(ge=0, le=86_400)
    evidence_reading_ids: list[str] = Field(default_factory=list)
    evidence_door_event_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(max_length=1200)
    escalate: bool = False


class ImpactAssessment(AgentOut):
    """Impact Analyst output. Scoped inventory read only — no capacity, no custody."""

    incident_id: str
    container_ids: list[str]
    priority_groups: list[PriorityGroup] = Field(default_factory=list)
    notes: str = Field(default="", max_length=1200)
    inventory_complete: bool = Field(
        description="False when the inventory adapter could not enumerate all containers (D15). "
        "A false value must prevent an authoritative impact snapshot."
    )


class PriorityGroup(AgentOut):
    priority_class: int = Field(ge=1, le=3)
    required_temp_c: float
    container_ids: list[str]
    reason: str = Field(max_length=400)


class PlacementChoice(AgentOut):
    destination_freezer_id: str
    placement_group_id: str
    slots: int = Field(gt=0)
    why: str = Field(max_length=400)


class CapacityPlan(AgentOut):
    """Capacity Broker output. The broker proposes; the Capacity Service disposes."""

    incident_id: str
    choices: list[PlacementChoice]
    fallback_destinations: list[str] = Field(default_factory=list)
    replan_reason: str | None = None
    all_groups_placed: bool


class DispatchDecision(AgentOut):
    """Dispatch/Facilities Agent output. Equipment context only — never specimen data."""

    incident_id: str
    fault_class: FaultClass
    work_order_summary: str = Field(max_length=600)
    responder_role: ResponderRole
    response_phase: ResponsePhase
    vendor_message: str = Field(
        max_length=600,
        description="Sanitized equipment context sent externally. Must contain no study or "
        "specimen metadata (semantic policy SG-05).",
    )
    escalate: bool = False


class CustodyDecision(AgentOut):
    """Custody Agent output. Requests a commit; the Custody Service validates N3/N4.

    ``COMMIT_ALL_READY`` covers the normal case where many containers are scanned in at
    once. It is not a bulk override: the service still evaluates N3 and N4 per container
    and refuses individually, so a batch of forty with one bad destination reading
    commits thirty-nine and refuses one, with a receipt for each.
    """

    incident_id: str
    container_id: str | None = Field(
        default=None, description="Required for every action except COMMIT_ALL_READY."
    )
    action: Literal[
        "REQUEST_COMMIT", "COMMIT_ALL_READY", "FLAG_EXCEPTION", "WAIT_FOR_EVIDENCE", "QUARANTINE"
    ]
    destination_freezer_id: str | None = None
    destination_slot: str | None = None
    reason: str = Field(max_length=600)


class PlanStep(AgentOut):
    specialist: AgentName
    objective: str = Field(max_length=300)
    blocking: bool = True


class CommanderPlan(AgentOut):
    """Incident Commander output. The Commander has no direct mutation authority."""

    incident_id: str
    assessment: str = Field(max_length=1200)
    next_steps: list[PlanStep]
    request_closure: bool = False
    reassess_in_seconds: int = Field(ge=0, le=86_400, default=0)
    escalate: bool = False
    escalation_reason: str | None = None


ImpactAssessment.model_rebuild()
CapacityPlan.model_rebuild()
CommanderPlan.model_rebuild()
