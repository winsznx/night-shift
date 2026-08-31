"""Incident evidence manifest (PRD §28).

The manifest carries two things that matter to a verifier:

* the **stored verdict** — what Night Shift claims the invariants said; and
* the **state snapshot** — enough authoritative state to recompute that verdict.

The verifier rebuilds a ``KernelState`` from the snapshot, re-runs the same kernel
functions, and compares. Nothing in this file consults a model, and the evaluation
timestamp is stored so freshness checks (N4) replay identically instead of drifting
with wall-clock time.
"""

from __future__ import annotations

from typing import Any

from nightshift.common.canonical import canonical_bytes, sha256_bytes, sha256_of
from nightshift.common.clock import now_iso
from nightshift.safety_kernel.config import DEFAULT_CONFIG, KernelConfig
from nightshift.safety_kernel.invariants import check_all_invariants
from nightshift.safety_kernel.world import KernelState, reconciliation_snapshot
from nightshift.schemas.core import (
    ActionReceipt,
    Container,
    ContainmentHold,
    Dispatch,
    Freezer,
    ImpactSnapshot,
    Incident,
    Reservation,
    TemperatureReading,
    Transfer,
    WorkOrder,
)

MANIFEST_VERSION = 1

_COLLECTIONS: dict[str, Any] = {
    "freezers": Freezer,
    "containers": Container,
    "reservations": Reservation,
    "work_orders": WorkOrder,
    "dispatches": Dispatch,
    "transfers": Transfer,
    "receipts": ActionReceipt,
    "holds": ContainmentHold,
    "readings": TemperatureReading,
}


def redact_task_token(token: str) -> str:
    """Replace a live responder token with a stable, non-usable digest.

    A dispatch task token is the only credential in the responder flow: holding one is
    sufficient to read a responder's batch and to post pickup, receipt and exception
    events. Manifests are published to a public bucket and committed to a public repo,
    so shipping the raw token hands that authority to anyone who reads the evidence.

    The digest keeps every property the manifest actually needs. It is stable, so two
    dispatches remain distinguishable and a verifier still recomputes an identical
    snapshot hash. No kernel invariant reads this field, so redacting it cannot change
    a recomputed verdict.
    """
    if not token:
        return token
    return f"sha256:{sha256_bytes(token.encode('utf-8'))[:16]}"


def snapshot_state(state: KernelState) -> dict[str, Any]:
    """Serialize a ``KernelState`` into the manifest's recomputable snapshot."""
    out: dict[str, Any] = {
        "incident": state.incident.model_dump(mode="json") if state.incident else None,
        "impact": state.impact.model_dump(mode="json") if state.impact else None,
        "revision_states": dict(state.revision_states),
        "memory_notes": list(state.memory_notes),
        "unavailable_sources": sorted(state.unavailable_sources),
    }
    for name in _COLLECTIONS:
        out[name] = {
            key: value.model_dump(mode="json") for key, value in getattr(state, name).items()
        }
    for key, dispatch in out["dispatches"].items():
        if "task_token" in dispatch:
            out["dispatches"][key] = {
                **dispatch,
                "task_token": redact_task_token(str(dispatch["task_token"])),
            }
    return out


def restore_state(snapshot: dict[str, Any]) -> KernelState:
    """Rebuild a ``KernelState`` from a manifest snapshot. Used only by the verifier."""
    kwargs: dict[str, Any] = {
        "incident": Incident(**snapshot["incident"]) if snapshot.get("incident") else None,
        "impact": ImpactSnapshot(**snapshot["impact"]) if snapshot.get("impact") else None,
        "revision_states": dict(snapshot.get("revision_states", {})),
        "memory_notes": list(snapshot.get("memory_notes", [])),
        "unavailable_sources": frozenset(snapshot.get("unavailable_sources", [])),
    }
    for name, model in _COLLECTIONS.items():
        kwargs[name] = {k: model(**v) for k, v in snapshot.get(name, {}).items()}
    return KernelState(**kwargs)


def build_manifest(
    state: KernelState,
    *,
    evaluated_at: str | None = None,
    estate_fixture_hash: str = "",
    opening_evidence: list[dict[str, Any]] | None = None,
    agents: list[dict[str, Any]] | None = None,
    skill_revisions: dict[str, str] | None = None,
    policy_refs: dict[str, Any] | None = None,
    model_armor_template: str = "",
    trace_ids: list[str] | None = None,
    delivered_event_ids: list[str] | None = None,
    source_commit: str = "unknown",
    deployment_env: str = "local",
    model_id: str = "",
    adk_version: str = "",
    corpus_version: str = "",
    limitations: list[str] | None = None,
    signer_backend: str = "",
    config: KernelConfig = DEFAULT_CONFIG,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce the canonical manifest body (unsigned).

    ``evaluated_at`` is stored deliberately: N4 asks "how old is this reading *now*",
    and a verifier running next week must ask the same question against the same
    ``now`` or it would reach a different, useless answer.
    """
    evaluated_at = evaluated_at or now_iso()
    results = check_all_invariants(
        state, evaluated_at, delivered_event_ids=delivered_event_ids or [], config=config
    )
    recon = reconciliation_snapshot(state)
    incident = state.incident

    body: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "incident_id": incident.id if incident else "",
        "synthetic": True,
        "simulated_field_events": True,
        "namespace": incident.namespace if incident else "demo",
        "evaluated_at": evaluated_at,
        "incident_state": incident.state.value if incident else "",
        "severity": incident.severity.value if incident else "",
        "opened_at": incident.opened_at if incident else "",
        "closed_at": incident.closed_at if incident else None,
        "failed_freezer_id": incident.failed_freezer_id if incident else "",
        "estate_fixture_hash": estate_fixture_hash,
        "opening_evidence": opening_evidence or [],
        "state_transitions": [
            t.model_dump(mode="json") for t in (incident.transitions if incident else [])
        ],
        "agents": agents or [],
        "skill_revisions": skill_revisions or {},
        "policy_refs": policy_refs or {},
        "model_armor_template": model_armor_template,
        "impact_snapshot_hash": incident.impact_snapshot_hash if incident else None,
        "reconciliation": recon.as_dict(),
        "reconciliation_hash": recon.snapshot_hash,
        "kernel_config": config.as_dict(),
        "invariant_results": [r.as_dict() for r in results],
        "invariants_all_hold": all(r.holds for r in results),
        "failed_invariants": [r.invariant for r in results if not r.holds],
        "delivered_event_ids": sorted(set(delivered_event_ids or [])),
        "trace_ids": sorted(set(trace_ids or [])),
        "source_commit": source_commit,
        "deployment_env": deployment_env,
        "model_id": model_id,
        "adk_version": adk_version,
        "corpus_version": corpus_version,
        "signer_backend": signer_backend,
        "limitations": limitations or [],
        "state_snapshot": snapshot_state(state),
    }
    if extra:
        body["extra"] = extra
    body["artifact_hashes"] = {
        "state_snapshot": sha256_of(body["state_snapshot"]),
        "invariant_results": sha256_of(body["invariant_results"]),
        "reconciliation": sha256_of(body["reconciliation"]),
    }
    return body


def manifest_hash(body: dict[str, Any]) -> str:
    return sha256_of(body)


def manifest_bytes(body: dict[str, Any]) -> bytes:
    return canonical_bytes(body)
