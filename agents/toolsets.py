"""Per-agent ADK toolsets.

An agent's toolset is derived from the §11.3 matrix, so an agent literally cannot see a
tool it has no authority for. That is the first of three layers: the tool is absent from
its schema, the broker would refuse the call, and the service would refuse it again.

Every function here is a thin shim over ``ToolBroker.call``. The docstrings matter —
they become the tool descriptions the model reads — so they say what the tool returns
*and* what the caller must do with a refusal.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nightshift.safety_kernel.authority import tools_for
from nightshift.schemas.enums import AgentName, FaultClass, ResponderRole, ResponsePhase
from services.gateway.broker import BrokerDenied, ToolBroker
from services.gateway.transport import TransportError


def _wrap(broker: ToolBroker, agent: AgentName, tool_name: str,
          payload_fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def invoke(**kwargs: Any) -> dict[str, Any]:
        try:
            return broker.call(agent, tool_name, payload_fn(**kwargs))
        except BrokerDenied as denied:
            # A denial is a normal, informative outcome the agent must reason about.
            return {
                "denied": True,
                "tool": tool_name,
                "reason": denied.decision.reason,
                "invariant": denied.decision.invariant,
                "denial_reason": (
                    denied.decision.denial_reason.value if denied.decision.denial_reason else None
                ),
                "guidance": (
                    "You do not hold authority for this tool. Do not retry it. "
                    "Escalate or use a tool within your domain."
                ),
            }
        except TransportError as exc:
            return {
                "unavailable": True,
                "tool": tool_name,
                "reason": str(exc),
                "guidance": (
                    "This is an infrastructure failure, not a refusal. The action may or "
                    "may not have committed. Re-read authoritative state before deciding; "
                    "retrying the same request is safe because it is idempotent."
                ),
            }

    return invoke


def build_toolset(broker: ToolBroker, agent: AgentName, incident_id: str) -> list[Callable[..., Any]]:
    """Build the callable tool list for ``agent`` on ``incident_id``."""
    allowed = set(tools_for(agent))
    tools: list[Callable[..., Any]] = []

    def add(name: str, fn: Callable[..., Any]) -> None:
        if name in allowed:
            fn.__name__ = name
            tools.append(fn)

    # ---- telemetry -----------------------------------------------------------------

    def get_freezer_state(freezer_id: str) -> dict:
        """Current authoritative state and temperature for one freezer.

        Returns current_temp_c, setpoint_c, state, last_reading_at and reading_age_s.
        """
        return _wrap(broker, agent, "get_freezer_state",
                     lambda: {"freezer_id": freezer_id})()

    def get_temperature_window(freezer_id: str, minutes: int = 120) -> dict:
        """Temperature readings over a window, with the sustained-warming verdict.

        `sustained_warming_confirmed` is computed deterministically. Explain it; do not
        recompute or dispute it.
        """
        return _wrap(broker, agent, "get_temperature_window",
                     lambda: {"freezer_id": freezer_id, "minutes": minutes})()

    def get_recent_door_events(freezer_id: str, hours: int = 6) -> dict:
        """Door open/close events, with total open seconds over the window."""
        return _wrap(broker, agent, "get_recent_door_events",
                     lambda: {"freezer_id": freezer_id, "hours": hours})()

    def get_equipment_history(freezer_id: str) -> dict:
        """Model, zone, and maintenance history. Contains no specimen or study data."""
        return _wrap(broker, agent, "get_equipment_history",
                     lambda: {"freezer_id": freezer_id})()

    def get_incident_telemetry_summary() -> dict:
        """Coarse temperature summary for this incident's freezer. No reading series."""
        return _wrap(broker, agent, "get_incident_telemetry_summary",
                     lambda: {"incident_id": incident_id})()

    def get_backup_freezer_state() -> dict:
        """Temperature and free-slot headline for every backup-qualified freezer."""
        return _wrap(broker, agent, "get_backup_freezer_state", lambda: {})()

    def get_destination_temperature(freezer_id: str) -> dict:
        """Freshest destination reading plus the freshness verdict.

        `fresh_and_in_bounds` false means a custody commit there will be refused.
        """
        return _wrap(broker, agent, "get_destination_temperature",
                     lambda: {"freezer_id": freezer_id})()

    add("get_freezer_state", get_freezer_state)
    add("get_temperature_window", get_temperature_window)
    add("get_recent_door_events", get_recent_door_events)
    add("get_equipment_history", get_equipment_history)
    add("get_incident_telemetry_summary", get_incident_telemetry_summary)
    add("get_backup_freezer_state", get_backup_freezer_state)
    add("get_destination_temperature", get_destination_temperature)

    # ---- inventory -----------------------------------------------------------------

    def get_container_summary(container_id: str) -> dict:
        """Container-level record: study, priority class, specimen count, custody state."""
        return _wrap(broker, agent, "get_container_summary",
                     lambda: {"container_id": container_id})()

    def list_impacted_containers(freezer_id: str) -> dict:
        """Every container held by a freezer, with priority breakdown and study ids.

        `enumeration_complete` false means the read was partial — carry that through to
        your `inventory_complete` output field.
        """
        return _wrap(broker, agent, "list_impacted_containers",
                     lambda: {"freezer_id": freezer_id, "incident_id": incident_id})()

    def get_placement_requirements() -> dict:
        """Placement groups for this incident: slot counts and required temperatures."""
        return _wrap(broker, agent, "get_placement_requirements",
                     lambda: {"incident_id": incident_id})()

    def get_incident_container_ids() -> dict:
        """Container identifiers scoped to this incident. Identifiers only."""
        return _wrap(broker, agent, "get_incident_container_ids",
                     lambda: {"incident_id": incident_id})()

    def get_hold_state(freezer_id: str) -> dict:
        """Whether a containment hold is active, and whether normal ops are permitted."""
        return _wrap(broker, agent, "get_hold_state", lambda: {"freezer_id": freezer_id})()

    add("get_container_summary", get_container_summary)
    add("list_impacted_containers", list_impacted_containers)
    add("get_placement_requirements", get_placement_requirements)
    add("get_incident_container_ids", get_incident_container_ids)
    add("get_hold_state", get_hold_state)

    # ---- capacity ------------------------------------------------------------------

    def list_qualified_destinations(required_temp_c: float = -80.0) -> dict:
        """Backup freezers with eligibility already decided.

        Each entry carries `eligible` and `ineligible_reasons`. An ineligible freezer is
        not a destination no matter how many free slots it reports.
        """
        return _wrap(broker, agent, "list_qualified_destinations",
                     lambda: {"incident_id": incident_id,
                              "required_temp_c": required_temp_c})()

    def get_capacity(freezer_id: str) -> dict:
        """Verified available slots and how many are already reserved."""
        return _wrap(broker, agent, "get_capacity", lambda: {"freezer_id": freezer_id})()

    def get_reservation(reservation_id: str) -> dict:
        """Read one reservation and its current state."""
        return _wrap(broker, agent, "get_reservation",
                     lambda: {"reservation_id": reservation_id})()

    def reserve_capacity(destination_freezer_id: str, placement_group_id: str,
                         slots: int) -> dict:
        """Reserve slots for a placement group. Returns a receipt.

        Idempotent on (incident, destination, placement group): calling again returns
        the same receipt with duplicate_returned true rather than reserving twice.
        A REFUSED receipt carries the real capacity numbers in decision.detail.
        """
        return _wrap(broker, agent, "reserve_capacity",
                     lambda: {"incident_id": incident_id,
                              "destination_freezer_id": destination_freezer_id,
                              "placement_group_id": placement_group_id,
                              "slots": slots,
                              "evidence_sources": ["capacity:get_capacity",
                                                   "telemetry:get_backup_freezer_state"]})()

    def release_reservation(reservation_id: str, reason: str) -> dict:
        """Release a reservation you no longer need, freeing its slots."""
        return _wrap(broker, agent, "release_reservation",
                     lambda: {"incident_id": incident_id, "reservation_id": reservation_id,
                              "reason": reason})()

    add("list_qualified_destinations", list_qualified_destinations)
    add("get_capacity", get_capacity)
    add("get_reservation", get_reservation)
    add("reserve_capacity", reserve_capacity)
    add("release_reservation", release_reservation)

    # ---- facilities ----------------------------------------------------------------

    def get_responder_roster(on_call_only: bool = True) -> dict:
        """Responders and their roles. Use to choose a role, not a named person."""
        return _wrap(broker, agent, "get_responder_roster",
                     lambda: {"on_call_only": on_call_only})()

    def get_work_order(work_order_id: str) -> dict:
        """Read a work order and its repair events."""
        return _wrap(broker, agent, "get_work_order",
                     lambda: {"work_order_id": work_order_id, "incident_id": incident_id})()

    def get_dispatch_state() -> dict:
        """Dispatches raised for this incident."""
        return _wrap(broker, agent, "get_dispatch_state",
                     lambda: {"incident_id": incident_id})()

    def create_work_order(freezer_id: str, fault_class: str, summary: str) -> dict:
        """Open a maintenance work order. Returns a receipt.

        fault_class is one of COMPRESSOR_FAILURE, DOOR_SEAL, CONTROLLER_FAULT,
        POWER_LOSS, UNKNOWN. Idempotent on (incident, freezer, fault class).
        """
        return _wrap(broker, agent, "create_work_order",
                     lambda: {"incident_id": incident_id, "freezer_id": freezer_id,
                              "fault_class": _enum(FaultClass, fault_class),
                              "summary": summary})()

    def dispatch_responder(responder_role: str, response_phase: str,
                           container_ids: list[str] | None = None) -> dict:
        """Dispatch an on-call responder. Returns a receipt.

        responder_role: LAB_TECH, FACILITIES_TECH, ONCALL_MANAGER, VENDOR_ENGINEER.
        response_phase: INITIAL_ASSESSMENT, TRANSFER, REPAIR, VALIDATION.
        Idempotent on (incident, phase, role).
        """
        return _wrap(broker, agent, "dispatch_responder",
                     lambda: {"incident_id": incident_id,
                              "responder_role": _enum(ResponderRole, responder_role),
                              "response_phase": _enum(ResponsePhase, response_phase),
                              "container_ids": container_ids or []})()

    def record_repair_status(work_order_id: str, status: str, note: str = "") -> dict:
        """Record a repair status update: IN_PROGRESS, RESOLVED, or CANCELLED."""
        return _wrap(broker, agent, "record_repair_status",
                     lambda: {"incident_id": incident_id, "work_order_id": work_order_id,
                              "status": status, "note": note})()

    def send_vendor_message(work_order_id: str, message: str) -> dict:
        """Send equipment context to the vendor. Leaves the building.

        Equipment only. A message containing container ids, study names, or specimen
        references is blocked and recorded as a security event.
        """
        return _wrap(broker, agent, "send_vendor_message",
                     lambda: {"incident_id": incident_id, "work_order_id": work_order_id,
                              "message": message})()

    add("get_responder_roster", get_responder_roster)
    add("get_work_order", get_work_order)
    add("get_dispatch_state", get_dispatch_state)
    add("create_work_order", create_work_order)
    add("dispatch_responder", dispatch_responder)
    add("record_repair_status", record_repair_status)
    add("send_vendor_message", send_vendor_message)

    # ---- custody -------------------------------------------------------------------

    def get_custody_state() -> dict:
        """Custody state for every container in this incident, plus transfer records."""
        return _wrap(broker, agent, "get_custody_state",
                     lambda: {"incident_id": incident_id})()

    def reconcile_incident() -> dict:
        """Deterministic reconciliation: committed, quarantined, unresolved, in flight.

        `complete` false means the incident cannot close. Read this before requesting
        closure rather than requesting closure to find out.
        """
        return _wrap(broker, agent, "reconcile_incident",
                     lambda: {"incident_id": incident_id})()

    def commit_transfer(container_id: str) -> dict:
        """Commit the authoritative location change for one container.

        Refused unless the container belongs to this incident, an active reservation
        covers the destination, both scans exist, and destination temperature is fresh
        and in bounds. The refusal reason names which one failed.
        """
        return _wrap(broker, agent, "commit_transfer",
                     lambda: {"incident_id": incident_id, "container_id": container_id})()

    def commit_ready_transfers(limit: int = 60) -> dict:
        """Commit every container that is scanned in and has complete evidence.

        This is the normal path when a responder has just scanned in a batch. Each
        container is validated individually — the response lists exactly which ones
        committed and, for any that were refused, which invariant refused it and why.
        A refusal inside a batch is information to act on, not a failure of the batch.
        """
        return _wrap(broker, agent, "commit_ready_transfers",
                     lambda: {"incident_id": incident_id, "limit": limit})()

    def flag_custody_exception(container_id: str, reason: str,
                               disposition: str = "UNRESOLVED") -> dict:
        """Flag an unresolved or contradictory movement.

        disposition UNRESOLVED keeps the incident open. QUARANTINED is a terminal
        disposition for material that cannot safely continue.
        """
        return _wrap(broker, agent, "flag_custody_exception",
                     lambda: {"incident_id": incident_id, "container_id": container_id,
                              "reason": reason, "disposition": disposition})()

    add("get_custody_state", get_custody_state)
    add("reconcile_incident", reconcile_incident)
    add("commit_transfer", commit_transfer)
    add("commit_ready_transfers", commit_ready_transfers)
    add("flag_custody_exception", flag_custody_exception)

    # ---- incident control -----------------------------------------------------------

    def get_incident() -> dict:
        """Incident record, reconciliation summary, and the next supported state."""
        return _wrap(broker, agent, "get_incident", lambda: {"incident_id": incident_id})()

    def get_incident_timeline() -> dict:
        """Chronological incident timeline: decisions, receipts, refusals, security events."""
        return _wrap(broker, agent, "get_incident_timeline",
                     lambda: {"incident_id": incident_id})()

    def request_incident_transition(to_state: str, reason: str) -> dict:
        """Request an incident state transition. The service decides whether it is legal."""
        return _wrap(broker, agent, "request_incident_transition",
                     lambda: {"incident_id": incident_id, "to_state": to_state,
                              "reason": reason})()

    def request_incident_close(reason: str) -> dict:
        """Request closure. Refused unless every container is reconciled and the hold released."""
        return _wrap(broker, agent, "request_incident_close",
                     lambda: {"incident_id": incident_id, "reason": reason})()

    add("get_incident", get_incident)
    add("get_incident_timeline", get_incident_timeline)
    add("request_incident_transition", request_incident_transition)
    add("request_incident_close", request_incident_close)

    return tools


def _enum(enum_cls: Any, raw: str) -> str:
    """Coerce a model-supplied string onto the enum, failing loudly if it is not one."""
    try:
        return enum_cls(raw).value  # type: ignore[no-any-return]
    except ValueError:
        upper = str(raw).upper().replace(" ", "_").replace("-", "_")
        return enum_cls(upper).value  # type: ignore[no-any-return]
