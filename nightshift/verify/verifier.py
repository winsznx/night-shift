"""Independent verification of an incident manifest.

The verifier answers one question a reader should not have to take on trust:

    Does the stored verdict actually follow from the stored state?

It rebuilds a ``KernelState`` from the manifest's snapshot, re-runs the same invariant
functions the production services ran, and compares invariant by invariant. A manifest
whose state has been edited will produce a different recomputed verdict, or fail its
artifact hashes, or fail its signature — all three are reported separately so a mismatch
says *what* diverged.

No model is involved anywhere in this file. That is the point: the hard properties are
verifiable by arithmetic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from nightshift.common.canonical import canonical_bytes, sha256_of
from nightshift.evidence.manifest import restore_state
from nightshift.evidence.signing import Signature, verify_signature
from nightshift.safety_kernel.config import KernelConfig
from nightshift.safety_kernel.invariants import check_all_invariants
from nightshift.safety_kernel.world import reconciliation_snapshot
from nightshift.verify.trusted_keys import key_is_pinned


class VerificationStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 - a verification result, not a credential
    MISMATCH = "MISMATCH"
    PARTIAL = "PARTIAL"
    """Everything checkable checked out, but something could not be checked — most often
    an unsigned manifest. Never reported as PASS."""


@dataclass
class Check:
    name: str
    ok: bool | None
    detail: str = ""

    @property
    def symbol(self) -> str:
        return {True: "PASS", False: "FAIL", None: "SKIP"}[self.ok]


@dataclass
class VerificationResult:
    status: VerificationStatus
    incident_id: str
    checks: list[Check] = field(default_factory=list)
    recomputed: dict[str, bool] = field(default_factory=dict)
    stored: dict[str, bool] = field(default_factory=dict)
    divergences: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "incident_id": self.incident_id,
            "checks": [
                {"name": c.name, "result": c.symbol, "detail": c.detail} for c in self.checks
            ],
            "recomputed_invariants": self.recomputed,
            "stored_invariants": self.stored,
            "divergences": self.divergences,
        }

    def render(self) -> str:
        lines = [
            f"Night Shift verifier — incident {self.incident_id or '(unknown)'}",
            "",
        ]
        width = max((len(c.name) for c in self.checks), default=20)
        for c in self.checks:
            lines.append(f"  {c.symbol:<4} {c.name.ljust(width)}  {c.detail}")
        lines.append("")
        if self.divergences:
            lines.append("Divergences between stored and recomputed verdict:")
            lines.extend(f"  - {d}" for d in self.divergences)
            lines.append("")
        lines.append(f"RESULT: {self.status.value}")
        return "\n".join(lines)


def verify_manifest(
    manifest: dict[str, Any], *, signature: dict[str, Any] | None = None
) -> VerificationResult:
    incident_id = str(manifest.get("incident_id", ""))
    checks: list[Check] = []

    # --- structural -----------------------------------------------------------------
    version = manifest.get("manifest_version")
    checks.append(Check("manifest version", version == 1, f"version={version}"))

    snapshot = manifest.get("state_snapshot")
    if not isinstance(snapshot, dict):
        checks.append(Check("state snapshot present", False, "missing or malformed"))
        return VerificationResult(
            status=VerificationStatus.MISMATCH, incident_id=incident_id, checks=checks
        )
    checks.append(Check("state snapshot present", True, f"{len(snapshot)} collections"))

    # --- artifact hashes -------------------------------------------------------------
    stored_hashes = manifest.get("artifact_hashes") or {}
    for key, source in (
        ("state_snapshot", snapshot),
        ("invariant_results", manifest.get("invariant_results")),
        ("reconciliation", manifest.get("reconciliation")),
    ):
        expected = stored_hashes.get(key)
        if expected is None:
            checks.append(Check(f"artifact hash: {key}", None, "not present in manifest"))
            continue
        actual = sha256_of(source)
        checks.append(
            Check(
                f"artifact hash: {key}",
                actual == expected,
                f"{actual[:16]}… vs stored {str(expected)[:16]}…",
            )
        )

    # --- signature -------------------------------------------------------------------
    # Every signature that travels with the manifest is checked, not just the first one
    # found. Preferring a detached sidecar over the embedded field would let an edit to
    # the embedded signature pass unnoticed, which is exactly backwards.
    body = {k: v for k, v in manifest.items() if k != "signature"}
    payload = canonical_bytes(body)
    embedded = manifest.get("signature")
    candidates = [("embedded", embedded), ("detached", signature)]
    present = [(label, data) for label, data in candidates if data]

    if not present:
        checks.append(Check("signature", None, "manifest is unsigned"))
    else:
        for label, data in present:
            name = "signature" if len(present) == 1 else f"signature ({label})"
            if str(data.get("algorithm")) == "none":
                # Not a failed check — a check that could not be performed.
                checks.append(Check(name, None, "manifest was written by an unsigned backend"))
                continue
            # Pin the signer before trusting the signature. Checking a signature against
            # the key the same document supplies proves only that the document is
            # internally consistent, which a forger can arrange trivially.
            pinned, pin_detail = key_is_pinned(
                str(data.get("public_key_pem") or ""),
                backend=str(data.get("backend") or ""),
                key_ref=str(data.get("key_ref") or ""),
            )
            checks.append(
                Check(
                    "signing key is pinned" if len(present) == 1 else f"signing key ({label})",
                    pinned,
                    pin_detail,
                )
            )
            ok, reason = verify_signature(payload, Signature.from_dict(data))
            backend = data.get("backend", "unknown")
            checks.append(Check(name, ok, reason or f"verified against {backend} public key"))
        if len(present) == 2 and embedded and signature:
            same = embedded.get("signature_b64") == signature.get("signature_b64")
            checks.append(
                Check(
                    "embedded and detached signatures agree",
                    same,
                    "identical" if same else "the two signatures differ",
                )
            )

    # --- recomputation ---------------------------------------------------------------
    try:
        state = restore_state(snapshot)
    except Exception as exc:
        checks.append(Check("state snapshot parses", False, f"{type(exc).__name__}: {exc}"))
        return VerificationResult(
            status=VerificationStatus.MISMATCH, incident_id=incident_id, checks=checks
        )
    checks.append(Check("state snapshot parses", True, "rebuilt KernelState"))

    evaluated_at = str(manifest.get("evaluated_at", ""))
    if not evaluated_at:
        checks.append(Check("evaluation timestamp", False, "missing; N4 cannot be replayed"))
        return VerificationResult(
            status=VerificationStatus.MISMATCH, incident_id=incident_id, checks=checks
        )

    config = _config_from(manifest.get("kernel_config") or {})
    results = check_all_invariants(
        state,
        evaluated_at,
        delivered_event_ids=list(manifest.get("delivered_event_ids") or []),
        config=config,
    )
    recomputed = {r.invariant: r.holds for r in results}
    stored = {
        str(r["invariant"]): bool(r["holds"])
        for r in (manifest.get("invariant_results") or [])
        if isinstance(r, dict) and "invariant" in r
    }

    divergences: list[str] = []
    for name in sorted(set(recomputed) | set(stored)):
        want = stored.get(name)
        got = recomputed.get(name)
        if want is None:
            divergences.append(f"{name}: recomputed {got}, absent from the stored verdict")
        elif got is None:
            divergences.append(f"{name}: stored {want}, not recomputable")
        elif want != got:
            divergences.append(f"{name}: stored {want}, recomputed {got}")
    checks.append(
        Check(
            "invariant verdict matches",
            not divergences,
            f"{len(recomputed)} invariants recomputed"
            + ("" if not divergences else f", {len(divergences)} divergent"),
        )
    )

    # --- reconciliation ---------------------------------------------------------------
    recon = reconciliation_snapshot(state)
    stored_recon_hash = manifest.get("reconciliation_hash")
    checks.append(
        Check(
            "reconciliation hash",
            recon.snapshot_hash == stored_recon_hash if stored_recon_hash else None,
            f"{recon.snapshot_hash[:16]}… vs stored {str(stored_recon_hash)[:16]}…"
            if stored_recon_hash
            else "not present in manifest",
        )
    )

    # --- honesty checks ---------------------------------------------------------------
    stated_state = manifest.get("incident_state")
    actual_state = state.incident.state.value if state.incident else None
    checks.append(
        Check(
            "declared incident state",
            stated_state == actual_state,
            f"manifest says {stated_state}, snapshot says {actual_state}",
        )
    )
    if stated_state == "CLOSED":
        checks.append(
            Check(
                "closed incident is fully reconciled",
                recon.complete,
                f"{len(recon.unresolved)} unresolved, {len(recon.in_flight)} in flight",
            )
        )
    checks.append(
        Check(
            "synthetic data declared",
            bool(manifest.get("synthetic")),
            "manifest declares synthetic/simulated provenance",
        )
    )

    failed = [c for c in checks if c.ok is False]
    skipped = [c for c in checks if c.ok is None]
    if failed or divergences:
        status = VerificationStatus.MISMATCH
    elif skipped:
        status = VerificationStatus.PARTIAL
    else:
        status = VerificationStatus.PASS

    return VerificationResult(
        status=status,
        incident_id=incident_id,
        checks=checks,
        recomputed=recomputed,
        stored=stored,
        divergences=divergences,
    )


def _config_from(raw: dict[str, Any]) -> KernelConfig:
    """Rebuild the kernel config the manifest was evaluated under.

    Thresholds travel with the manifest so a verifier reaches the same verdict even if
    the defaults later change.
    """
    fields = {f for f in KernelConfig.__dataclass_fields__}
    return KernelConfig(**{k: v for k, v in raw.items() if k in fields})


def verify_manifest_file(path: str | Path) -> VerificationResult:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    sig_path = Path(str(path) + ".sig")
    signature = json.loads(sig_path.read_text(encoding="utf-8")) if sig_path.exists() else None
    return verify_manifest(data, signature=signature)


def verify_manifest_url(url: str) -> VerificationResult:
    import httpx

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        manifest = client.get(url).json()
        signature = None
        sig_response = client.get(url + ".sig")
        if sig_response.status_code == 200:
            try:
                signature = sig_response.json()
            except ValueError:
                signature = None
    return verify_manifest(manifest, signature=signature)
