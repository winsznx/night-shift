# Night Shift

**Night Shift coordinates research-freezer rescue from alarm to reconciled custody.**

A freezer alarm tells a lab that something is wrong. The hard part is everything that has
to happen next: work out whether it is real, find out what is inside, locate space that is
actually safe, get someone on site, track every box that moves, and know — provably — that
nothing was left behind.

Across **126 disclosed disaster-drill runs**, it passed 126, produced **0 capacity-overbooking violations**, and produced **0 duplicate effects** under 54 injected faults — replaying an existing receipt 6 times instead.

A separate live-agent tier ran 18 of the same drills against the real Gemini 3.5 Flash fleet, passing 17 with 0 N1 and 0 N2 violations. The two tiers are reported separately and never pooled.

**[Live product](https://nightshift-web-xk6xxtobta-uc.a.run.app)** · [Public API](https://nightshift-api-xk6xxtobta-uc.a.run.app/api/meta) · [Architecture](ARCHITECTURE.md) · [Proof](docs/PROOF.md) · [Claims](docs/CLAIMS.json)

## Deployed

| | |
|---|---|
| Product (start here) | <https://nightshift-web-xk6xxtobta-uc.a.run.app> |
| Live incident | <https://nightshift-web-xk6xxtobta-uc.a.run.app/app/incidents> |
| Fleet and permission matrix | <https://nightshift-web-xk6xxtobta-uc.a.run.app/app/fleet> |
| Disaster drills | <https://nightshift-web-xk6xxtobta-uc.a.run.app/app/drills> |
| Evidence and claim ledger | <https://nightshift-web-xk6xxtobta-uc.a.run.app/app/evidence> |
| Verify a manifest | <https://nightshift-web-xk6xxtobta-uc.a.run.app/verify> |
| Public API | <https://nightshift-api-xk6xxtobta-uc.a.run.app/api/meta> |

Google Cloud `project-2ac1d1fb-7da1-46b4-90e`, region `us-central1`. Six domain services and the public API run as separate Cloud Run services under separate service accounts.

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

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/preview/architecture.dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/diagrams/preview/architecture.light.png">
  <img alt="Night Shift runtime map: telemetry enters an agent fleet, every proposed action passes a tool broker and the safety kernel before Firestore commits it, and the resulting state is signed by Cloud KMS and checked by an offline verifier." src="docs/diagrams/preview/architecture.light.png">
</picture>

The same map is also an interactive artifact with guided views that walk one path at a
time: [`docs/diagrams/night-shift-architecture.html`](docs/diagrams/night-shift-architecture.html).
It is a single self-contained file, so it opens straight from disk with no server and no
network.

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

This is what the third shape looks like. The same semantic action arrives twice; the
second pass finds the receipt at step 3 and never reaches the kernel or the write:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/preview/exactly-once.dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/diagrams/preview/exactly-once.light.png">
  <img alt="The commit sequence run twice. The first attempt finds no receipt, evaluates kernel preconditions, and commits the effect and its receipt together. After the worker restarts, the same action finds the existing committed receipt and returns it without consulting the kernel or writing anything." src="docs/diagrams/preview/exactly-once.light.png">
</picture>

Interactive version:
[`night-shift-exactly-once.html`](docs/diagrams/night-shift-exactly-once.html).

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
| Drill runs scored | 60 fully reconciled |
| Authorization denials recorded | 24 |
| Published manifests | 3 (1 CLOSED, 126 containers reconciled) |
| Median drill wall clock | 0.54s |

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
