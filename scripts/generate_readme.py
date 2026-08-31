"""Generate README.md with measured numbers filled in from evidence.

The README's headline figures are read from the campaign results rather than typed, so a
number in the README cannot drift away from what was actually measured. Prose lives in
the template below; only the bracketed metrics are substituted.

    uv run python scripts/generate_readme.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

# The template is hand-wrapped at 90 columns. Substituted paragraphs are wrapped to match,
# so a generated sentence is not visibly a generated sentence in the raw file.
WRAP = 90

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def count(value: Any) -> int:
    """Reconciliation buckets are id lists in the current manifest schema, counts in older
    ones. Reading either shape keeps a schema change from silently reporting zero."""
    if isinstance(value, list):
        return len(value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def plural(n: int, singular: str, suffix: str = "s") -> str:
    return singular if n == 1 else singular + suffix


def wrap(text: str) -> str:
    return textwrap.fill(" ".join(text.split()), width=WRAP)


def first_commit() -> tuple[str, str]:
    """Origination provenance has to come out of git. A typed date is exactly the kind of
    unbacked claim this repository exists to argue against."""
    try:
        lines = subprocess.run(
            ["git", "log", "--reverse", "--format=%h %ad", "--date=short"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        sha, date = lines[0].split(None, 1)
        return sha, date.strip()
    except Exception:
        return "", ""


def main() -> int:
    scripted_results = load(ROOT / "evidence" / "campaign" / "results.json")
    scripted = scripted_results.get("metrics", {}).get("by_driver", {}).get("scripted", {})
    agent = (
        load(ROOT / "evidence" / "campaign-agent" / "results.json")
        .get("metrics", {})
        .get("by_driver", {})
        .get("agent", {})
    )
    api_url = ""
    web_url = ""
    urls = ROOT / "infra" / "deploy" / "urls.env"
    if urls.exists():
        for line in urls.read_text(encoding="utf-8").splitlines():
            if line.startswith("NIGHTSHIFT_API_URL="):
                api_url = line.split("=", 1)[1].strip()
            elif line.startswith("NIGHTSHIFT_WEB_URL="):
                web_url = line.split("=", 1)[1].strip()

    manifests = sorted((ROOT / "evidence" / "incidents").glob("*.manifest.json"))
    closed = 0
    containers_committed = 0
    containers_total = 0
    for path in manifests:
        body = load(path)
        reconciliation = body.get("reconciliation") or {}
        if body.get("incident_state") == "CLOSED":
            closed += 1
        containers_total += count(reconciliation.get("total"))
        # `total` counts every impacted container whatever its custody state, so summing it
        # and calling the result "reconciled" reports in-flight material as finished.
        containers_committed += count(reconciliation.get("committed"))

    if not scripted:
        print("No campaign results found. Run `make evidence` first.", file=sys.stderr)
        return 1

    scored = scripted.get("scored_runs", 0)
    replays = scripted.get("duplicate_receipts_returned", 0)
    scripted_runs = scripted_results.get("runs", []) or []
    replay_drills = sorted(
        {r.get("drill_id", "") for r in scripted_runs if r.get("duplicate_receipts")}
    )
    replay_faults = sum(
        r.get("faults_injected", 0) for r in scripted_runs if r.get("duplicate_receipts")
    )

    headline = (
        f"Across {scored} disclosed disaster-drill runs it passed {scripted.get('passed', 0)}, "
        f"with {scripted.get('capacity_overbooking_violations', 0)} capacity-overbooking "
        f"violations and {scripted.get('runs_with_duplicate_effect_after_fault', 0)} duplicate "
        f"effects under {scripted.get('faults_injected_total', 0)} injected faults. That is the "
        f"deterministic tier, a fixed policy drives the same broker, services and kernel with "
        f"no model in the loop."
    )
    headline = wrap(headline)

    # The replay count and the fault count used to share a sentence, which read as though
    # the faults caused the replays. They are independent measurements and stay apart.
    replay_line = (
        f"Separately, {replays} tool {plural(replays, 'call')} returned an existing receipt "
        f"instead of committing a second effect."
    )
    if replay_drills and replay_faults == 0:
        replay_line += (
            f" Every one came from drill {', '.join(replay_drills)}, which injects no faults "
            f"at all, so these are the idempotency path working on ordinary retries rather "
            f"than a response to anything going wrong."
        )
    replay_line = "\n" + wrap(replay_line) + "\n"

    agent_line = ""
    if agent:
        agent_line = (
            f"A separate live-agent tier ran {agent.get('scored_runs', 0)} runs across "
            f"{len(agent.get('per_drill') or {})} of the "
            f"{len(scripted.get('per_drill') or {})} corpus drills, holdout excluded, against "
            f"the real Gemini 3.5 Flash fleet. It passed {agent.get('passed', 0)} with "
            f"{agent.get('capacity_overbooking_violations', 0)} N1 and "
            f"{agent.get('duplicate_effect_violations', 0)} N2 violations. The two tiers "
            f"are reported separately and never pooled."
        )
        agent_line = "\n" + wrap(agent_line) + "\n"

    iam = load(ROOT / "evidence" / "iam-denial.json")
    iam_denials = sum(
        1
        for probe in iam.get("probes", [])
        if probe.get("matrix_expectation") == "forbidden" and probe.get("denied_by_platform")
    )
    denials_cell = (
        f"{scripted.get('authorization_denials_total', 0)} broker denials across "
        f"{scripted.get('runs_with_authorization_denials', 0)} of {scored} runs"
    )
    if iam_denials:
        denials_cell += f", plus {iam_denials} Cloud Run IAM edge {plural(iam_denials, 'denial')}"

    # One median hid the fact that the two tiers differ by three orders of magnitude, which
    # is the most informative thing about them.
    median_cell = f"{scripted.get('wall_clock_median_s', 'n/a')}s deterministic tier"
    if agent:
        median_cell += f", {agent.get('wall_clock_median_s', 'n/a')}s live-agent tier"

    manifests_cell = (
        f"{len(manifests)} ({closed} CLOSED, {containers_committed} of {containers_total} "
        f"containers committed)"
    )

    sha, sha_date = first_commit()
    track_line = (
        "Track: Fortified Enterprise Fleet. All application code was written during the "
        "submission period."
    )
    if sha:
        track_line += f" First commit `{sha}`, {sha_date}."
    track_line = wrap(track_line)

    envelope = _envelope(agent)

    links = []
    if web_url:
        links.append(f"**[Live product]({web_url})**")
    if api_url:
        links.append(f"[Public API]({api_url}/api/meta)")
    links.append("[Architecture](ARCHITECTURE.md)")
    links.append("[Proof](docs/PROOF.md)")
    links.append("[Claims](docs/CLAIMS.json)")

    readme = TEMPLATE.format(
        headline=headline,
        replay_line=replay_line,
        agent_line=agent_line,
        track_line=track_line,
        envelope=envelope,
        links=" · ".join(links),
        manifests_cell=manifests_cell,
        manifest_count=len(manifests),
        denials=denials_cell,
        reconciled=scripted.get("runs_fully_reconciled", 0),
        scored=scored,
        median=median_cell,
        api_line=_deployment_block(web_url, api_url),
        architecture_figure=_theme_aware_figure(
            "architecture",
            "Night Shift runtime map: telemetry enters an agent fleet, every proposed "
            "action passes a tool broker and the safety kernel before Firestore commits "
            "it, and the resulting state is signed by Cloud KMS and checked by an "
            "offline verifier.",
        ),
        exactly_once_figure=_theme_aware_figure(
            "exactly-once",
            "The commit sequence run twice. The first attempt finds no receipt, "
            "evaluates kernel preconditions, and commits the effect and its receipt "
            "together. After the worker restarts, the same action finds the existing "
            "committed receipt and returns it without consulting the kernel or writing "
            "anything.",
        ),
    )
    (ROOT / "README.md").write_text(readme, encoding="utf-8")
    print(f"Wrote README.md ({len(readme.splitlines())} lines)")
    return 0


def _envelope(agent: dict[str, Any]) -> str:
    """What the live-agent tier was actually observed to do, and nothing beyond it.

    Every figure here is read straight out of evidence/campaign-agent/metrics.json. Nothing
    is derived, averaged, or extrapolated, because the moment a number in this paragraph is
    computed rather than measured it stops being an operating envelope and becomes a
    forecast.
    """
    if not agent:
        return ""
    committed = agent.get("containers_committed_total", 0)
    unresolved = agent.get("containers_unresolved_total", 0)
    return "\n".join(
        [
            "",
            "## Operating envelope",
            "",
            wrap(
                f"Over the live-agent tier the fleet committed {committed} container custody "
                f"{plural(committed, 'transition')} and finished with {unresolved} "
                f"{plural(unresolved, 'container')} unresolved. The median run took "
                f"{agent.get('wall_clock_median_s', 'n/a')} seconds. No human approved, "
                "corrected, or intervened in any of those runs. That is the whole envelope. "
                "Anything outside it has not been measured and is not claimed."
            ),
            "",
        ]
    )


def _theme_aware_figure(stem: str, alt: str) -> str:
    """A diagram that follows the reader's GitHub theme.

    GitHub strips most HTML from Markdown but honours <picture> with a
    prefers-color-scheme source, which is the only way to keep a light diagram off a dark
    page. The <img> fallback matters: any renderer that ignores <picture> still shows the
    light asset rather than nothing.
    """
    base = f"docs/diagrams/preview/{stem}"
    return "\n".join(
        [
            "<picture>",
            f'  <source media="(prefers-color-scheme: dark)" srcset="{base}.dark.png">',
            f'  <source media="(prefers-color-scheme: light)" srcset="{base}.light.png">',
            f'  <img alt="{alt}" src="{base}.light.png">',
            "</picture>",
        ]
    )


def _deployment_block(web_url: str, api_url: str) -> str:
    """The live links, in the first screen of the README."""
    if not (web_url or api_url):
        return ""
    rows = ["", "## Deployed", "", "| | |", "|---|---|"]
    if web_url:
        rows += [
            f"| Product (start here) | <{web_url}> |",
            f"| Live incident | <{web_url}/app/incidents> |",
            f"| Fleet and permission matrix | <{web_url}/app/fleet> |",
            f"| Disaster drills | <{web_url}/app/drills> |",
            f"| Evidence and claim ledger | <{web_url}/app/evidence> |",
            f"| Verify a manifest | <{web_url}/verify> |",
        ]
    if api_url:
        rows.append(f"| Public API | <{api_url}/api/meta> |")
    rows += [
        "",
        "Google Cloud `project-2ac1d1fb-7da1-46b4-90e`, region `us-central1`. Six domain "
        "services and the public API run as separate Cloud Run services under separate "
        "service accounts.",
        "",
    ]
    return "\n".join(rows)


TEMPLATE = """# Night Shift

**Night Shift coordinates research-freezer rescue from alarm to reconciled custody.**

{track_line}

A freezer alarm tells a lab that something is wrong. The hard part is everything that has
to happen next: work out whether it is real, find out what is inside, locate space that is
actually safe, get someone on site, track every box that moves, and know, provably, that
nothing was left behind.

{headline}
{replay_line}{agent_line}
{links}
{api_line}
---

## Who this is for

The unlikely hero here is a biobank lab manager at 2am. Not a developer, and not a standard
corporate role either. A laboratory operations manager, biobank technician, or
research-core facility responder who takes the freezer alarm and personally becomes the
orchestration layer for the next several hours: deciding whether the event is real,
identifying affected material, locating backup capacity, contacting the right people,
starting the repair, preserving sample identity, coordinating physical movement, recording
where every box went, tracking what is still unaccounted for, restoring normal operations,
and writing it all up afterwards.

They do that alone, at night, from a phone, while the material degrades. The buyers behind
them are university research core facilities, institutional biobanks, biotech and pharma
R&D sites, hospital research repositories, and the freezer-monitoring and LIMS vendors who
want a response layer to hand their customers.

It helps to say what this is not, because the shape of the user follows from it. Night
Shift is not a temperature sensor vendor, a freezer monitoring dashboard, a chatbot for
scientists, a generic multi-agent framework, a LIMS replacement, a robotics system, a
compliance certification product, or an agent testing product wearing a laboratory skin.
The product is incident response. The assurance plane exists to make incident response
trustworthy.

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
verifier both call, the same code, on the same inputs.

{architecture_figure}

The same map is also an interactive artifact with guided views that walk one path at a
time: [`docs/diagrams/night-shift-architecture.html`](docs/diagrams/night-shift-architecture.html).
It is a single self-contained file, so it opens straight from disk with no server and no
network.

## What actually runs

Six ADK specialists on Gemini 3.5 Flash, six Cloud Run domain services under six distinct
Google service accounts, Firestore transactions enforcing capacity conservation, Cloud KMS
signing every evidence manifest, Cloud Storage holding the published evidence bundles,
Cloud Trace carrying the spans, and Model Armor screening untrusted vendor content.

Eleven Google services are in the deployed path: Vertex AI, Cloud Run, Cloud IAM,
Firestore, Pub/Sub, Cloud KMS, Cloud Storage, Cloud Trace, Model Armor, Artifact Registry,
and Cloud Build.

Model access path: Gemini 3.5 Flash through Vertex AI, with
`GOOGLE_GENAI_USE_VERTEXAI=TRUE` and the model served from the `global` endpoint. Regional
infrastructure stays in `us-central1`. The split is deliberate and documented in
`nightshift/common/config.py`.

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
reply asking it to export the specimen list has nothing to reach, at four independent
layers, ending with Cloud Run IAM refusing the call before it reaches our code.

## Thirteen invariants, checked twice

| | Invariant | What it prevents |
|---|---|---|
| N1 | Capacity conservation | Two incidents booking the same slots |
| N2 | Exactly-once effects | A retry creating a second real effect |
| N3 | Valid custody prerequisite | Recording a move the evidence does not support |
| N4 | Fresh destination evidence | Committing into a freezer that has warmed |
| N5 | Complete reconciliation | Closing with material unaccounted for |
| N6 | No premature close | Closing while anything is uncertain |
| N7 | Least-privilege effect authority | The wrong agent producing an effect |
| N8 | Memory non-authority | Acting on remembered rather than current state |
| N9 | Duplicate event safety | Redelivery multiplying effects |
| N10 | Revision qualification | An unqualified revision taking real work |
| N11 | Fail closed on contradiction | Inventing success from partial evidence |
| N12 | Failure attribution | Blaming the agent for infrastructure failing |
| N13 | Containment integrity | Normal traffic continuing on a failed freezer |

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

Only the third, a worker actually dying, re-invokes. That run made 2 tool calls and
produced 1 committed effect, because the semantic action ID was identical and the second
call replayed the first call's receipt.

If you test resume safety by raising from a plugin, you will observe no re-invocation and
conclude idempotency is optional. Then a pod eviction produces the third shape and you
have booked the freezer twice. Details in [CONTRIBUTIONS.md](CONTRIBUTIONS.md).

This is what the third shape looks like. The same semantic action arrives twice; the
second pass finds the receipt at step 3 and never reaches the kernel or the write:

{exactly_once_figure}

Interactive version:
[`night-shift-exactly-once.html`](docs/diagrams/night-shift-exactly-once.html).

## Spin it up

Two paths. The first needs no Google Cloud account, no credentials, and no billing.

### Local, credential-free

Prerequisites: [uv](https://docs.astral.sh/uv/) 0.5 or newer. Node 20 or newer and pnpm 9
or newer are needed only if you also want to run the web app locally. No `gcloud`, no
Google Cloud account, no billing.

```bash
git clone https://github.com/winsznx/night-shift.git
cd night-shift
```

```bash
make setup-python
```
Installs Python 3.12 through uv and syncs every dependency group. Ends with a short list of
the credential-free targets. Use `make setup` instead if you also want the web app's
Node dependencies.

```bash
make test
```
Unit, property, and integration tests, no credentials touched. Expect a pytest summary
line in under ten seconds, `234 passed` at this commit. The count grows with the suite.
What matters is zero failures.

```bash
make drills
```
Runs the whole disaster-drill corpus on the deterministic tier, one seed per drill. Prints
a progress line per run, then:
```
total runs: 21
  scripted: 21/21 passed, 0 infrastructure error(s), N1 violations=0, N2 violations=0
```

```bash
make verify-demo
```
Recomputes every invariant and every hash for each published manifest with no model and no
network, and checks the Cloud KMS signature against the pinned public key. Prints a full
PASS/FAIL line per check, then:
```
{manifest_count}/{manifest_count} manifest(s) verified PASS.
```
The same document also verifies straight over HTTPS, with no clone:
```bash
uv run python -m nightshift.verify --manifest https://storage.googleapis.com/nightshift-public-evidence-project-2ac1d1fb-7da1-46b4-90e/incidents/INC-0E7C54F8B5/manifest.json
```
That bucket is world-readable and holds manifests, signatures and public keys only. The
bucket holding the Firestore export is a different bucket and is private.

### Cloud

Needs a Google Cloud project with billing enabled. Full detail, including every
environment variable, is in [SETUP.md](SETUP.md).

```bash
gcloud auth login
```
Standard gcloud browser flow. Ends with your account listed as active.

```bash
make bootstrap
```
Enables the APIs and provisions Firestore, the Pub/Sub topics and subscriptions, the
evidence bucket, the Cloud KMS signing key, the Model Armor template, and the Artifact
Registry repository. Exports the signing public key to
`keys/kms-evidence-signer.pub.pem` and prints the `.env` block to copy.

```bash
make deploy
```
Builds one image with Cloud Build and deploys seven Cloud Run services: six authenticated
domain services under six distinct service accounts, plus the public API. Writes every
resolved URL to `infra/deploy/urls.env` and prints them under a `Deployed` heading. This
target does not ship the frontend.

```bash
make deploy-web
```
Separate target, separate Cloud Run service. Builds the Next.js app and deploys it pointed
at the API URL from the previous step, then appends `NIGHTSHIFT_WEB_URL` to
`infra/deploy/urls.env` and prints both URLs.

```bash
make smoke-live
```
Two groups of checks. First it hits `/api/meta`, `/api/overview`, `/api/fleet`,
`/api/drills`, and `/api/evidence` on the deployed API, printing a PASS line per endpoint
with the live model id, store backend, and signer backend on the first. Then it checks
provenance: that the deployed commit is an ancestor of your HEAD, that the manifests the
API serves are byte-identical to the ones in the repo, and that the served claim ledger
matches `docs/CLAIMS.json`. Ends with:
```
8/8 live checks passed against https://<your-api-host>
```
A non-zero exit means the deployment and the repo disagree about something.

## Measured, not asserted

| | |
|---|---|
| Drill runs fully reconciled | {reconciled} of {scored} |
| Authorization denials recorded | {denials} |
| Published manifests | {manifests_cell} |
| Median drill wall clock | {median} |

Every number above is read from `evidence/campaign/results.json`,
`evidence/campaign-agent/results.json`, `evidence/iam-denial.json`, and the published
manifests by `scripts/generate_readme.py`. None of them is typed. Raw rows, methodology,
and the claim ledger with reproduction commands are in [`evidence/`](evidence/) and
[`docs/CLAIMS.json`](docs/CLAIMS.json).
{envelope}

## Honest boundaries

The estate, specimens, studies, and responder roster are synthetic. Responder movements
are simulated, and no real biobank samples were moved. Agents are not registered as managed
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
