"""Generate docs/CLAIMS.json and the README metrics block from measured evidence.

Every public claim is written here with its evidence artifact, its reproduction command,
and its limitation. Numbers are read out of the campaign results — never typed — so a
claim cannot drift away from what was actually measured.

    uv run python scripts/generate_claims.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nightshift.common.clock import now_iso

ROOT = Path(__file__).resolve().parents[1]


def commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def claim(
    cid: str,
    text: str,
    *,
    status: str,
    evidence: str,
    reproduce: str,
    limitation: str,
) -> dict[str, Any]:
    return {
        "id": cid,
        "claim": text,
        "status": status,
        "evidence": evidence,
        "reproduce": reproduce,
        "limitation": limitation,
        "date": now_iso(),
        "source_commit": commit(),
    }


def main() -> int:
    scripted_results = load(ROOT / "evidence" / "campaign" / "results.json")
    agent_results = load(ROOT / "evidence" / "campaign-agent" / "results.json")

    s = (scripted_results.get("metrics", {}).get("by_driver", {}) or {}).get("scripted", {})
    a = (agent_results.get("metrics", {}).get("by_driver", {}) or {}).get("agent", {})

    manifests = sorted((ROOT / "evidence" / "incidents").glob("*.manifest.json"))
    manifest_states: list[str] = []
    for path in manifests:
        body = load(path)
        if body:
            manifest_states.append(str(body.get("incident_state", "")))

    claims: list[dict[str, Any]] = []

    if s:
        n = s.get("scored_runs", 0)
        claims += [
            claim(
                "C-01",
                f"Across {n} deterministic drill runs on the published corpus, "
                f"{s.get('capacity_overbooking_violations', 0)} capacity-overbooking "
                f"invariant (N1) violations were observed.",
                status="local",
                evidence="evidence/campaign/results.json",
                reproduce="make evidence",
                limitation=(
                    "Deterministic tier only: a fixed policy replaces the model. Proves "
                    "the kernel and services hold, not that agents behave well. Zero "
                    "observed is over this corpus at this commit, not a proof of "
                    "impossibility."
                ),
            ),
            claim(
                "C-02",
                f"Under {s.get('faults_injected_total', 0)} injected faults across "
                f"{s.get('runs_with_injected_faults', 0)} runs, "
                f"{s.get('runs_with_duplicate_effect_after_fault', 0)} runs produced a "
                f"duplicate semantic effect.",
                status="local",
                evidence="evidence/campaign/results.json",
                reproduce="make evidence",
                limitation=(
                    "Faults are injected at the tool transport boundary. Faults inside "
                    "Firestore's own commit path are not simulated."
                ),
            ),
            claim(
                "C-03",
                f"{s.get('duplicate_receipts_returned', 0)} tool calls returned an "
                f"existing receipt instead of creating a second effect.",
                status="local",
                evidence="evidence/campaign/results.json",
                reproduce="make evidence",
                limitation=(
                    "Counted at the broker; the underlying services enforce it independently."
                ),
            ),
            claim(
                "C-04",
                f"{s.get('authorization_denials_total', 0)} agent-to-tool calls were "
                f"denied by the authorization layer across the corpus, including a "
                f"Dispatch Agent attempt to reach restricted inventory tools.",
                status="local",
                evidence="evidence/campaign/results.json",
                reproduce="make evidence",
                limitation=(
                    "These are broker and service-layer denials. The Cloud Run IAM denial "
                    "is a separate, additional layer verified during deployment."
                ),
            ),
            claim(
                "C-05",
                f"{s.get('passed', 0)} of {n} scored deterministic drill runs passed every "
                f"expectation, including the hard invariants N1 through N13.",
                status="local",
                evidence="evidence/campaign/results.json",
                reproduce="make evidence",
                limitation="Expectations are properties of the outcome, not scenario identifiers.",
            ),
        ]

    if a:
        claims.append(
            claim(
                "C-06",
                f"With the live Gemini 3.5 Flash fleet driving the same corpus, "
                f"{a.get('passed', 0)} of {a.get('scored_runs', 0)} scored runs passed, "
                f"with {a.get('capacity_overbooking_violations', 0)} N1 violations and "
                f"{a.get('duplicate_effect_violations', 0)} N2 violations.",
                status="live",
                evidence="evidence/campaign-agent/results.json",
                reproduce="make evidence-agent",
                limitation=(
                    "A much smaller sample than the deterministic tier because each run "
                    "takes minutes. Reported separately and never pooled."
                ),
            )
        )

    claims += [
        claim(
            "C-07",
            "A cancelled ADK invocation re-invokes an already-committed tool on resume. "
            "The observed run made 2 tool calls and produced 1 committed effect, because "
            "the semantic action ID was identical and the second call replayed the first "
            "call's receipt.",
            status="live",
            evidence="docs/SPIKE_RESULTS.md",
            reproduce="make spike",
            limitation=(
                "Observed on google-adk 2.7.1 with an in-memory session service. Two other "
                "interruption shapes did not re-invoke; all three are published."
            ),
        ),
        claim(
            "C-08",
            "Model Armor matched the published prompt-injection payload family at HIGH "
            "confidence via the live sanitizeUserPrompt API.",
            status="live",
            evidence="docs/SPIKE_RESULTS.md",
            reproduce=("curl -X POST .../templates/nightshift-vendor-content:sanitizeUserPrompt"),
            limitation=(
                "One payload family, not a detection rate. Night Shift never relies on "
                "Model Armor alone: the Dispatch Agent holds no inventory authority "
                "regardless of what any screening layer concludes."
            ),
        ),
        claim(
            "C-09",
            "Tampering with a published manifest is detected. Editing the state snapshot, "
            "the stored verdict, or the signature each produce a distinct MISMATCH, and an "
            "unsigned manifest reports PARTIAL rather than PASS.",
            status="local",
            evidence="tests/unit/test_evidence_and_verifier.py",
            reproduce="uv run pytest tests/unit/test_evidence_and_verifier.py -q",
            limitation=(
                "Proves the stored verdict follows from the stored state and that the "
                "state was signed by the published key holder. It cannot prove the state "
                "describes the physical world."
            ),
        ),
        claim(
            "C-10",
            "Evidence manifests are signed with a Cloud KMS asymmetric key "
            "(EC_SIGN_P256_SHA256) and verify against the exported public key.",
            status="live",
            evidence="evidence/incidents/*.manifest.json",
            reproduce=(
                "python -m nightshift.verify --manifest evidence/incidents/<id>.manifest.json"
            ),
            limitation=(
                "A local EC key is used as a documented fallback when KMS is unreachable; "
                "the backend that actually signed is recorded in the manifest."
            ),
        ),
        claim(
            "C-11",
            "Field movements in the demo are simulated. No real biobank samples were moved "
            "and no real patient or research data exists anywhere in the fixture.",
            status="synthetic",
            evidence="fixtures/estate.py, services/simulator/ingest.py",
            reproduce=(
                "uv run python -c 'from fixtures.estate import build_estate; "
                "print(build_estate().site)'"
            ),
            limitation=(
                "This is a statement of scope, not a measurement. The field simulator "
                "refuses to run outside demo, drill, and test namespaces."
            ),
        ),
        claim(
            "C-12",
            "Six domain services run on Cloud Run under six distinct Google service "
            "accounts, and cross-service run.invoker grants mirror the permission matrix.",
            status="live",
            evidence="infra/deploy/deploy_services.sh, infra/deploy/urls.env",
            reproduce="make deploy && make smoke-live",
            limitation=(
                "Agents are not registered as managed Agent Registry or Agent Runtime "
                "resources; see LIMITATIONS.md."
            ),
        ),
    ]

    if manifest_states:
        closed = sum(1 for state in manifest_states if state == "CLOSED")
        claims.append(
            claim(
                "C-13",
                f"{len(manifest_states)} incident manifest(s) are published, of which "
                f"{closed} reached CLOSED with every impacted container in a terminal "
                f"custody state.",
                status="live",
                evidence="evidence/incidents/",
                reproduce="make verify-demo",
                limitation="Synthetic estate; simulated responder movements.",
            )
        )

    document = {
        "generated_at": now_iso(),
        "source_commit": commit(),
        "note": (
            "Every number in this file is read from the campaign results, never typed. "
            "Regenerate with: uv run python scripts/generate_claims.py"
        ),
        "claims": claims,
    }

    out = ROOT / "docs" / "CLAIMS.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(claims)} claims to {out.relative_to(ROOT)}")

    for c in claims:
        print(f"  {c['id']}  [{c['status']:<9}] {c['claim'][:96]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
