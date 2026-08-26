"""Incident Control Service (PRD §17.6).

Owns the incident state machine and the action ledger.

The Commander may *request* a transition. This service decides whether the evidence
supports it. That separation is the whole reason a compromised or confused Commander
cannot walk an incident to CLOSED.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends
from pydantic import BaseModel

from nightshift.common.clock import now_iso
from nightshift.common.ids import close_action_id, dedupe_key, event_id, transition_action_id
from nightshift.common.store import TxnContext
from nightshift.safety_kernel import ActionRequest, KernelState, reconciliation_snapshot
from nightshift.safety_kernel.transitions import can_transition_incident, next_natural_state
from nightshift.schemas.core import Incident, StateTransition
from nightshift.schemas.enums import ActionType, IncidentState, Severity
from services.common.app import create_app, get_repository, require_tool
from services.common.effects import EffectResult, commit_effect
from services.common.identity import AgentPrincipal
from services.common.repository import Repository

app = create_app(
    service_name="incident_control",
    title="Night Shift — Incident Control Service",
    description="Incident state machine, transition guards, and the action ledger.",
)


class TransitionRequest(BaseModel):
    incident_id: str
    to_state: IncidentState
    reason: str = ""
    source_event_id: str | None = None
    trace_id: str | None = None


class CloseRequest(BaseModel):
    incident_id: str
    reason: str = ""
    trace_id: str | None = None


class OpenIncidentRequest(BaseModel):
    """Used by the ingestor, not by an agent."""

    site_id: str
    freezer_id: str
    window_key: str
    severity: Severity = Severity.SEV2
    source_event_id: str
    namespace: str = "demo"
    trace_id: str | None = None


@app.get("/v1/incidents/{incident_id}")
async def get_incident(
    incident_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_incident")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    incident = repo.get_incident(incident_id)
    if incident is None:
        return {"incident_id": incident_id, "known": False}
    state = repo.load_kernel_state(incident_id)
    snap = reconciliation_snapshot(state)
    return {
        "known": True,
        "incident": incident.model_dump(mode="json"),
        "reconciliation": snap.as_dict(),
        "reconciliation_hash": snap.snapshot_hash,
        "receipt_count": len(state.receipts),
        "next_supported_state": (ns.value if (ns := next_natural_state(state)) else None),
        "evaluated_at": now_iso(),
    }


@app.get("/v1/incidents/{incident_id}/timeline")
async def get_incident_timeline(
    incident_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_incident_timeline")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    events = repo.list_events(incident_id)
    return {
        "incident_id": incident_id,
        "count": len(events),
        "events": [e.model_dump(mode="json") for e in events],
    }


@app.post("/v1/incidents/{incident_id}/transitions")
async def request_incident_transition(
    incident_id: str,
    body: TransitionRequest,
    principal: AgentPrincipal = Depends(require_tool("request_incident_transition")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    cause = body.source_event_id or body.reason or body.to_state.value
    request = ActionRequest(
        action_id=transition_action_id(incident_id, body.to_state.value, cause),
        action_type=ActionType.INCIDENT_TRANSITION,
        incident_id=incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={"to_state": body.to_state.value, "reason": body.reason},
        now=now_iso(),
    )

    def build(ctx: TxnContext, state: KernelState, req: ActionRequest) -> EffectResult:
        incident = state.incident
        if incident is None:
            raise ValueError(f"incident {incident_id!r} does not exist")
        transition = StateTransition(
            from_state=incident.state,
            to_state=body.to_state,
            at=req.now,
            source_event_id=body.source_event_id,
            source_action_id=req.action_id,
            reason=body.reason or "requested transition",
        )
        updated = incident.model_copy(
            update={
                "state": body.to_state,
                "transitions": [*incident.transitions, transition],
                "last_evidence_at": req.now,
                "unresolved_count": len(state.unresolved_container_ids()),
            }
        )
        ctx.set("incidents", updated.id, updated.model_dump(mode="json"))
        return EffectResult(
            effect_ref=updated.id,
            collection="incidents",
            summary=f"Incident {incident.state.value} -> {body.to_state.value}",
            evidence_sources=["incident_control:get_incident"],
            detail={"from": incident.state.value, "to": body.to_state.value, "reason": body.reason},
        )

    return commit_effect(repo, request, build, trace_id=body.trace_id).as_dict()


@app.post("/v1/incidents/{incident_id}/close")
async def request_incident_close(
    incident_id: str,
    body: CloseRequest,
    principal: AgentPrincipal = Depends(require_tool("request_incident_close")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Closure. Refused unless N5 and N6 both hold against the current snapshot."""
    state = repo.load_kernel_state(incident_id)
    snap = reconciliation_snapshot(state)

    request = ActionRequest(
        action_id=close_action_id(incident_id, snap.snapshot_hash),
        action_type=ActionType.INCIDENT_CLOSE,
        incident_id=incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={"reason": body.reason},
        now=now_iso(),
    )

    def build(ctx: TxnContext, kstate: KernelState, req: ActionRequest) -> EffectResult:
        incident = kstate.incident
        if incident is None:
            raise ValueError(f"incident {incident_id!r} does not exist")
        transition = StateTransition(
            from_state=incident.state,
            to_state=IncidentState.CLOSED,
            at=req.now,
            source_action_id=req.action_id,
            reason=body.reason or "all impacted containers reconciled",
        )
        updated = incident.model_copy(
            update={
                "state": IncidentState.CLOSED,
                "closed_at": req.now,
                "transitions": [*incident.transitions, transition],
                "last_evidence_at": req.now,
                "unresolved_count": 0,
            }
        )
        ctx.set("incidents", updated.id, updated.model_dump(mode="json"))
        return EffectResult(
            effect_ref=updated.id,
            collection="incidents",
            summary=(
                f"Incident closed: {snap.total} container(s) reconciled "
                f"({len(snap.committed)} committed, {len(snap.quarantined)} quarantined)"
            ),
            evidence_sources=["custody:reconcile_incident", "incident_control:get_incident"],
            detail={"reconciliation": snap.as_dict(), "reconciliation_hash": snap.snapshot_hash},
        )

    return commit_effect(repo, request, build, trace_id=body.trace_id).as_dict()


@app.post("/v1/incidents")
async def open_incident(
    body: OpenIncidentRequest,
    principal: AgentPrincipal = Depends(require_tool("request_incident_transition")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Open or join an incident for a sensor event.

    D3 lives here. The dedupe key is derived from (site, freezer, window), not from the
    Pub/Sub message id, so the *same real-world condition* delivered twice — even under
    two different message ids — joins the existing incident instead of opening a second.
    """
    key = dedupe_key(body.site_id, body.freezer_id, body.window_key)
    existing = [i for i in repo.list_incidents(dedupe_key=key)]
    if existing:
        incident = existing[0]
        if body.source_event_id not in incident.source_event_ids:
            repo.put(
                "incidents",
                incident.id,
                incident.model_copy(
                    update={
                        "source_event_ids": [*incident.source_event_ids, body.source_event_id],
                        "last_evidence_at": now_iso(),
                    }
                ),
            )
        return {
            "incident_id": incident.id,
            "created": False,
            "joined_existing": True,
            "dedupe_key": key,
            "state": incident.state.value,
        }

    now = now_iso()
    incident = Incident(
        id=f"INC-{key[:10].upper()}",
        site_id=body.site_id,
        failed_freezer_id=body.freezer_id,
        state=IncidentState.OBSERVING,
        severity=body.severity,
        opened_at=now,
        last_evidence_at=now,
        namespace=body.namespace,
        source_event_ids=[body.source_event_id],
        dedupe_key=key,
        trace_root_id=body.trace_id,
    )
    repo.put("incidents", incident.id, incident)
    from services.common.effects import record_event

    record_event(
        repo,
        incident.id,
        kind="sensor",
        source="incident-ingestor",
        summary=f"Incident opened on {body.freezer_id} from sensor evidence",
        detail={
            "dedupe_key": key,
            "source_event_id": body.source_event_id,
            "window_key": body.window_key,
        },
        trace_id=body.trace_id,
        occurred_at=now,
    )
    return {
        "incident_id": incident.id,
        "created": True,
        "joined_existing": False,
        "dedupe_key": key,
        "state": incident.state.value,
    }


@app.get("/v1/incidents/{incident_id}/can-transition/{to_state}")
async def can_transition(
    incident_id: str,
    to_state: IncidentState,
    _p: AgentPrincipal = Depends(require_tool("get_incident")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Dry-run guard. Lets the Commander ask before it requests."""
    state = repo.load_kernel_state(incident_id)
    return can_transition_incident(state, to_state).as_dict()


__all__ = ["app", "event_id"]
