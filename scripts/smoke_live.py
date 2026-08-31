"""Smoke test the deployed public API.

uv run python scripts/smoke_live.py [BASE_URL]

Two layers. Reachability says the deployment answers. Provenance says it is answering
with the evidence this checkout can reproduce: a stale revision serving last week's
manifests returned 200 on every endpoint and looked exactly as green as the current one,
so reachability alone never noticed that the repo and the live service had diverged.

Needs no credentials. Every endpoint used here is public and every comparison is against
a file already in the repo.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPO_ROOT / "evidence" / "incidents"
CLAIMS_FILE = REPO_ROOT / "docs" / "CLAIMS.json"
DEFAULT = os.environ.get("NIGHTSHIFT_API_URL", "")

Result = tuple[bool, str]

REACHABILITY = [
    ("meta", "/api/meta"),
    ("overview", "/api/overview"),
    ("fleet", "/api/fleet"),
    ("drills", "/api/drills"),
    ("evidence", "/api/evidence"),
]


def deployed_commit_is_ancestor_of_head(meta: dict[str, Any] | None) -> Result:
    """The commit the deployment was built from must be reachable from local HEAD.

    If it is not, the live service is running a tree this checkout does not contain, and
    every "reproduce it yourself" instruction in the repo points at the wrong source.
    """
    if meta is None:
        return False, "/api/meta did not answer, so there is no deployed commit to check"

    sha = str(meta.get("source_commit") or "").strip()
    if not sha or sha == "unknown":
        return False, (
            f"deployment reports source_commit={sha or '(empty)'}, "
            "which names no tree and cannot be reproduced"
        )

    probe = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode == 0:
        return True, f"deployed {sha} is an ancestor of local HEAD"
    if probe.returncode == 1:
        return False, (
            f"deployed {sha} is not an ancestor of local HEAD; "
            "the live service is running code this checkout does not have"
        )
    stderr = (probe.stderr or "").strip()
    return False, f"git could not resolve {sha}: {stderr or f'exit {probe.returncode}'}"


def served_manifests_match_repo_copies(
    client: httpx.Client, base: str, evidence: dict[str, Any] | None
) -> Result:
    """Every manifest the proof page serves must be byte-identical to the repo copy.

    The proof page is the artifact a judge is asked to trust. A deployment serving a
    manifest that differs from the signed copy in ``evidence/incidents/`` is serving
    something nobody can check out and re-verify.
    """
    if evidence is None:
        return False, "/api/evidence did not answer, so no served manifest could be compared"

    repo_copies = {
        path.name.removesuffix(".manifest.json"): path
        for path in EVIDENCE_DIR.glob("*.manifest.json")
    }
    if not repo_copies:
        return False, f"no manifests in {EVIDENCE_DIR.relative_to(REPO_ROOT)} to compare against"

    served_ids = [
        m.get("incident_id") for m in evidence.get("manifests", []) if m.get("incident_id")
    ]
    shared = [i for i in served_ids if i in repo_copies]
    if not shared:
        return False, (
            f"the deployment serves {len(served_ids)} manifest(s) and the repo holds "
            f"{len(repo_copies)}, and none of them are the same incident"
        )

    for incident_id in shared:
        try:
            response = client.get(f"{base}/api/incidents/{incident_id}/proof")
            response.raise_for_status()
            served = response.json().get("manifest")
        except Exception as exc:
            return False, f"{incident_id}: proof endpoint failed with {type(exc).__name__}: {exc}"

        local = json.loads(repo_copies[incident_id].read_text(encoding="utf-8"))
        if served != local:
            differing = sorted(
                key
                for key in set(local) | set(dict(served or {}))
                if (served or {}).get(key) != local.get(key)
            )
            return False, (
                f"{incident_id}: served manifest differs from the repo copy in "
                f"{', '.join(differing) or 'an unnamed field'}"
            )

    return True, f"{len(shared)} served manifest(s) identical to the repo copies"


def served_claims_match_repo_ledger(evidence: dict[str, Any] | None) -> Result:
    """The claim ledger the deployment publishes must be the one in the repo.

    Every claim carries a reproduce command that only means anything if the deployed
    ledger and the checked-out ledger are the same document.
    """
    if evidence is None:
        return False, "/api/evidence did not answer, so no claims could be compared"
    if not CLAIMS_FILE.exists():
        return False, f"{CLAIMS_FILE.relative_to(REPO_ROOT)} is missing from this checkout"

    local = json.loads(CLAIMS_FILE.read_text(encoding="utf-8")).get("claims", [])
    served = evidence.get("claims", [])

    local_by_id = {c.get("id"): c for c in local}
    served_by_id = {c.get("id"): c for c in served}

    missing = sorted(set(local_by_id) - set(served_by_id))
    extra = sorted(set(served_by_id) - set(local_by_id))
    if missing or extra:
        return False, (
            f"claim ids differ: {len(missing)} in the repo but not served "
            f"({', '.join(missing) or 'none'}), {len(extra)} served but not in the repo "
            f"({', '.join(extra) or 'none'})"
        )

    changed = sorted(cid for cid, claim in local_by_id.items() if served_by_id[cid] != claim)
    if changed:
        return False, f"{len(changed)} claim(s) differ in wording or evidence: {', '.join(changed)}"

    return True, f"{len(local)} claim(s) identical to docs/CLAIMS.json"


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT).rstrip("/")
    if not base:
        print("Set NIGHTSHIFT_API_URL or pass a base URL.", file=sys.stderr)
        return 2

    failures = 0
    total = 0
    bodies: dict[str, dict[str, Any]] = {}

    with httpx.Client(timeout=45.0, follow_redirects=True) as client:
        for label, path in REACHABILITY:
            try:
                response = client.get(f"{base}{path}")
                ok = response.status_code == 200
                detail = ""
                if ok:
                    bodies[label] = response.json()
                if ok and label == "meta":
                    body = bodies[label]
                    detail = (
                        f"model={body.get('model_id')} store={body.get('store_backend')} "
                        f"signer={body.get('signer_backend')} env={body.get('deployment_env')}"
                    )
                elif ok and label == "overview":
                    body = bodies[label]
                    detail = (
                        f"{len(body.get('freezers', []))} freezers, "
                        f"{body.get('total_incidents')} incident(s)"
                    )
            except Exception as exc:
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            print(f"  {'PASS' if ok else 'FAIL'}  {label:<10} {path:<20} {detail}")
            total += 1
            failures += 0 if ok else 1

        provenance: list[tuple[str, Result]] = [
            ("commit-ancestry", deployed_commit_is_ancestor_of_head(bodies.get("meta"))),
            (
                "manifest-parity",
                served_manifests_match_repo_copies(client, base, bodies.get("evidence")),
            ),
            ("claims-parity", served_claims_match_repo_ledger(bodies.get("evidence"))),
        ]

    print()
    for label, (ok, detail) in provenance:
        print(f"  {'PASS' if ok else 'FAIL'}  {label:<16} {detail}")
        total += 1
        failures += 0 if ok else 1

    print()
    print(f"{total - failures}/{total} live checks passed against {base}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
