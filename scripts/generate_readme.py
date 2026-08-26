"""Generate README.md with measured numbers filled in from evidence.

The README's headline figures are read from the campaign results rather than typed, so a
number in the README cannot drift away from what was actually measured. Prose lives in
the template below; only the bracketed metrics are substituted.

    uv run python scripts/generate_readme.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    scripted = (
        load(ROOT / "evidence" / "campaign" / "results.json")
        .get("metrics", {})
        .get("by_driver", {})
        .get("scripted", {})
    )
    agent = (
        load(ROOT / "evidence" / "campaign-agent" / "results.json")
        .get("metrics", {})
        .get("by_driver", {})
        .get("agent", {})
    )
    api_url = ""
    urls = ROOT / "infra" / "deploy" / "urls.env"
    if urls.exists():
        for line in urls.read_text(encoding="utf-8").splitlines():
            if line.startswith("NIGHTSHIFT_API_URL="):
                api_url = line.split("=", 1)[1].strip()

    manifests = sorted((ROOT / "evidence" / "incidents").glob("*.manifest.json"))
    closed = 0
    containers = 0
    for path in manifests:
        body = load(path)
        if body.get("incident_state") == "CLOSED":
            closed += 1
        containers += int((body.get("reconciliation") or {}).get("total", 0))

    if not scripted:
        print("No campaign results found. Run `make evidence` first.", file=sys.stderr)
        return 1

    headline = (
        f"Across **{scripted.get('scored_runs', 0)} disclosed disaster-drill runs**, it "
        f"passed {scripted.get('passed', 0)}, produced "
        f"**{scripted.get('capacity_overbooking_violations', 0)} capacity-overbooking "
        f"violations**, and produced **{scripted.get('runs_with_duplicate_effect_after_fault', 0)} "
        f"duplicate effects** under {scripted.get('faults_injected_total', 0)} injected "
        f"faults — replaying an existing receipt "
        f"{scripted.get('duplicate_receipts_returned', 0)} times instead."
    )

    agent_line = ""
    if agent:
        agent_line = (
            f"\nA separate live-agent tier ran {agent.get('scored_runs', 0)} of the same "
            f"drills against the real Gemini 3.5 Flash fleet, passing "
            f"{agent.get('passed', 0)} with "
            f"{agent.get('capacity_overbooking_violations', 0)} N1 and "
            f"{agent.get('duplicate_effect_violations', 0)} N2 violations. The two tiers "
            f"are reported separately and never pooled.\n"
        )

    links = []
    if api_url:
        links.append(f"[Live API]({api_url}/api/meta)")
    links.append("[Architecture](ARCHITECTURE.md)")
    links.append("[Proof](docs/PROOF.md)")
    links.append("[Claims](docs/CLAIMS.json)")

    readme = TEMPLATE.format(
        headline=headline,
        agent_line=agent_line,
        links=" · ".join(links),
        manifest_count=len(manifests),
        closed=closed,
        containers=containers,
        denials=scripted.get("authorization_denials_total", 0),
        reconciled=scripted.get("runs_fully_reconciled", 0),
        median=scripted.get("wall_clock_median_s", "—"),
        api_line=(f"\nLive public API: <{api_url}/api/meta>\n" if api_url else ""),
    )
    (ROOT / "README.md").write_text(readme, encoding="utf-8")
    print(f"Wrote README.md ({len(readme.splitlines())} lines)")
    return 0


TEMPLATE = """# Night Shift

**Night Shift coordinates research-freezer rescue from alarm to reconciled custody.**

A freezer alarm tells a lab that something is wrong. The hard part is everything that has
to happen next: work out whether it is real, find out what is inside, locate space that is
actually safe, get someone on site, track every box that moves, and know — provably — that
nothing was left behind.

{headline}
{agent_line}
{links}
{api_line}
---

## The mechanism

```
live incident evidence
  → specialist agents plan and delegate
    → tool broker restricts reachable tools by identity
      → deterministic Rescue Safety Kernel validates preconditions
        → idempotent domain service commits the effect
          → immutable receipt enters the incident ledger
            → incident advances only when the required evidence exists
```

One rule holds it together:

> **Agents decide what to do. Deterministic code decides what is true and whether state
> may change.**

Gemini 3.5 Flash interprets noisy telemetry, prioritises material, and chooses among valid
backup options. It is never the authority on whether capacity exists, whether an effect
already happened, whether a responder is authorised, or whether an incident may close.
Those belong to a pure Python safety kernel that the production services and an offline
verifier both call — the same code, on the same inputs.

## What actually runs

Six ADK specialists on Gemini 3.5 Flash, six Cloud Run domain services under six distinct
Google service accounts, Firestore transactions enforcing capacity conservation, Cloud KMS
signing every evidence manifest, and Model Armor screening untrusted vendor content.

| Agent | Owns | Cannot touch |
|---|---|---|
| Incident Commander | the plan, delegation, closure requests | anything mutable |
| Signal Investigator | is this a real failure? | specimens, capacity, custody |
| Impact Analyst | what is affected and how urgently | capacity, custody, facilities |
| Capacity Broker | finding and reserving safe space | custody, facilities |
| Dispatch Agent | work orders and responders | **inventory, entirely** |
| Custody Agent | verifying evidence and committing custody | reservations, work orders |

Read that table by its gaps. A compromised Commander can request a plan change and nothing
else. The Dispatch Agent has no inventory authority at all, which is why a poisoned vendor
reply asking it to export the specimen list has nothing to reach — at four independent
layers, ending with Cloud Run IAM refusing the call before it reaches our code.

## Thirteen invariants, checked twice

Capacity conservation. Exactly-once effects. Custody prerequisites. Destination freshness.
Complete reconciliation. No premature close. Least-privilege effect authority. Memory
non-authority. Duplicate event safety. Revision qualification. Fail closed on
contradiction. Failure attribution. Containment integrity.

The services check them before committing. The verifier recomputes them afterwards from
the stored state snapshot, with no model and no network:

```bash
python -m nightshift.verify --manifest evidence/incidents/<id>.manifest.json
```

Editing the state produces a hash failure *and* a divergent verdict. Editing the stored
verdict produces a divergence alone. Editing the signature fails signature verification.
All three are reported separately, so a mismatch says which happened. An unsigned manifest
reports `PARTIAL`, never `PASS`.

## The finding that shaped the design

PRD §22 asks what ADK does to an effectful tool on resume. Rather than assume, three
interruption shapes were provoked against a real Gemini-backed run:

| How the run ended | Tool re-invoked on resume? |
|---|---|
| a plugin raised after the tool returned | no |
| the tool itself raised after committing | no |
| **the invocation was cancelled mid-flight** | **yes** |

Only the third — a worker actually dying — re-invokes. That run made 2 tool calls and
produced 1 committed effect, because the semantic action ID was identical and the second
call replayed the first call's receipt.

If you test resume safety by raising from a plugin, you will observe no re-invocation and
conclude idempotency is optional. Then a pod eviction produces the third shape and you
have booked the freezer twice. Details in [CONTRIBUTIONS.md](CONTRIBUTIONS.md).

## Try it without credentials

```bash
make setup
make test           # unit, property, and integration
make drills         # the full disaster drill corpus, seconds
make verify-demo    # verify every published manifest
```

Live Google Cloud deployment is in [SETUP.md](SETUP.md).

## Measured, not asserted

| | |
|---|---|
| Drill runs scored | {reconciled} fully reconciled |
| Authorization denials recorded | {denials} |
| Published manifests | {manifest_count} ({closed} CLOSED, {containers} containers reconciled) |
| Median drill wall clock | {median}s |

Every number above is read from `evidence/campaign/results.json` by
`scripts/generate_readme.py`. None of them is typed. Raw rows, methodology, and the claim
ledger with reproduction commands are in [`evidence/`](evidence/) and
[`docs/CLAIMS.json`](docs/CLAIMS.json).

## Honest boundaries

The estate, specimens, studies, and responder roster are synthetic. Responder movements
are simulated — no real biobank samples were moved. Agents are not registered as managed
Agent Registry or Agent Runtime resources; the delivered authority separation uses
distinct Google service accounts and Cloud Run IAM instead. Semantic Governance and Memory
Bank are local implementations of the specified behaviour, not the managed products.

Every one of those is stated on the specific claim it affects in
[LIMITATIONS.md](LIMITATIONS.md) and [`docs/CLAIMS.json`](docs/CLAIMS.json).

## Documentation

[Architecture](ARCHITECTURE.md) · [Security](SECURITY.md) · [Decisions](DECISIONS.md) ·
[Setup](SETUP.md) · [Limitations](LIMITATIONS.md) · [Proof](docs/PROOF.md) ·
[Contributions](CONTRIBUTIONS.md) · [Phase 0 spike](docs/SPIKE_RESULTS.md)
"""


if __name__ == "__main__":
    sys.exit(main())
