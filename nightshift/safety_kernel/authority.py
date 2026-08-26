"""Tool registry and the least-privilege permission matrix (PRD §11.3, invariant N7).

Two independent rules apply to every agent-to-tool call:

1. the tool must be *registered* — unregistered endpoints are unreachable by default;
2. the calling identity must hold the tool's authority domain.

This table is the deterministic authorization layer. When live Agent Gateway
enforcement is available it sits in front of this and both must agree; when it is not,
this is the delivered enforcement point and is documented as such in ``CLAIMS.json``.
The domain services re-check it server-side, so bypassing the client-side broker does
not grant authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from nightshift.safety_kernel.decision import Decision, allow, refuse
from nightshift.schemas.enums import AgentName, DenialReason, FailureClass, ToolDomain


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    service: str
    domain: ToolDomain
    mutating: bool
    description: str


def _t(name: str, service: str, domain: ToolDomain, mutating: bool, description: str) -> ToolSpec:
    return ToolSpec(name=name, service=service, domain=domain, mutating=mutating, description=description)


TOOL_REGISTRY: dict[str, ToolSpec] = {
    t.name: t
    for t in [
        # Telemetry — read only, always.
        _t("get_freezer_state", "telemetry", ToolDomain.TELEMETRY_READ, False,
           "Current state and temperature for one freezer"),
        _t("get_temperature_window", "telemetry", ToolDomain.TELEMETRY_READ, False,
           "Temperature readings over a time window"),
        _t("get_recent_door_events", "telemetry", ToolDomain.TELEMETRY_READ, False,
           "Door open/close events for one freezer"),
        _t("get_equipment_history", "telemetry", ToolDomain.TELEMETRY_EQUIPMENT_READ, False,
           "Maintenance and fault history for one freezer"),
        _t("get_incident_telemetry_summary", "telemetry", ToolDomain.TELEMETRY_SUMMARY, False,
           "Coarse temperature summary for the incident freezer"),
        _t("get_backup_freezer_state", "telemetry", ToolDomain.TELEMETRY_BACKUP_READ, False,
           "Temperature and capacity headline for qualified backup freezers"),
        _t("get_destination_temperature", "telemetry", ToolDomain.TELEMETRY_DESTINATION_READ, False,
           "Freshest reading for a transfer destination"),

        # Inventory.
        _t("get_container_summary", "inventory", ToolDomain.INVENTORY_SCOPED_READ, False,
           "Container-level record without free-text study notes"),
        _t("list_impacted_containers", "inventory", ToolDomain.INVENTORY_SCOPED_READ, False,
           "Containers held by the failed freezer"),
        _t("get_placement_requirements", "inventory", ToolDomain.INVENTORY_PLACEMENT_VIEW, False,
           "Minimal grouping/volume view needed to place material"),
        _t("get_incident_container_ids", "inventory", ToolDomain.INVENTORY_INCIDENT_READ, False,
           "Container identifiers scoped to one incident"),
        _t("apply_containment_hold", "inventory", ToolDomain.INVENTORY_WRITE, True,
           "Place a containment hold on the failed freezer"),
        _t("get_hold_state", "inventory", ToolDomain.INVENTORY_SCOPED_READ, False,
           "Current containment hold state"),
        _t("get_study_notes", "inventory", ToolDomain.INVENTORY_WRITE, False,
           "Sensitive study notes — deliberately gated behind inventory write authority "
           "so no operational agent can reach it"),

        # Capacity.
        _t("list_qualified_destinations", "capacity", ToolDomain.CAPACITY_READ, False,
           "Backup freezers qualified to receive material"),
        _t("get_capacity", "capacity", ToolDomain.CAPACITY_READ, False,
           "Verified available slots for a destination"),
        _t("reserve_capacity", "capacity", ToolDomain.CAPACITY_WRITE, True,
           "Transactionally reserve slots"),
        _t("release_reservation", "capacity", ToolDomain.CAPACITY_WRITE, True,
           "Release a reservation"),
        _t("get_reservation", "capacity", ToolDomain.CAPACITY_READ, False,
           "Read one reservation"),

        # Facilities / dispatch.
        _t("create_work_order", "facilities", ToolDomain.FACILITIES_WRITE, True,
           "Open a maintenance work order"),
        _t("get_work_order", "facilities", ToolDomain.FACILITIES_READ, False,
           "Read a work order"),
        _t("dispatch_responder", "facilities", ToolDomain.FACILITIES_WRITE, True,
           "Dispatch an on-call responder"),
        _t("get_dispatch_state", "facilities", ToolDomain.FACILITIES_READ, False,
           "Read dispatch state"),
        _t("record_repair_status", "facilities", ToolDomain.FACILITIES_WRITE, True,
           "Record a repair status update"),
        _t("get_responder_roster", "facilities", ToolDomain.FACILITIES_READ, False,
           "On-call roster"),
        _t("send_vendor_message", "facilities", ToolDomain.FACILITIES_WRITE, True,
           "Send sanitized equipment context to the vendor simulation"),

        # Custody.
        _t("record_pickup", "custody", ToolDomain.CUSTODY_WRITE, True,
           "Record a responder pickup scan"),
        _t("record_destination_scan", "custody", ToolDomain.CUSTODY_WRITE, True,
           "Record a destination scan"),
        _t("commit_transfer", "custody", ToolDomain.CUSTODY_WRITE, True,
           "Commit the authoritative location change"),
        _t("get_custody_state", "custody", ToolDomain.CUSTODY_READ, False,
           "Custody state for incident containers"),
        _t("reconcile_incident", "custody", ToolDomain.CUSTODY_READ, False,
           "Compute the reconciliation snapshot"),
        _t("flag_custody_exception", "custody", ToolDomain.CUSTODY_WRITE, True,
           "Flag an unresolved or contradictory movement"),

        # Incident control.
        _t("get_incident", "incident_control", ToolDomain.INCIDENT_READ, False,
           "Incident summary and receipts"),
        _t("get_incident_timeline", "incident_control", ToolDomain.INCIDENT_READ, False,
           "Chronological incident timeline"),
        _t("request_incident_transition", "incident_control", ToolDomain.INCIDENT_TRANSITION, True,
           "Request an incident state transition (the service owns transition truth)"),
        _t("request_incident_close", "incident_control", ToolDomain.INCIDENT_TRANSITION, True,
           "Request closure — refused unless N5 and N6 hold"),
    ]
}


AGENT_TOOL_DOMAINS: dict[AgentName, frozenset[ToolDomain]] = {
    AgentName.COMMANDER: frozenset({
        ToolDomain.TELEMETRY_SUMMARY,
        ToolDomain.INCIDENT_READ,
        ToolDomain.INCIDENT_TRANSITION,
    }),
    AgentName.SIGNAL_INVESTIGATOR: frozenset({
        ToolDomain.TELEMETRY_READ,
        ToolDomain.TELEMETRY_EQUIPMENT_READ,
        ToolDomain.INCIDENT_READ,
    }),
    AgentName.IMPACT_ANALYST: frozenset({
        ToolDomain.TELEMETRY_SUMMARY,
        ToolDomain.INVENTORY_SCOPED_READ,
        ToolDomain.INCIDENT_READ,
    }),
    AgentName.CAPACITY_BROKER: frozenset({
        ToolDomain.TELEMETRY_BACKUP_READ,
        ToolDomain.INVENTORY_PLACEMENT_VIEW,
        ToolDomain.CAPACITY_READ,
        ToolDomain.CAPACITY_WRITE,
        ToolDomain.INCIDENT_READ,
    }),
    AgentName.DISPATCH_AGENT: frozenset({
        ToolDomain.TELEMETRY_EQUIPMENT_READ,
        ToolDomain.FACILITIES_READ,
        ToolDomain.FACILITIES_WRITE,
        ToolDomain.INCIDENT_READ,
    }),
    AgentName.CUSTODY_AGENT: frozenset({
        ToolDomain.TELEMETRY_DESTINATION_READ,
        ToolDomain.INVENTORY_INCIDENT_READ,
        ToolDomain.CAPACITY_READ,
        ToolDomain.CUSTODY_READ,
        ToolDomain.CUSTODY_WRITE,
        ToolDomain.INCIDENT_READ,
    }),

    # Non-agent principals.
    AgentName.INGESTOR: frozenset({
        ToolDomain.TELEMETRY_READ,
        ToolDomain.INVENTORY_WRITE,
        ToolDomain.INCIDENT_READ,
        ToolDomain.INCIDENT_TRANSITION,
    }),
    AgentName.RESPONDER_APP: frozenset({
        ToolDomain.CUSTODY_WRITE,
        ToolDomain.CUSTODY_READ,
        ToolDomain.TELEMETRY_DESTINATION_READ,
        ToolDomain.INVENTORY_INCIDENT_READ,
    }),
    AgentName.DRILL_CONTROLLER: frozenset({
        ToolDomain.INCIDENT_READ,
    }),
}
"""The §11.3 matrix, expressed as authority domains.

Read the table this way:

* Commander gets *summary only* telemetry and no inventory/capacity/facilities/custody
  authority at all — a compromised Commander cannot move anything (threat model §31).
* Signal Investigator sees telemetry and equipment history but never a specimen record.
* Impact Analyst reads scoped inventory but cannot reserve capacity.
* Capacity Broker holds the only capacity-write authority and cannot touch custody.
* Dispatch Agent holds facilities write and has **no** inventory domain whatsoever,
  which is what makes drill D10/D11 a real authorization denial rather than a prompt.
* Custody Agent holds the only custody-write authority and cannot create reservations
  or work orders.
"""


def is_registered_tool(tool_name: str) -> bool:
    return tool_name in TOOL_REGISTRY


def domains_for(agent: AgentName) -> frozenset[ToolDomain]:
    return AGENT_TOOL_DOMAINS.get(agent, frozenset())


def tools_for(agent: AgentName) -> list[str]:
    """Every registered tool ``agent`` may call. Used to build per-agent toolsets."""
    granted = domains_for(agent)
    return sorted(name for name, spec in TOOL_REGISTRY.items() if spec.domain in granted)


def authorize_tool(agent: AgentName | str, tool_name: str) -> Decision:
    """N7. Deny by default: unregistered tool, or identity without the tool's domain."""
    spec = TOOL_REGISTRY.get(tool_name)
    if spec is None:
        return refuse(
            "N7",
            f"tool '{tool_name}' is not registered; unregistered tools are unreachable",
            denial_reason=DenialReason.UNREGISTERED_TOOL,
            failure_class=FailureClass.POLICY_DENIAL,
            detail={"tool": tool_name},
        )

    try:
        principal = AgentName(agent)
    except ValueError:
        return refuse(
            "N7",
            f"unknown calling identity '{agent}'",
            denial_reason=DenialReason.IDENTITY_NOT_PERMITTED,
            failure_class=FailureClass.POLICY_DENIAL,
            detail={"tool": tool_name, "identity": str(agent)},
        )

    granted = domains_for(principal)
    if spec.domain not in granted:
        return refuse(
            "N7",
            f"identity '{principal.value}' does not hold authority domain "
            f"'{spec.domain.value}' required by tool '{tool_name}'",
            denial_reason=DenialReason.IDENTITY_NOT_PERMITTED,
            failure_class=FailureClass.POLICY_DENIAL,
            detail={
                "tool": tool_name,
                "identity": principal.value,
                "required_domain": spec.domain.value,
                "granted_domains": sorted(d.value for d in granted),
                "mutating": spec.mutating,
            },
        )

    return allow({"tool": tool_name, "identity": principal.value, "domain": spec.domain.value})


def permission_matrix() -> dict[str, dict[str, str]]:
    """Human-readable matrix for the fleet page and the SECURITY doc."""
    columns = {
        "telemetry": [
            ToolDomain.TELEMETRY_SUMMARY,
            ToolDomain.TELEMETRY_READ,
            ToolDomain.TELEMETRY_BACKUP_READ,
            ToolDomain.TELEMETRY_DESTINATION_READ,
            ToolDomain.TELEMETRY_EQUIPMENT_READ,
        ],
        "inventory": [
            ToolDomain.INVENTORY_SCOPED_READ,
            ToolDomain.INVENTORY_PLACEMENT_VIEW,
            ToolDomain.INVENTORY_INCIDENT_READ,
            ToolDomain.INVENTORY_WRITE,
        ],
        "capacity": [ToolDomain.CAPACITY_READ, ToolDomain.CAPACITY_WRITE],
        "facilities": [ToolDomain.FACILITIES_READ, ToolDomain.FACILITIES_WRITE],
        "custody": [ToolDomain.CUSTODY_READ, ToolDomain.CUSTODY_WRITE],
    }
    matrix: dict[str, dict[str, str]] = {}
    for agent in AgentName:
        granted = domains_for(agent)
        row: dict[str, str] = {}
        for col, domains in columns.items():
            held = [d.value.split(".", 1)[1] for d in domains if d in granted]
            row[col] = ", ".join(held) if held else "no"
        matrix[agent.value] = row
    return matrix
