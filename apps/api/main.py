"""Public BFF.

Everything a judge can reach without credentials, plus the responder flow. Two rules
shape it:

* **Read-only by default.** The only writes are responder scans, which are gated on an
  unguessable dispatch task token, and bounded demo drills.
* **No credentials, no secrets, no operational namespaces.** Demo and drill namespaces
  only, and task tokens are never echoed back through a read route.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from nightshift.common import otel
from nightshift.common.clock import age_seconds, now_iso
from nightshift.common.config import get_settings
from nightshift.common.skills import load_skills
from nightshift.safety_kernel.authority import (
    AGENT_TOOL_DOMAINS,
    TOOL_REGISTRY,
    permission_matrix,
    tools_for,
)
from nightshift.safety_kernel.invariants import check_all_invariants
from nightshift.safety_kernel.world import reconciliation_snapshot
from nightshift.schemas.enums import AgentName
from nightshift.verify.verifier import verify_manifest
from services.common.repository import Repository

log = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title="Night Shift — Public API",
    description=(
        "Read-only proof surface for the Night Shift demo. All data is synthetic and "
        "all field events are simulated."
    ),
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_repos: dict[str, Repository] = {}

_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
_MAX_CACHED_REPOS = 8


def repo(namespace: str | None = None) -> Repository:
    """Open a repository for a demo namespace.

    The namespace arrives from an unauthenticated query string, and it is interpolated
    into a Firestore collection prefix. Anything outside the pattern is rejected at the
    edge with a 400 rather than allowed to surface as a 500 from the Firestore client,
    and the cache is bounded so a caller cannot grow it one namespace at a time.
    """
    ns = namespace or settings.namespace
    if not _NAMESPACE_PATTERN.match(ns):
        raise HTTPException(
            status_code=400,
            detail={"error": "namespace must match [a-z0-9][a-z0-9-]{0,30}"},
        )
    if ns not in _repos:
        if len(_repos) >= _MAX_CACHED_REPOS:
            _repos.pop(next(iter(_repos)))
        created = Repository.create(
            settings.store_backend,
            project=settings.project_id,
            database=settings.firestore_database,
            namespace=ns,
        )
        if settings.store_backend == "memory":
            _seed_memory_estate(created)
        _repos[ns] = created
    return _repos[ns]


def _seed_memory_estate(repository: Repository) -> None:
    """Give the in-memory backend the fixture estate.

    The memory store starts empty by definition, so ``make run-local`` served a console
    with no freezers, no capacity, and no estate to reason about — every judge-path
    screen rendered its own empty state and the browser suite had nothing to assert
    against. Seeding the same synthetic estate the drills use makes the local stack show
    the real product.

    Firestore is never touched here: a persistent backend carries its own state, and
    silently writing fixture data into it would be indistinguishable from a real estate.
    """
    from fixtures.estate import build_estate, seed_repository

    seed_repository(repository, build_estate())


# --------------------------------------------------------------------------------------
# Abuse control
# --------------------------------------------------------------------------------------


class RateLimiter:
    """Bounded demo-drill creation.

    The client bucket is a salted hash of the source address, never the address itself,
    and it is held in memory only for the length of the window (PRD §27).
    """

    def __init__(self, per_hour: int = 6, max_concurrent: int = 3) -> None:
        self.per_hour = per_hour
        self.max_concurrent = max_concurrent
        self._buckets: dict[str, list[float]] = {}
        self._running = 0

    def bucket_for(self, request: Request) -> str:
        import hashlib

        raw = (request.client.host if request.client else "unknown") + settings.agent_shared_secret
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def check(self, bucket: str) -> tuple[bool, str]:
        now = time.time()
        hits = [t for t in self._buckets.get(bucket, []) if now - t < 3600]
        self._buckets[bucket] = hits
        if self._running >= self.max_concurrent:
            return False, f"at most {self.max_concurrent} demo drills run concurrently"
        if len(hits) >= self.per_hour:
            return False, f"at most {self.per_hour} demo drills per hour per client"
        return True, ""

    def acquire(self, bucket: str) -> None:
        self._buckets.setdefault(bucket, []).append(time.time())
        self._running += 1

    def release(self) -> None:
        self._running = max(0, self._running - 1)


limiter = RateLimiter()


# --------------------------------------------------------------------------------------
# Health and metadata
# --------------------------------------------------------------------------------------


@app.get("/healthz", include_in_schema=False)
@app.get("/api/healthz", include_in_schema=False)
async def healthz() -> dict[str, Any]:
    """Liveness plus the identifying facts a judge would otherwise have to infer.

    Registered twice on purpose. Google's front end answers ``/healthz`` itself with an
    HTML 404 before the request reaches the container, so the path the deploy script
    used to print was never servable. ``/api/healthz`` reaches the app, and it is also
    the path that works through the web app's ``/api`` proxy.
    """
    return {
        "service": "bff",
        "status": "ok",
        "store": repo().store.backend,
        "namespace": settings.namespace,
        "env": settings.deployment_env,
        "commit": settings.source_commit,
        "model": settings.model_id,
    }


@app.get("/api/meta")
async def meta() -> dict[str, Any]:
    """Everything the UI needs to label the demo honestly."""
    from google.adk.version import __version__ as adk_version

    return {
        "synthetic": True,
        "simulated_field_events": True,
        "disclaimer": (
            "All estate, specimen, and responder data is synthetic. Physical responder "
            "movements are simulated; no real biobank samples were moved."
        ),
        "model_id": settings.model_id,
        "model_location": settings.model_location,
        "adk_version": adk_version,
        "region": settings.region,
        "deployment_env": settings.deployment_env,
        "source_commit": settings.source_commit,
        "store_backend": repo().store.backend,
        "signer_backend": "cloud-kms" if settings.kms_key else "local-ec-p256",
        "model_armor_configured": bool(settings.model_armor_template),
        "tracing": otel.tracing_status(),
        "evaluated_at": now_iso(),
    }


# --------------------------------------------------------------------------------------
# Operations overview
# --------------------------------------------------------------------------------------


@app.get("/api/overview")
async def overview(namespace: str | None = None) -> dict[str, Any]:
    r = repo(namespace)
    incidents = r.list_incidents()
    freezers = r.list_freezers()
    now = now_iso()

    active = [i for i in incidents if i.state.value not in {"CLOSED", "ABORTED_SAFE"}]
    reservations = r.list_reservations()
    held = sum(res.held_slots for res in reservations if res.state.value in {"ACTIVE", "PROPOSED"})

    return {
        "evaluated_at": now,
        "active_incidents": len(active),
        "total_incidents": len(incidents),
        "freezers": [
            {
                "freezer_id": f.id,
                "label": f.label,
                "zone": f.zone,
                "state": f.state.value,
                "current_temp_c": f.current_temp_c,
                "setpoint_c": f.setpoint_c,
                "alarm_high_c": f.alarm_high_c,
                "above_alarm": f.current_temp_c > f.alarm_high_c,
                "total_slots": f.total_slots,
                "occupied_slots": f.occupied_slots,
                "free_slots": f.free_slots,
                "is_backup_qualified": f.is_backup_qualified,
                "reading_age_s": round(age_seconds(f.last_reading_at, now), 1),
                "hold_active": bool((h := r.get_hold(f.id)) and h.active),
            }
            for f in sorted(freezers, key=lambda x: x.id)
        ],
        "capacity": {
            "total_slots": sum(f.total_slots for f in freezers),
            "occupied_slots": sum(f.occupied_slots for f in freezers),
            "reserved_slots": held,
            "backup_free_slots": sum(f.free_slots for f in freezers if f.is_backup_qualified),
        },
        "incidents": [
            _incident_card(r, i) for i in sorted(incidents, key=lambda x: x.opened_at, reverse=True)
        ],
    }


def _incident_card(r: Repository, incident: Any) -> dict[str, Any]:
    state = r.load_kernel_state(incident.id)
    recon = reconciliation_snapshot(state)
    return {
        "incident_id": incident.id,
        "state": incident.state.value,
        "severity": incident.severity.value,
        "failed_freezer_id": incident.failed_freezer_id,
        "opened_at": incident.opened_at,
        "closed_at": incident.closed_at,
        "impacted_containers": recon.total,
        "committed": len(recon.committed),
        "unresolved": len(recon.unresolved),
        "in_flight": len(recon.in_flight),
        "complete": recon.complete,
    }


# --------------------------------------------------------------------------------------
# Incident detail
# --------------------------------------------------------------------------------------


TERMINAL_STATES = {"CLOSED", "ABORTED_SAFE"}


def _evaluation_instant(r: Repository, incident: Any, now: str) -> tuple[str, str]:
    """The instant the hard invariants should be asked about, and why that instant.

    N4 asks how old a telemetry reading is *now*. For a rescue still running, "now" is
    wall clock and a stale reading is a live finding. For a rescue that terminated, wall
    clock keeps ageing evidence that stopped changing when the incident closed, so every
    past incident drifts into a failing freshness check within one window and stays
    there forever — which is what made a CLOSED incident render a red N4 banner while
    the offline verifier called the same incident PASS.

    ``nightshift/evidence/manifest.py`` already fixed the contract for the signed
    artifact ("a verifier running next week must ask the same question against the same
    now"), and ``nightshift/verify/verifier.py`` already honours it. This applies the
    same rule to the live read path so all three surfaces agree.
    """
    if incident.state.value in TERMINAL_STATES:
        if incident.closed_at:
            return str(incident.closed_at), "incident closed_at"
        sealed = _manifest_evaluated_at(r, incident.id)
        if sealed:
            return sealed, "sealed manifest evaluated_at"
    return now, "wall clock"


def _manifest_evaluated_at(r: Repository, incident_id: str) -> str | None:
    record = r.store.get("manifests", incident_id)
    manifest = (record or {}).get("manifest") or _manifest_from_disk(incident_id)
    value = (manifest or {}).get("evaluated_at")
    return str(value) if value else None


@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str, namespace: str | None = None) -> dict[str, Any]:
    r = repo(namespace)
    incident = r.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail={"error": "unknown incident"})

    state = r.load_kernel_state(incident_id)
    recon = reconciliation_snapshot(state)
    now = now_iso()
    evaluated_as_of, evaluation_basis = _evaluation_instant(r, incident, now)
    invariants = check_all_invariants(state, evaluated_as_of)
    freezer = r.get_freezer(incident.failed_freezer_id)
    readings = r.list_readings(incident.failed_freezer_id)

    trace_ids = sorted(
        {rc.trace_id for rc in r.list_receipts(incident_id) if rc.trace_id}
        | ({incident.trace_root_id} if incident.trace_root_id else set())
    )
    return {
        "incident": incident.model_dump(mode="json"),
        "evaluated_at": now,
        "evaluated_as_of": evaluated_as_of,
        "evaluation_basis": evaluation_basis,
        "trace": {
            "root_trace_id": incident.trace_root_id,
            "trace_ids": trace_ids,
            "console_url": (
                otel.cloud_trace_url(incident.trace_root_id, settings.project_id)
                if incident.trace_root_id
                else ""
            ),
            "enabled": otel.tracing_status()["enabled"],
        },
        "freezer": freezer.model_dump(mode="json") if freezer else None,
        "temperature_series": [
            {"id": x.id, "celsius": x.celsius, "recorded_at": x.recorded_at}
            for x in readings[-160:]
        ],
        "impact": (imp := r.get_impact(incident_id)) and imp.model_dump(mode="json"),
        "reconciliation": {**recon.as_dict(), "hash": recon.snapshot_hash},
        "reservations": [
            res.model_dump(mode="json")
            for res in r.list_reservations()
            if res.incident_id == incident_id
        ],
        "work_orders": [w.model_dump(mode="json") for w in r.list_work_orders(incident_id)],
        "dispatches": [
            {k: v for k, v in d.model_dump(mode="json").items() if k != "task_token"}
            for d in r.list_dispatches(incident_id)
        ],
        "transfers": [t.model_dump(mode="json") for t in r.list_transfers(incident_id)],
        "receipts": [rc.model_dump(mode="json") for rc in r.list_receipts(incident_id)],
        "invariants": [x.as_dict() for x in invariants],
        "containers": [
            {
                "container_id": c.id,
                "freezer_id": c.freezer_id,
                "slot_id": c.slot_id,
                "study_id": c.study_id,
                "priority_class": c.priority_class,
                "specimen_count": c.specimen_count,
                "custody_state": c.custody_state.value,
            }
            for c in sorted(r.list_containers(incident_id=incident_id), key=lambda x: x.id)
        ],
    }


@app.get("/api/incidents/{incident_id}/timeline")
async def get_timeline(incident_id: str, namespace: str | None = None) -> dict[str, Any]:
    r = repo(namespace)
    events = r.list_events(incident_id)
    return {
        "incident_id": incident_id,
        "count": len(events),
        "events": [e.model_dump(mode="json") for e in events],
    }


@app.get("/api/incidents/{incident_id}/proof")
async def get_proof(incident_id: str, namespace: str | None = None) -> dict[str, Any]:
    """The proof page's data: manifest, signature state, and a live verification."""
    r = repo(namespace)
    record = r.store.get("manifests", incident_id)
    manifest = record.get("manifest") if record else _manifest_from_disk(incident_id)
    if manifest is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "no evidence manifest exists for this incident yet"},
        )
    result = verify_manifest(manifest)
    return {
        "incident_id": incident_id,
        "manifest": manifest,
        "manifest_hash": (record or {}).get("manifest_hash"),
        "gcs_uri": (record or {}).get("gcs_uri"),
        "verification": result.as_dict(),
        "verify_command": "python -m nightshift.verify --manifest <path-or-url>",
    }


def _manifest_from_disk(incident_id: str) -> dict[str, Any] | None:
    path = settings.evidence_dir / "incidents" / f"{incident_id}.manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# Fleet, drills, evidence
# --------------------------------------------------------------------------------------


@app.get("/api/fleet")
async def fleet(namespace: str | None = None) -> dict[str, Any]:
    r = repo(namespace)
    revisions = {row["agent"]: row for row in r.store.query("agentRevisions")}
    registry = _load_registry_snapshot()
    qualification = _load_qualification()
    matrix = permission_matrix()

    operational = [
        AgentName.COMMANDER,
        AgentName.SIGNAL_INVESTIGATOR,
        AgentName.IMPACT_ANALYST,
        AgentName.CAPACITY_BROKER,
        AgentName.DISPATCH_AGENT,
        AgentName.CUSTODY_AGENT,
    ]
    return {
        "evaluated_at": now_iso(),
        "agents": [
            {
                "agent": a.value,
                "revision": revisions.get(a.value, {}).get("revision_id", "rev-1"),
                "qualification": revisions.get(a.value, {}).get("state", "UNQUALIFIED"),
                "traffic_percent": 100
                if revisions.get(a.value, {}).get("state") in {"ACTIVE", "QUALIFIED"}
                else 0,
                "identity": registry.get(a.value, {}).get("identity") or _configured_identity(a),
                "identity_source": (
                    "agent-registry-snapshot"
                    if registry.get(a.value, {}).get("identity")
                    else ("provisioned-service-account" if _configured_identity(a) else "none")
                ),
                "runtime_resource": registry.get(a.value, {}).get("runtime_resource"),
                "registry_resource": registry.get(a.value, {}).get("registry_resource"),
                "latest_drill": _drill_result_for(a.value, qualification),
                "authority_domains": sorted(d.value for d in AGENT_TOOL_DOMAINS.get(a, [])),
                "allowed_tools": tools_for(a),
                "forbidden_tools": sorted(set(TOOL_REGISTRY) - set(tools_for(a))),
                "permissions": matrix.get(a.value, {}),
            }
            for a in operational
        ],
        "permission_matrix": matrix,
        "skills": [s.as_dict() for s in load_skills().values()],
        "tool_registry": [
            {
                "name": t.name,
                "service": t.service,
                "domain": t.domain.value,
                "mutating": t.mutating,
                "description": t.description,
            }
            for t in sorted(TOOL_REGISTRY.values(), key=lambda x: x.name)
        ],
    }


def _load_registry_snapshot() -> dict[str, dict[str, Any]]:
    """Live Agent Registry / Identity resources recorded by the deploy script."""
    path = settings.repo_root / "infra" / "registry-snapshot.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("agents", {})
    except Exception:
        return {}


def _configured_identity(agent: AgentName) -> str | None:
    """The Google service account this agent actually calls as.

    ``infra/bootstrap/provision.sh`` creates one account per agent and grants the
    runtime ``roles/iam.serviceAccountTokenCreator`` on each, and
    ``services/gateway/identity_tokens.py`` mints the outbound OIDC token as that
    account. The name is therefore a real principal, and it is the same principal
    ``evidence/iam-denial.json`` records receiving a 403 from the Cloud Run edge.

    It is reported as ``provisioned-service-account`` and not as a registry read,
    because nothing here queries Agent Registry. Reporting it as a registry resource
    would be the overclaim this field exists to avoid.
    """
    from services.gateway.identity_tokens import AGENT_SERVICE_ACCOUNTS

    short = AGENT_SERVICE_ACCOUNTS.get(agent)
    if not short or not settings.project_id:
        return None
    return f"{short}@{settings.project_id}.iam.gserviceaccount.com"


def _load_qualification() -> dict[str, Any]:
    """The signed qualification record, if one has been produced."""
    path = settings.evidence_dir / "qualification.json"
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _drill_result_for(agent: str, qualification: dict[str, Any]) -> dict[str, Any] | None:
    """The corpus outcome covering this agent's current revision.

    Drills exercise the whole fleet at once, so there is no per-agent drill result to
    report and inventing one would imply an attribution the corpus does not make. What
    is true per agent is which qualification run its revision was scored under, so that
    is what this returns — named ``covered_by_run`` rather than anything that reads like
    the agent was drilled alone.
    """
    revisions = qualification.get("agent_revisions") or {}
    revision = revisions.get(agent)
    if not revision:
        return None
    return {
        "revision": revision,
        "covered_by_run": qualification.get("run_id"),
        "outcome": "PASS" if qualification.get("qualified") else "FAIL",
        "corpus_version": qualification.get("corpus_version"),
        "scope": "whole-fleet corpus run; drills are not attributed to a single agent",
    }


@app.get("/api/drills")
async def drills() -> dict[str, Any]:
    from assurance.corpus import CORPUS_VERSION, DRILLS

    results = _load_campaign()
    per_drill: dict[str, Any] = {}
    for driver, block in (results.get("metrics", {}).get("by_driver") or {}).items():
        for drill_id, stats in (block.get("per_drill") or {}).items():
            per_drill.setdefault(drill_id, {})[driver] = stats

    return {
        "corpus_version": CORPUS_VERSION,
        "drills": [{**d.as_dict(), "results": per_drill.get(d.id, {})} for d in DRILLS],
        "campaign": results.get("metrics", {}),
        "provenance": results.get("provenance", {}),
    }


@app.get("/api/drills/{drill_id}")
async def drill_detail(drill_id: str) -> dict[str, Any]:
    from assurance.corpus import DRILLS

    spec = next((d for d in DRILLS if d.id == drill_id), None)
    if spec is None:
        raise HTTPException(status_code=404, detail={"error": "unknown drill"})
    results = _load_campaign()
    runs = [r for r in results.get("runs", []) if r.get("drill_id") == drill_id]
    return {"drill": spec.as_dict(), "runs": runs, "run_count": len(runs)}


@app.get("/api/evidence")
async def evidence() -> dict[str, Any]:
    """Published manifests and the campaign summary."""
    directory = settings.evidence_dir / "incidents"
    manifests = []
    if directory.exists():
        for path in sorted(directory.glob("*.manifest.json")):
            try:
                body = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                log.warning("skipping unreadable manifest %s: %s", path.name, exc)
                continue
            result = verify_manifest(body)
            manifests.append(
                {
                    "incident_id": body.get("incident_id"),
                    "incident_state": body.get("incident_state"),
                    "evaluated_at": body.get("evaluated_at"),
                    "signer_backend": body.get("signer_backend"),
                    "invariants_all_hold": body.get("invariants_all_hold"),
                    "failed_invariants": body.get("failed_invariants", []),
                    "reconciliation": body.get("reconciliation", {}),
                    "verification_status": result.status.value,
                }
            )
    campaign = _load_campaign()
    return {
        "manifests": manifests,
        "campaign_metrics": campaign.get("metrics", {}),
        "campaign_provenance": campaign.get("provenance", {}),
        "claims": _load_claims(),
    }


def _load_campaign() -> dict[str, Any]:
    """Both measurement tiers, read together and never pooled.

    This used to return inside the loop, so the live-agent directory was unreachable and
    the deployed assurance surface of an agentic system published ``model_calls_total:
    0`` while the same API served a claim citing the file it had refused to read.

    The tiers are merged for *reading* only. ``by_driver`` keeps them apart because the
    commands, seeds, drill selection and holdout policy genuinely differ, so a pooled
    pass rate would describe no experiment that was ever run. Provenance is kept per
    driver for the same reason.
    """
    bodies: list[dict[str, Any]] = []
    for name in ("campaign", "campaign-agent"):
        path = settings.evidence_dir / name / "results.json"
        if not path.exists():
            continue
        try:
            bodies.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            log.warning("skipping unreadable campaign results %s: %s", path, exc)
    if not bodies:
        return {}

    by_driver: dict[str, Any] = {}
    provenance_by_driver: dict[str, Any] = {}
    runs: list[Any] = []
    total_runs = 0
    corpus_version = ""
    generated_at = ""
    for body in bodies:
        metrics = body.get("metrics") or {}
        provenance = body.get("provenance") or {}
        for driver, stats in (metrics.get("by_driver") or {}).items():
            by_driver[driver] = stats
            provenance_by_driver[driver] = provenance
        runs.extend(body.get("runs") or [])
        total_runs += int(metrics.get("total_runs") or 0)
        corpus_version = corpus_version or str(metrics.get("corpus_version") or "")
        generated_at = max(generated_at, str(metrics.get("generated_at") or ""))

    return {
        "metrics": {
            "generated_at": generated_at,
            "corpus_version": corpus_version,
            "total_runs": total_runs,
            "runs_by_driver": {
                d: b.get("total_runs", b.get("scored_runs")) for d, b in by_driver.items()
            },
            "by_driver": by_driver,
        },
        "provenance": provenance_by_driver.get("scripted")
        or next(iter(provenance_by_driver.values()), {}),
        "provenance_by_driver": provenance_by_driver,
        "runs": runs,
    }


def _load_claims() -> list[dict[str, Any]]:
    path = settings.repo_root / "docs" / "CLAIMS.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("claims", [])
    except Exception:
        return []


# --------------------------------------------------------------------------------------
# Responder flow
# --------------------------------------------------------------------------------------


class ScanRequest(BaseModel):
    container_id: str = Field(max_length=64)
    location_ref: str = Field(default="", max_length=64)


class ExceptionRequest(BaseModel):
    container_id: str = Field(max_length=64)
    reason: str = Field(max_length=400)
    disposition: str = Field(default="UNRESOLVED", pattern="^(UNRESOLVED|QUARANTINED)$")


def _dispatch_for(token: str, namespace: str | None = None) -> tuple[Repository, Any]:
    for ns in {namespace or settings.namespace, settings.namespace, "demo"}:
        r = repo(ns)
        for row in r.store.query("dispatches", task_token=token):
            from nightshift.schemas.core import Dispatch

            return r, Dispatch(**row)
    raise HTTPException(status_code=404, detail={"error": "unknown or expired task token"})


@app.get("/api/respond/{token}")
async def responder_task(token: str, namespace: str | None = None) -> dict[str, Any]:
    """The responder's whole world: their batch, and nothing else.

    Deliberately narrow — no study names, no specimen counts, no other incidents. A
    responder needs a container code, a source, a destination, and whether the
    destination is cold enough.
    """
    r, dispatch = _dispatch_for(token, namespace)
    incident = r.get_incident(dispatch.incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail={"error": "incident not found"})

    state = r.load_kernel_state(dispatch.incident_id)
    transfers = {t.container_id: t for t in r.list_transfers(dispatch.incident_id)}
    now = now_iso()

    tasks = []
    for container_id in sorted(state.incident_container_ids()):
        container = state.containers.get(container_id)
        if container is None:
            continue
        transfer = transfers.get(container_id)
        # Before a pickup there is no transfer record yet, so the destination has to
        # come from the reservation the Broker made. Without this the responder screen
        # showed no destination and the "Confirm pickup" button was permanently
        # disabled — a deadlock that made the whole flow unusable.
        destination = (
            transfer.destination_freezer if transfer else _planned_destination(state, container_id)
        )
        dest_freezer = r.get_freezer(destination) if destination else None
        dest_readings = r.list_readings(destination) if destination else []
        latest = dest_readings[-1] if dest_readings else None
        planned_slot = (
            transfer.destination_slot
            if transfer
            else (f"{destination}-SLOT-{container_id[-4:]}" if destination else None)
        )
        tasks.append(
            {
                "container_id": container_id,
                "source_freezer": container.freezer_id if not transfer else transfer.source_freezer,
                "source_slot": container.slot_id,
                "destination_freezer": destination,
                "destination_slot": planned_slot,
                "custody_state": container.custody_state.value,
                "destination_temp_c": latest.celsius
                if latest
                else (dest_freezer.current_temp_c if dest_freezer else None),
                "destination_reading_age_s": (
                    round(age_seconds(latest.recorded_at, now), 1) if latest else None
                ),
                "exception_reason": transfer.exception_reason if transfer else None,
            }
        )

    return {
        "incident_id": dispatch.incident_id,
        "incident_state": incident.state.value,
        "responder_id": dispatch.responder_id,
        "responder_role": dispatch.responder_role.value,
        "response_phase": dispatch.response_phase.value,
        "failed_freezer_id": incident.failed_freezer_id,
        "evaluated_at": now,
        "synthetic": True,
        "tasks": tasks,
        "summary": {
            "total": len(tasks),
            "at_source": sum(1 for t in tasks if t["custody_state"] == "AT_SOURCE"),
            "picked_up": sum(1 for t in tasks if t["custody_state"] in {"PICKED_UP", "IN_TRANSIT"}),
            "received": sum(1 for t in tasks if t["custody_state"] == "RECEIVED"),
            "committed": sum(1 for t in tasks if t["custody_state"] == "COMMITTED"),
            "exceptions": sum(
                1 for t in tasks if t["custody_state"] in {"UNRESOLVED", "QUARANTINED"}
            ),
        },
    }


def _planned_destination(state: Any, container_id: str) -> str | None:
    """Where this container is *going*, from the reservation covering its group.

    The responder needs to know the destination before they pick anything up, and the
    transfer record that would normally carry it does not exist until they do.
    """
    if state.impact is None or state.incident is None:
        return None
    group_id = next(
        (g.id for g in state.impact.placement_groups if container_id in g.container_ids),
        None,
    )
    if group_id is None:
        return None
    for reservation in state.reservations.values():
        if (
            reservation.incident_id == state.incident.id
            and reservation.placement_group_id == group_id
            and reservation.state.value in {"ACTIVE", "CONSUMED"}
        ):
            return str(reservation.destination_freezer_id)
    return None


def _responder_broker(r: Repository) -> Any:
    from services.common.identity import issue_principal_token
    from services.gateway.broker import ToolBroker
    from services.gateway.transport import InProcessTransport

    return ToolBroker(
        transport=InProcessTransport.build(r),
        principal_token_for=lambda agent: issue_principal_token(
            agent, "rev-1", settings.agent_shared_secret
        ),
    )


@app.post("/api/respond/{token}/pickup")
async def responder_pickup(
    token: str, body: ScanRequest, namespace: str | None = None
) -> dict[str, Any]:
    r, dispatch = _dispatch_for(token, namespace)
    state = r.load_kernel_state(dispatch.incident_id)
    container = state.containers.get(body.container_id)
    if container is None:
        raise HTTPException(status_code=404, detail={"error": "unknown container"})
    transfer = next(
        (t for t in r.list_transfers(dispatch.incident_id) if t.container_id == body.container_id),
        None,
    )
    reservation = _reservation_for(state, dispatch.incident_id)
    destination = (
        transfer.destination_freezer
        if transfer
        else (reservation.destination_freezer_id if reservation else "")
    )
    if not destination:
        raise HTTPException(
            status_code=409,
            detail={"error": "no reserved destination exists for this container yet"},
        )
    slot = transfer.destination_slot if transfer else f"{destination}-SLOT-{body.container_id[-4:]}"

    return _broker_call(
        r,
        "record_pickup",
        {
            "incident_id": dispatch.incident_id,
            "container_id": body.container_id,
            "responder_id": dispatch.responder_id,
            "source_freezer": container.freezer_id,
            "destination_freezer": destination,
            "destination_slot": slot,
            "reservation_id": reservation.id if reservation else None,
            "scan_signature": _signature(token, body.container_id, "pickup"),
            "simulated": False,
        },
    )


@app.post("/api/respond/{token}/receive")
async def responder_receive(
    token: str, body: ScanRequest, namespace: str | None = None
) -> dict[str, Any]:
    r, dispatch = _dispatch_for(token, namespace)
    transfer = next(
        (t for t in r.list_transfers(dispatch.incident_id) if t.container_id == body.container_id),
        None,
    )
    if transfer is None:
        raise HTTPException(status_code=409, detail={"error": "no pickup recorded yet"})

    scanned = body.location_ref or transfer.destination_freezer
    result = _broker_call(
        r,
        "record_destination_scan",
        {
            "incident_id": dispatch.incident_id,
            "container_id": body.container_id,
            "responder_id": dispatch.responder_id,
            "destination_freezer_id": scanned,
            "destination_slot": transfer.destination_slot,
            "scan_signature": _signature(token, body.container_id, "destination"),
            "simulated": False,
        },
    )
    if result.get("receipt", {}).get("status") == "COMMITTED":
        # Attempt the authoritative commit immediately. It will be refused if the
        # destination reading is stale or out of bounds, and the responder sees why.
        result["commit"] = _broker_call(
            r,
            "commit_transfer",
            {"incident_id": dispatch.incident_id, "container_id": body.container_id},
            agent=AgentName.CUSTODY_AGENT,
        )
    return result


@app.post("/api/respond/{token}/exception")
async def responder_exception(
    token: str, body: ExceptionRequest, namespace: str | None = None
) -> dict[str, Any]:
    r, dispatch = _dispatch_for(token, namespace)
    return _broker_call(
        r,
        "flag_custody_exception",
        {
            "incident_id": dispatch.incident_id,
            "container_id": body.container_id,
            "reason": body.reason,
            "disposition": body.disposition,
        },
    )


def _reservation_for(state: Any, incident_id: str) -> Any:
    live = [
        r
        for r in state.reservations.values()
        if r.incident_id == incident_id
        and r.state.value in {"ACTIVE", "CONSUMED"}
        and r.held_slots > 0
    ]
    return live[0] if live else None


def _signature(token: str, container_id: str, phase: str) -> str:
    from services.common.identity import responder_task_signature

    return responder_task_signature(token, {"container_id": container_id, "phase": phase})


def _broker_call(
    r: Repository, tool: str, payload: dict[str, Any], agent: AgentName = AgentName.RESPONDER_APP
) -> dict[str, Any]:
    from services.gateway.broker import BrokerDeniedError

    broker = _responder_broker(r)
    try:
        return broker.call(agent, tool, payload)
    except BrokerDeniedError as denied:
        raise HTTPException(status_code=403, detail=denied.decision.as_dict()) from denied
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc


# --------------------------------------------------------------------------------------
# Bounded demo drill
# --------------------------------------------------------------------------------------


class DemoDrillRequest(BaseModel):
    drill_id: str = Field(default="D2", max_length=8)


@app.post("/api/demo/drills")
async def create_demo_drill(request: Request, body: DemoDrillRequest) -> dict[str, Any]:
    """Run one bounded drill in a throwaway namespace.

    Uses the scripted driver: it exercises the real services, the real kernel, and real
    fault injection with no model call, which is what makes it safe to expose publicly.
    The model-driven tier is not reachable from an unauthenticated endpoint.
    """
    from assurance.controller import run_drill
    from assurance.corpus import DRILLS

    spec = next((d for d in DRILLS if d.id == body.drill_id), None)
    if spec is None:
        raise HTTPException(status_code=404, detail={"error": "unknown drill"})

    bucket = limiter.bucket_for(request)
    ok, reason = limiter.check(bucket)
    if not ok:
        raise HTTPException(status_code=429, detail={"error": reason})

    limiter.acquire(bucket)
    try:
        result = await run_drill(spec, driver="scripted")
    finally:
        limiter.release()

    outcome = result.outcome
    return {
        "drill": spec.as_dict(),
        "outcome": outcome.as_dict(),
        "namespace": result.runtime.repo.namespace,
        "note": (
            "Ran with the deterministic scripted driver against the real services and "
            "the real Safety Kernel. Data lives in a throwaway namespace and is not "
            "reachable from any other namespace."
        ),
    }
