"""Facilities / Dispatch Service (PRD §17.4).

Work orders, the responder roster, dispatch, and the vendor channel.

This service holds no inventory authority whatsoever. The vendor message route strips
and validates its payload before anything leaves, so even a Dispatch Agent that has
been talked into exfiltrating specimen data has nothing to send and nowhere to get it.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import Depends
from pydantic import BaseModel, Field

from nightshift.common.clock import now_iso
from nightshift.common.ids import (
    dispatch_action_id,
    opaque_token,
    repair_status_action_id,
    work_order_action_id,
)
from nightshift.common.store import TxnContext
from nightshift.safety_kernel import ActionRequest, KernelState
from nightshift.schemas.core import Dispatch, WorkOrder
from nightshift.schemas.enums import ActionType, FaultClass, ResponderRole, ResponsePhase
from services.common.app import create_app, get_repository, require_tool
from services.common.effects import EffectResult, commit_effect, record_event
from services.common.identity import AgentPrincipal
from services.common.repository import Repository

app = create_app(
    service_name="facilities",
    title="Night Shift — Facilities Service",
    description="Maintenance work orders, responder dispatch, and the vendor channel.",
)

# Patterns that must never appear in outbound vendor traffic. This is a last-line
# deterministic check; Model Armor and semantic policy sit above it, but this one
# cannot be talked out of its opinion.
_FORBIDDEN_IN_VENDOR_MESSAGE = [
    (re.compile(r"\bC-\d{3,}\b"), "container identifier"),
    (re.compile(r"\bSTUDY-[A-Z]+\b"), "study identifier"),
    (re.compile(r"\bspecimen\b", re.I), "specimen reference"),
    (re.compile(r"\bpatient\b", re.I), "patient reference"),
    (re.compile(r"\bowner-[a-z-]+\b"), "study owner reference"),
]


class WorkOrderRequest(BaseModel):
    incident_id: str
    freezer_id: str
    fault_class: FaultClass
    summary: str = Field(max_length=600)
    trace_id: str | None = None


class DispatchRequest(BaseModel):
    incident_id: str
    responder_role: ResponderRole
    response_phase: ResponsePhase
    container_ids: list[str] = Field(default_factory=list)
    trace_id: str | None = None


class RepairStatusRequest(BaseModel):
    incident_id: str
    work_order_id: str
    status: str
    note: str = ""
    trace_id: str | None = None


class VendorMessageRequest(BaseModel):
    incident_id: str
    work_order_id: str
    message: str = Field(max_length=600)
    trace_id: str | None = None


@app.get("/v1/responders")
async def get_responder_roster(
    on_call_only: bool = True,
    _p: AgentPrincipal = Depends(require_tool("get_responder_roster")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    responders = repo.list_responders(**({"on_call": True} if on_call_only else {}))
    return {
        "count": len(responders),
        "responders": [r.model_dump(mode="json") for r in responders],
    }


@app.get("/v1/work-orders/{work_order_id}")
async def get_work_order(
    work_order_id: str,
    incident_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_work_order")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    for wo in repo.list_work_orders(incident_id):
        if wo.id == work_order_id:
            return {"found": True, "work_order": wo.model_dump(mode="json")}
    return {"found": False, "work_order_id": work_order_id}


@app.get("/v1/dispatches")
async def get_dispatch_state(
    incident_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_dispatch_state")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    dispatches = repo.list_dispatches(incident_id)
    return {
        "incident_id": incident_id,
        "count": len(dispatches),
        # The task token is a credential. It is never echoed back through a read route.
        "dispatches": [
            {k: v for k, v in d.model_dump(mode="json").items() if k != "task_token"}
            for d in dispatches
        ],
    }


@app.post("/v1/work-orders")
async def create_work_order(
    body: WorkOrderRequest,
    principal: AgentPrincipal = Depends(require_tool("create_work_order")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Idempotent on (incident, freezer, fault class) — D6's whole point."""
    request = ActionRequest(
        action_id=work_order_action_id(body.incident_id, body.freezer_id, body.fault_class),
        action_type=ActionType.WORK_ORDER_CREATE,
        incident_id=body.incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={"freezer_id": body.freezer_id, "fault_class": body.fault_class.value},
        now=now_iso(),
    )

    def build(ctx: TxnContext, state: KernelState, req: ActionRequest) -> EffectResult:
        wo = WorkOrder(
            id=f"WO-{req.action_id[:12]}",
            action_id=req.action_id,
            incident_id=req.incident_id,
            freezer_id=body.freezer_id,
            fault_class=body.fault_class,
            summary=body.summary,
            created_at=req.now,
        )
        ctx.set("workOrders", wo.id, wo.model_dump(mode="json"))
        return EffectResult(
            effect_ref=wo.id,
            collection="workOrders",
            summary=f"Work order {wo.id} opened on {body.freezer_id} ({body.fault_class.value})",
            evidence_sources=["telemetry:get_equipment_history"],
            detail={"fault_class": body.fault_class.value, "freezer_id": body.freezer_id},
        )

    return commit_effect(repo, request, build, trace_id=body.trace_id).as_dict()


@app.post("/v1/dispatches")
async def dispatch_responder(
    body: DispatchRequest,
    principal: AgentPrincipal = Depends(require_tool("dispatch_responder")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Idempotent on (incident, phase, role)."""
    request = ActionRequest(
        action_id=dispatch_action_id(body.incident_id, body.response_phase, body.responder_role),
        action_type=ActionType.DISPATCH_RESPONDER,
        incident_id=body.incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={
            "responder_role": body.responder_role.value,
            "response_phase": body.response_phase.value,
            "responder_id": _pick_responder(repo, body.responder_role),
        },
        now=now_iso(),
    )

    def build(ctx: TxnContext, state: KernelState, req: ActionRequest) -> EffectResult:
        responder_id = str(req.payload["responder_id"])
        dispatch = Dispatch(
            id=f"DSP-{req.action_id[:12]}",
            action_id=req.action_id,
            incident_id=req.incident_id,
            responder_id=responder_id,
            responder_role=body.responder_role,
            response_phase=body.response_phase,
            task_token=opaque_token(),
            created_at=req.now,
            container_ids=sorted(body.container_ids),
        )
        ctx.set("dispatches", dispatch.id, dispatch.model_dump(mode="json"))
        return EffectResult(
            effect_ref=dispatch.id,
            collection="dispatches",
            summary=(
                f"Dispatched {body.responder_role.value} for {body.response_phase.value} "
                f"({len(body.container_ids)} container(s))"
            ),
            evidence_sources=["facilities:get_responder_roster"],
            detail={
                "responder_id": responder_id,
                "responder_role": body.responder_role.value,
                "response_phase": body.response_phase.value,
                "container_count": len(body.container_ids),
            },
        )

    outcome = commit_effect(repo, request, build, trace_id=body.trace_id)
    payload = outcome.as_dict()
    # The responder link is returned once, to the caller that created the dispatch.
    if outcome.committed and outcome.receipt.effect_ref:
        dispatches = repo.list_dispatches(body.incident_id)
        match = next((d for d in dispatches if d.id == outcome.receipt.effect_ref), None)
        if match is not None:
            payload["responder_path"] = f"/respond/{match.task_token}"
    return payload


def _pick_responder(repo: Repository, role: ResponderRole) -> str:
    """Deterministic selection: first on-call responder holding the role, by id."""
    candidates = sorted(
        (r for r in repo.list_responders() if r.role is role and r.on_call), key=lambda r: r.id
    )
    if not candidates:
        candidates = sorted(
            (r for r in repo.list_responders() if r.role is role), key=lambda r: r.id
        )
    return candidates[0].id if candidates else ""


@app.post("/v1/repair-status")
async def record_repair_status(
    body: RepairStatusRequest,
    principal: AgentPrincipal = Depends(require_tool("record_repair_status")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    request = ActionRequest(
        action_id=repair_status_action_id(body.incident_id, body.work_order_id, body.status),
        action_type=ActionType.REPAIR_STATUS,
        incident_id=body.incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={"work_order_id": body.work_order_id, "status": body.status},
        now=now_iso(),
    )

    def build(ctx: TxnContext, state: KernelState, req: ActionRequest) -> EffectResult:
        wo = state.work_orders.get(body.work_order_id)
        if wo is None:
            raise ValueError(f"work order {body.work_order_id!r} does not exist")
        events = [*wo.repair_events, {"at": req.now, "status": body.status, "note": body.note}]
        status_map = {
            "IN_PROGRESS": "IN_PROGRESS",
            "RESOLVED": "RESOLVED",
            "CANCELLED": "CANCELLED",
        }
        updated = wo.model_copy(
            update={"repair_events": events, "status": status_map.get(body.status, wo.status)}
        )
        ctx.set("workOrders", updated.id, updated.model_dump(mode="json"))
        return EffectResult(
            effect_ref=updated.id,
            collection="workOrders",
            summary=f"Repair status on {updated.id}: {body.status}",
            evidence_sources=["facilities:get_work_order"],
            detail={"status": body.status, "note": body.note},
        )

    return commit_effect(repo, request, build, trace_id=body.trace_id).as_dict()


@app.post("/v1/vendor-messages")
async def send_vendor_message(
    body: VendorMessageRequest,
    principal: AgentPrincipal = Depends(require_tool("send_vendor_message")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Outbound equipment context to the vendor simulation.

    Deterministic egress check: if the message carries anything that looks like study
    or specimen metadata, it does not leave. This is the layer that still holds when
    Model Armor is unavailable (PRD §32.7).
    """
    findings = [
        label for pattern, label in _FORBIDDEN_IN_VENDOR_MESSAGE if pattern.search(body.message)
    ]
    if findings:
        record_event(
            repo,
            body.incident_id,
            kind="security",
            source=principal.identity,
            summary=(
                "Outbound vendor message blocked: it contained " + ", ".join(sorted(set(findings)))
            ),
            detail={"findings": sorted(set(findings)), "layer": "deterministic egress filter"},
            agent=principal.agent,
            trace_id=body.trace_id,
        )
        return {
            "sent": False,
            "blocked": True,
            "layer": "deterministic egress filter",
            "findings": sorted(set(findings)),
            "reason": "vendor messages may carry equipment context only",
        }

    record_event(
        repo,
        body.incident_id,
        kind="tool_call",
        source=principal.identity,
        summary="Sanitized equipment context sent to vendor simulation",
        detail={"work_order_id": body.work_order_id, "characters": len(body.message)},
        agent=principal.agent,
        trace_id=body.trace_id,
    )
    return {"sent": True, "blocked": False, "vendor_ref": f"VND-{body.work_order_id[-8:]}"}
