"""Inventory Service (PRD §17.2).

Holds the specimen hierarchy, the containment hold, and the impact snapshot.

The important design choice is what this service *refuses to return*. There is no route
that hands out unrestricted study metadata to a caller holding only facilities
authority — the sensitive surface sits behind ``inventory.write``, a domain no
operational agent holds. That is why drill D10's poisoned vendor payload cannot succeed
even if every probabilistic layer above it misses.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends
from pydantic import BaseModel, Field

from nightshift.common.canonical import sha256_of
from nightshift.common.clock import now_iso
from nightshift.common.ids import containment_action_id, impact_action_id, release_hold_action_id
from nightshift.common.store import TxnContext
from nightshift.safety_kernel import ActionRequest, KernelState
from nightshift.safety_kernel.preconditions import check_normal_inventory_operation
from nightshift.schemas.core import ContainmentHold, ImpactSnapshot, PlacementGroup
from nightshift.schemas.enums import ActionType, FreezerState
from services.common.app import create_app, get_repository, require_tool
from services.common.effects import EffectResult, commit_effect
from services.common.identity import AgentPrincipal
from services.common.repository import Repository

app = create_app(
    service_name="inventory",
    title="Night Shift — Inventory Service",
    description="Synthetic specimen hierarchy, containment holds, and impact snapshots.",
)


class HoldRequest(BaseModel):
    incident_id: str
    freezer_id: str
    reason: str = ""
    trace_id: str | None = None


class ReleaseHoldRequest(BaseModel):
    incident_id: str
    freezer_id: str
    validation_readings: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str | None = None


class ImpactRequest(BaseModel):
    incident_id: str
    container_ids: list[str]
    inventory_complete: bool
    trace_id: str | None = None


def _container_summary(c: Any) -> dict[str, Any]:
    """Container-level view. Note the absence of any free-text study notes field."""
    return {
        "container_id": c.id,
        "freezer_id": c.freezer_id,
        "slot_id": c.slot_id,
        "kind": c.kind,
        "study_id": c.study_id,
        "priority_class": c.priority_class,
        "specimen_count": c.specimen_count,
        "required_temp_c": c.required_temp_c,
        "custody_state": c.custody_state.value,
        "incident_id": c.incident_id,
    }


@app.get("/v1/containers/{container_id}")
async def get_container_summary(
    container_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_container_summary")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    c = repo.get_container(container_id)
    if c is None:
        return {"container_id": container_id, "known": False}
    return {"known": True, **_container_summary(c)}


@app.get("/v1/freezers/{freezer_id}/impacted")
async def list_impacted_containers(
    freezer_id: str,
    incident_id: str | None = None,
    _p: AgentPrincipal = Depends(require_tool("list_impacted_containers")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    containers = repo.list_containers(freezer_id=freezer_id)
    by_priority: dict[str, int] = {}
    for c in containers:
        key = str(c.priority_class)
        by_priority[key] = by_priority.get(key, 0) + 1
    return {
        "freezer_id": freezer_id,
        "incident_id": incident_id,
        "evaluated_at": now_iso(),
        "enumeration_complete": True,
        "container_count": len(containers),
        "specimen_total": sum(c.specimen_count for c in containers),
        "study_ids": sorted({c.study_id for c in containers}),
        "priority_breakdown": dict(sorted(by_priority.items())),
        "containers": [_container_summary(c) for c in containers],
    }


@app.get("/v1/incidents/{incident_id}/placement-requirements")
async def get_placement_requirements(
    incident_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_placement_requirements")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """The Broker's minimal view: how many slots at what temperature, grouped.

    Study identifiers are hashed to opaque group labels here. The Broker needs to keep
    a study's material together; it does not need to know which study it is.
    """
    impact = repo.get_impact(incident_id)
    if impact is None:
        return {"incident_id": incident_id, "impact_available": False, "groups": []}
    return {
        "incident_id": incident_id,
        "impact_available": True,
        "impact_snapshot_hash": impact.snapshot_hash,
        "groups": [
            {
                "placement_group_id": g.id,
                "priority_class": g.priority_class,
                "required_temp_c": g.required_temp_c,
                "slot_count": g.slot_count,
                "container_count": len(g.container_ids),
            }
            for g in impact.placement_groups
        ],
    }


@app.get("/v1/incidents/{incident_id}/container-ids")
async def get_incident_container_ids(
    incident_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_incident_container_ids")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Identifiers only — the Custody Agent's inventory view."""
    impact = repo.get_impact(incident_id)
    ids = impact.container_ids if impact else [
        c.id for c in repo.list_containers(incident_id=incident_id)
    ]
    return {"incident_id": incident_id, "container_ids": sorted(ids), "count": len(ids)}


@app.get("/v1/holds/{freezer_id}")
async def get_hold_state(
    freezer_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_hold_state")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    hold = repo.get_hold(freezer_id)
    return {
        "freezer_id": freezer_id,
        "hold_active": bool(hold and hold.active),
        "hold": hold.model_dump(mode="json") if hold else None,
        "normal_operations_permitted": check_normal_inventory_operation(
            repo.load_kernel_state(hold.incident_id if hold else ""), freezer_id
        ).allowed,
    }


@app.get("/v1/study-notes/{container_id}")
async def get_study_notes(
    container_id: str,
    _p: AgentPrincipal = Depends(require_tool("get_study_notes")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Sensitive study notes.

    Gated behind ``inventory.write``, which no operational agent holds. It exists so
    the forbidden-tool drill targets a route that genuinely returns something valuable
    rather than a stub — the denial has to be worth something to be worth proving.
    """
    c = repo.get_container(container_id)
    if c is None:
        return {"container_id": container_id, "known": False}
    return {
        "container_id": container_id,
        "known": True,
        "study_id": c.study_id,
        "owner_ref": c.owner_ref,
        "notes": (
            "Synthetic protocol notes for a synthetic study. No real research data is "
            "represented in this fixture."
        ),
    }


@app.post("/v1/holds")
async def apply_containment_hold(
    body: HoldRequest,
    principal: AgentPrincipal = Depends(require_tool("apply_containment_hold")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """N13: freeze normal traffic on the failed unit while the rescue runs."""
    request = ActionRequest(
        action_id=containment_action_id(body.incident_id, body.freezer_id),
        action_type=ActionType.CONTAINMENT_HOLD,
        incident_id=body.incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={"freezer_id": body.freezer_id, "reason": body.reason},
        now=now_iso(),
    )

    def build(ctx: TxnContext, state: KernelState, req: ActionRequest) -> EffectResult:
        hold = ContainmentHold(
            id=f"HOLD-{body.freezer_id}-{req.action_id[:8]}",
            incident_id=req.incident_id,
            freezer_id=body.freezer_id,
            active=True,
            placed_at=req.now,
        )
        ctx.set("holds", body.freezer_id, hold.model_dump(mode="json"))

        freezer = state.freezers.get(body.freezer_id)
        if freezer is not None and freezer.state is not FreezerState.FAILED:
            ctx.set(
                "freezers",
                freezer.id,
                freezer.model_copy(update={"state": FreezerState.FAILED}).model_dump(mode="json"),
            )
        # Claim every container in the failed freezer for this incident so custody and
        # reconciliation are scoped without a second enumeration step.
        for c in state.containers.values():
            if c.freezer_id == body.freezer_id and c.incident_id != req.incident_id:
                ctx.set(
                    "containers",
                    c.id,
                    c.model_copy(update={"incident_id": req.incident_id}).model_dump(mode="json"),
                )
        return EffectResult(
            effect_ref=hold.id,
            collection="holds",
            summary=f"Containment hold placed on {body.freezer_id}",
            evidence_sources=["telemetry:get_freezer_state", "inventory:list_impacted_containers"],
            detail={"freezer_id": body.freezer_id, "reason": body.reason},
        )

    return commit_effect(repo, request, build, trace_id=body.trace_id).as_dict()


@app.post("/v1/holds/{freezer_id}/release")
async def release_containment_hold(
    freezer_id: str,
    body: ReleaseHoldRequest,
    principal: AgentPrincipal = Depends(require_tool("apply_containment_hold")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """D18: release requires a demonstrated recovery window, not a repair claim."""
    request = ActionRequest(
        action_id=release_hold_action_id(body.incident_id, freezer_id),
        action_type=ActionType.RELEASE_HOLD,
        incident_id=body.incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={"freezer_id": freezer_id, "validation_readings": body.validation_readings},
        now=now_iso(),
    )

    def build(ctx: TxnContext, state: KernelState, req: ActionRequest) -> EffectResult:
        hold = state.holds[freezer_id]
        evidence_ref = sha256_of(body.validation_readings)[:16]
        released = hold.model_copy(
            update={"active": False, "released_at": req.now, "release_evidence_ref": evidence_ref}
        )
        ctx.set("holds", freezer_id, released.model_dump(mode="json"))
        freezer = state.freezers.get(freezer_id)
        if freezer is not None:
            ctx.set(
                "freezers",
                freezer_id,
                freezer.model_copy(update={"state": FreezerState.VALIDATED}).model_dump(mode="json"),
            )
        return EffectResult(
            effect_ref=released.id,
            collection="holds",
            summary=f"Containment hold released on {freezer_id} after validated recovery",
            evidence_sources=["telemetry:get_temperature_window"],
            detail={"validation_reading_count": len(body.validation_readings),
                    "release_evidence_ref": evidence_ref},
        )

    return commit_effect(repo, request, build, trace_id=body.trace_id).as_dict()


@app.post("/v1/impact")
async def record_impact_snapshot(
    body: ImpactRequest,
    principal: AgentPrincipal = Depends(require_tool("apply_containment_hold")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Freeze the impact set.

    Placement groups are derived deterministically from (priority class, required
    temperature). The Impact Analyst decides *priority*; the grouping arithmetic that
    reservation IDs depend on is not left to a model, because a differently-grouped
    retry would derive a different action ID and defeat idempotency.
    """
    containers = [c for c in (repo.get_container(cid) for cid in body.container_ids) if c]
    incident = repo.get_incident(body.incident_id)

    buckets: dict[tuple[int, float], list[str]] = {}
    for c in containers:
        buckets.setdefault((c.priority_class, c.required_temp_c), []).append(c.id)

    groups = [
        PlacementGroup(
            id=f"PG-{body.incident_id}-P{priority}-T{abs(int(temp))}",
            incident_id=body.incident_id,
            priority_class=priority,
            required_temp_c=temp,
            container_ids=sorted(ids),
            slot_count=len(ids),
        )
        for (priority, temp), ids in sorted(buckets.items())
    ]
    priority_breakdown: dict[str, int] = {}
    for c in containers:
        key = str(c.priority_class)
        priority_breakdown[key] = priority_breakdown.get(key, 0) + 1

    snapshot_body = {
        "incident_id": body.incident_id,
        "container_ids": sorted(c.id for c in containers),
        "specimen_total": sum(c.specimen_count for c in containers),
        "groups": [g.model_dump(mode="json") for g in groups],
    }
    snapshot_hash = sha256_of(snapshot_body)

    request = ActionRequest(
        action_id=impact_action_id(body.incident_id, snapshot_hash),
        action_type=ActionType.IMPACT_SNAPSHOT,
        incident_id=body.incident_id,
        actor_identity=principal.identity,
        requested_by_agent=principal.agent,
        requested_by_agent_revision=principal.revision,
        payload={
            "container_ids": [c.id for c in containers],
            "inventory_complete": body.inventory_complete,
        },
        now=now_iso(),
    )

    def build(ctx: TxnContext, state: KernelState, req: ActionRequest) -> EffectResult:
        snapshot = ImpactSnapshot(
            id=f"IMP-{snapshot_hash[:12]}",
            incident_id=req.incident_id,
            created_at=req.now,
            freezer_id=incident.failed_freezer_id if incident else "",
            container_ids=[c.id for c in containers],
            specimen_total=sum(c.specimen_count for c in containers),
            study_ids=sorted({c.study_id for c in containers}),
            priority_breakdown=priority_breakdown,
            placement_groups=groups,
            snapshot_hash=snapshot_hash,
        )
        ctx.set("impactSnapshots", snapshot.id, snapshot.model_dump(mode="json"))
        if incident is not None:
            ctx.set(
                "incidents",
                incident.id,
                incident.model_copy(
                    update={
                        "impact_snapshot_hash": snapshot_hash,
                        "impact_snapshot_id": snapshot.id,
                        "unresolved_count": len(containers),
                        "last_evidence_at": req.now,
                    }
                ).model_dump(mode="json"),
            )
        return EffectResult(
            effect_ref=snapshot.id,
            collection="impactSnapshots",
            summary=(
                f"Impact snapshot: {len(containers)} container(s), "
                f"{snapshot.specimen_total} specimen record(s), {len(groups)} placement group(s)"
            ),
            evidence_sources=["inventory:list_impacted_containers"],
            detail={
                "snapshot_hash": snapshot_hash,
                "container_count": len(containers),
                "specimen_total": snapshot.specimen_total,
                "placement_groups": [g.id for g in groups],
            },
        )

    return commit_effect(repo, request, build, trace_id=body.trace_id).as_dict()
