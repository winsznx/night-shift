"""Build the ADK agents.

Each specialist is an ``LlmAgent`` with a structured output schema and a toolset derived
from its authority. The Commander is built the same way and is deliberately *not* given
sub-agents in the ADK transfer sense — delegation is orchestrated deterministically in
``agents/orchestrator.py`` so that specialist ordering, budgets, and resume points are
observable state rather than an emergent property of a conversation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google.adk.agents import LlmAgent
from google.genai import types

from agents.prompts import build_prompt
from agents.toolsets import build_toolset
from nightshift.schemas.agent_io import (
    CapacityPlan,
    CommanderPlan,
    CustodyDecision,
    DispatchDecision,
    ImpactAssessment,
    SignalAssessment,
)
from nightshift.schemas.enums import AgentName
from services.gateway.broker import ToolBroker

AGENT_DESCRIPTIONS: dict[AgentName, str] = {
    AgentName.COMMANDER: "Owns the incident plan and decides which specialist works next.",
    AgentName.SIGNAL_INVESTIGATOR: "Decides whether telemetry shows a real equipment failure.",
    AgentName.IMPACT_ANALYST: "Establishes which material is affected and how urgently.",
    AgentName.CAPACITY_BROKER: "Finds and reserves safe backup capacity.",
    AgentName.DISPATCH_AGENT: "Opens work orders and dispatches responders.",
    AgentName.CUSTODY_AGENT: "Verifies transfer evidence and commits custody.",
}

OUTPUT_SCHEMAS: dict[AgentName, Any] = {
    AgentName.COMMANDER: CommanderPlan,
    AgentName.SIGNAL_INVESTIGATOR: SignalAssessment,
    AgentName.IMPACT_ANALYST: ImpactAssessment,
    AgentName.CAPACITY_BROKER: CapacityPlan,
    AgentName.DISPATCH_AGENT: DispatchDecision,
    AgentName.CUSTODY_AGENT: CustodyDecision,
}

_ADK_SAFE_NAMES = {
    AgentName.COMMANDER: "incident_commander",
    AgentName.SIGNAL_INVESTIGATOR: "signal_investigator",
    AgentName.IMPACT_ANALYST: "impact_analyst",
    AgentName.CAPACITY_BROKER: "capacity_broker",
    AgentName.DISPATCH_AGENT: "dispatch_agent",
    AgentName.CUSTODY_AGENT: "custody_agent",
}


@dataclass(frozen=True)
class AgentBuild:
    agent: LlmAgent
    name: AgentName
    revision: str
    tool_names: list[str]


def build_agent(
    name: AgentName,
    broker: ToolBroker,
    incident_id: str,
    *,
    model: str,
    revision: str = "rev-1",
    skill_refs: dict[str, str] | None = None,
    memory_context: list[str] | None = None,
    structured_output: bool = True,
) -> AgentBuild:
    """Build one specialist.

    ``structured_output`` is off for tool-using agents by default in ADK terms: an
    ``output_schema`` and ``tools`` cannot both be set, so the schema is enforced by
    the orchestrator parsing the final message instead. That keeps the contract without
    giving up tools.
    """
    tools = build_toolset(broker, name, incident_id)
    schema = OUTPUT_SCHEMAS[name]
    instruction = build_prompt(
        name, incident_id, skill_refs=skill_refs, memory_context=memory_context
    )
    instruction += (
        "\n\n## Response format\n\n"
        "When you have finished, your final message must be a single JSON object that "
        "validates against this JSON Schema — nothing else, no markdown fence, no "
        "commentary before or after. Use exactly these field names. Do not add fields "
        "that are not in the schema, and do not omit required ones.\n\n"
        f"```json\n{_schema_hint(schema)}\n```\n\n"
        f"{_schema_example(name)}"
    )

    agent = LlmAgent(
        name=_ADK_SAFE_NAMES[name],
        model=model,
        description=AGENT_DESCRIPTIONS[name],
        instruction=instruction,
        tools=tools,  # type: ignore[arg-type]
        generate_content_config=types.GenerateContentConfig(temperature=0.0),
    )
    return AgentBuild(
        agent=agent,
        name=name,
        revision=revision,
        tool_names=[t.__name__ for t in tools],
    )


def build_fleet(
    broker: ToolBroker,
    incident_id: str,
    *,
    model: str,
    revisions: dict[AgentName, str] | None = None,
    skill_refs: dict[str, str] | None = None,
    memory_context: list[str] | None = None,
) -> dict[AgentName, AgentBuild]:
    revisions = revisions or {}
    return {
        name: build_agent(
            name,
            broker,
            incident_id,
            model=model,
            revision=revisions.get(name, "rev-1"),
            skill_refs=skill_refs,
            memory_context=memory_context if name is AgentName.CAPACITY_BROKER else None,
        )
        for name in AGENT_DESCRIPTIONS
    }
    # Memory context is injected only where the stale-memory drill needs it to be
    # visible (D9 targets the Capacity Broker). Every agent is instructed to treat
    # memory as non-authoritative regardless.


def _schema_hint(schema: Any) -> str:
    """Full JSON Schema, minus the noise.

    A compact field list was tried first and the model invented plausible-but-wrong
    field names for nested objects — ``{"specialist": "impact-assessment", "reason": …}``
    instead of ``{"specialist": "impact-analyst", "objective": …}``. Nested shapes and
    enum members have to be spelled out, so the real schema goes in.
    """
    import json

    doc = schema.model_json_schema()
    doc.pop("title", None)
    for definition in (doc.get("$defs") or {}).values():
        definition.pop("title", None)
    for prop in (doc.get("properties") or {}).values():
        prop.pop("title", None)
    return json.dumps(doc, indent=2)


_EXAMPLES: dict[AgentName, str] = {
    AgentName.COMMANDER: """Example of a well-formed final message:

{"incident_id": "INC-EXAMPLE", "assessment": "Impact set is unknown, so capacity \
planning is premature. Establishing impact first.", "next_steps": [{"specialist": \
"impact-analyst", "objective": "Enumerate every container in F-17 and record the \
impact snapshot", "blocking": true}], "request_closure": false, \
"reassess_in_seconds": 0, "escalate": false, "escalation_reason": null}

Note that `specialist` is an agent identity such as "impact-analyst" or \
"capacity-broker" — never a skill name.""",
    AgentName.SIGNAL_INVESTIGATOR: """Example of a well-formed final message:

{"incident_id": "INC-EXAMPLE", "classification": "EQUIPMENT_FAILURE", \
"recommended_severity": "SEV1", "suspected_fault_class": "COMPRESSOR_FAILURE", \
"confidence": 0.86, "reobserve_in_seconds": 600, "evidence_reading_ids": \
["R-F-17-INJ-0000", "R-F-17-INJ-0017"], "evidence_door_event_ids": [], "rationale": \
"Temperature rose continuously for 90 minutes with no door event in the window.", \
"escalate": false}""",
    AgentName.IMPACT_ANALYST: """Example of a well-formed final message:

{"incident_id": "INC-EXAMPLE", "container_ids": ["C-0001", "C-0002"], \
"priority_groups": [{"priority_class": 1, "required_temp_c": -80.0, "container_ids": \
["C-0001"], "reason": "Priority class 1 study material"}], "notes": "Enumeration \
returned a complete read.", "inventory_complete": true}""",
    AgentName.CAPACITY_BROKER: """Example of a well-formed final message:

{"incident_id": "INC-EXAMPLE", "choices": [{"destination_freezer_id": "F-31", \
"placement_group_id": "PG-INC-EXAMPLE-P1-T80", "slots": 12, "why": "47 unreserved \
slots at -80.6C, largest temperature margin"}], "fallback_destinations": ["F-03"], \
"replan_reason": null, "all_groups_placed": true}""",
    AgentName.DISPATCH_AGENT: """Example of a well-formed final message:

{"incident_id": "INC-EXAMPLE", "fault_class": "COMPRESSOR_FAILURE", \
"work_order_summary": "ULT F-17 not holding setpoint; sustained rise over 90 minutes", \
"responder_role": "LAB_TECH", "response_phase": "TRANSFER", "vendor_message": "ULT \
F-17, model Synthetic ULT-700, zone B2. Sustained rise from -79C to -38C over 90 \
minutes, door closed throughout. Requesting compressor service.", "escalate": false}""",
    AgentName.CUSTODY_AGENT: """Example of a well-formed final message:

{"incident_id": "INC-EXAMPLE", "container_id": null, "action": "COMMIT_ALL_READY", \
"destination_freezer_id": null, "destination_slot": null, "reason": \
"38 containers are scanned in with fresh destination readings; committing the ready \
set. Each is validated individually by the service."}

Use COMMIT_ALL_READY with container_id null when several containers are ready at once — \
that is the normal case after a responder finishes a batch.""",
}


def _schema_example(name: AgentName) -> str:
    return _EXAMPLES.get(name, "")
