"""Write and publish evidence bundles.

An incident's evidence bundle is three files:

    <incident>.manifest.json       canonical manifest body
    <incident>.manifest.json.sig   detached signature
    <incident>.pub.pem             the public key that verifies it

They go to the repo's ``evidence/`` directory always, to Firestore ``/manifests`` when
a live store is configured, and to Cloud Storage when a bucket is configured. The local
copy is the one the clean-room reproduction reads, so ``make verify-demo`` works with no
credentials at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nightshift.common.canonical import canonical_bytes, sha256_of
from nightshift.common.clock import now_iso
from nightshift.common.config import Settings, get_settings
from nightshift.evidence.manifest import build_manifest
from nightshift.evidence.signing import Signer, get_signer
from nightshift.safety_kernel.world import KernelState
from nightshift.schemas.enums import IncidentState


@dataclass
class EvidenceBundle:
    incident_id: str
    manifest: dict[str, Any]
    manifest_hash: str
    signature: dict[str, Any]
    manifest_path: Path
    signature_path: Path
    public_key_path: Path
    gcs_uri: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "manifest_hash": self.manifest_hash,
            "signer_backend": self.signature.get("backend"),
            "manifest_path": str(self.manifest_path),
            "signature_path": str(self.signature_path),
            "public_key_path": str(self.public_key_path),
            "gcs_uri": self.gcs_uri,
        }


def _sealing_instant(state: KernelState) -> str | None:
    """The instant a manifest's invariants are evaluated at.

    N4 asks how old a destination reading is *now*. For an incident that has already
    reached a terminal state, the only ``now`` that yields a stable answer is the one
    the incident closed at: evaluating a finished rescue against wall clock re-asks the
    freshness question against readings that were current then and are not current now,
    so a manifest regenerated a week later seals an N4 failure that never happened.

    ``apps/api/main.py`` applies the same rule to the live read path. Returning ``None``
    for an open incident lets :func:`build_manifest` fall back to wall clock, which is
    correct while the rescue is still running.
    """
    incident = state.incident
    if incident is None:
        return None
    if incident.state in {IncidentState.CLOSED, IncidentState.ABORTED_SAFE}:
        return str(incident.closed_at) if incident.closed_at else None
    return None


def write_evidence(
    state: KernelState,
    *,
    settings: Settings | None = None,
    signer: Signer | None = None,
    out_dir: Path | None = None,
    upload: bool = True,
    **manifest_kwargs: Any,
) -> EvidenceBundle:
    """Build, sign, and publish an incident's evidence bundle."""
    settings = settings or get_settings()
    signer = signer or get_signer(settings)
    out_dir = out_dir or (settings.evidence_dir / "incidents")
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest_kwargs.setdefault("source_commit", settings.source_commit)
    manifest_kwargs.setdefault("deployment_env", settings.deployment_env)
    manifest_kwargs.setdefault("model_id", settings.model_id)
    manifest_kwargs.setdefault("model_armor_template", settings.model_armor_template)
    manifest_kwargs.setdefault("evaluated_at", _sealing_instant(state))
    manifest_kwargs["signer_backend"] = signer.backend

    body = build_manifest(state, **manifest_kwargs)
    incident_id = str(body.get("incident_id") or "unknown")

    # Sign the body *without* the signature field, so verification recomputes the exact
    # same bytes that were signed.
    payload = canonical_bytes(body)
    signature = signer.sign(payload)
    body_with_sig = {**body, "signature": signature.as_dict()}

    manifest_path = out_dir / f"{incident_id}.manifest.json"
    signature_path = out_dir / f"{incident_id}.manifest.json.sig"
    public_key_path = out_dir / f"{incident_id}.pub.pem"

    manifest_path.write_text(json.dumps(body_with_sig, indent=2), encoding="utf-8")
    signature_path.write_text(json.dumps(signature.as_dict(), indent=2), encoding="utf-8")
    if signature.public_key_pem:
        public_key_path.write_text(signature.public_key_pem, encoding="utf-8")

    bundle = EvidenceBundle(
        incident_id=incident_id,
        manifest=body_with_sig,
        manifest_hash=sha256_of(body),
        signature=signature.as_dict(),
        manifest_path=manifest_path,
        signature_path=signature_path,
        public_key_path=public_key_path,
    )

    if upload and settings.evidence_bucket:
        bundle.gcs_uri = _upload(settings, bundle)
    return bundle


def _upload(settings: Settings, bundle: EvidenceBundle) -> str | None:
    """Best-effort upload to Cloud Storage. A failure downgrades, never fabricates."""
    try:
        from google.cloud import storage  # type: ignore[attr-defined]

        client = storage.Client(project=settings.project_id)
        bucket = client.bucket(settings.evidence_bucket)
        prefix = f"incidents/{bundle.incident_id}"
        for path, name, content_type in (
            (bundle.manifest_path, f"{prefix}/manifest.json", "application/json"),
            (bundle.signature_path, f"{prefix}/manifest.json.sig", "application/json"),
            (bundle.public_key_path, f"{prefix}/public_key.pem", "application/x-pem-file"),
        ):
            if path.exists():
                bucket.blob(name).upload_from_filename(str(path), content_type=content_type)
        return f"gs://{settings.evidence_bucket}/{prefix}/manifest.json"
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(
            "evidence upload to gs://%s failed (%s); the local bundle is authoritative "
            "and no upload is claimed",
            settings.evidence_bucket,
            exc,
        )
        return None


def record_manifest_in_store(repo: Any, bundle: EvidenceBundle) -> None:
    """Index the manifest so the proof API can find it without touching the filesystem."""
    repo.store.set(
        "manifests",
        bundle.incident_id,
        {
            "incident_id": bundle.incident_id,
            "manifest_hash": bundle.manifest_hash,
            "signer_backend": bundle.signature.get("backend"),
            "signature_b64": bundle.signature.get("signature_b64"),
            "public_key_pem": bundle.signature.get("public_key_pem"),
            "gcs_uri": bundle.gcs_uri,
            "created_at": now_iso(),
            "manifest": bundle.manifest,
        },
    )
