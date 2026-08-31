# Measurement methodology

## What is measured

Whether the deterministic layer's hard invariants hold under fault injection, across many
seeds and every drill in the corpus, and whether the live agent fleet drives that same
machinery correctly.

## Two tiers, reported separately

| Tier | Driver | Scale | What it proves |
|---|---|---|---|
| `scripted` | fixed policy, no model | whole corpus × many seeds | the kernel and services hold under faults |
| `agent` | real Gemini 3.5 Flash fleet | subset × few seeds | the agents drive the same machinery |

The scripted tier is **not a mock**. It makes real tool calls through the real broker with
real authorization, real semantic policy evaluation, and real fault injection, against the
real FastAPI services and the real Safety Kernel. Only the choice of *which* call to make
next is fixed rather than reasoned.

They are never pooled into a single percentage. A full agent run takes about four minutes
against under a second for the scripted equivalent, so combining them would let the cheap
tier's volume flatter the expensive tier's behaviour — precisely the kind of number this
project exists to avoid.

## Isolation

Every drill run gets its own namespace, which is a collection prefix rather than a field
filter. A drill physically cannot read or write another drill's state, let alone
operational state.

## Fault injection

Faults are keyed on `(tool_name, action_id, call_number_within_action)`, never on
wall-clock timing. "Fail the second call to `reserve_capacity` for this placement group"
reproduces exactly; "fail 400ms in" reproduces differently on every machine.

Two kinds:

- `commit_loss` — the tool runs to completion and its response is discarded. The effect
  exists and nobody knows. This is the case PRD §22 asks about, and producing it requires
  wrapping the transport rather than raising before it.
- `tool_failure` — the tool never runs. A plain infrastructure error.

A `call_number` of `0` means every call, which is how a service that is genuinely down
behaves. Faulting only the first call would let a bare retry succeed and prove nothing.

## Controls

A pass rate over a corpus of "things that should work" measures very little. The corpus
carries a control structure, and these are the terms used for it here and in
`docs/PROOF.md`.

| Control | Drill | What it rules out |
|---|---|---|
| positive | D2, `Confirmed freezer failure` | a system that is inert. D2 fails when nothing happens, so it is the drill that makes the rest mean something |
| negative | D1, `Transient door excursion` | a system that always rescues. D1's expectations are all absences, so eagerness fails it |
| boundary | D4, `Concurrent freezer failures compete for capacity`; H2, `Contention plus a warming destination` | properties that hold only away from the edge. Both put the invariant under contention where it actually binds |
| fail-closed | D14, `Contradictory scan`; D15, `Inventory adapter unavailable` | filling a gap with something plausible when evidence is contradictory or missing |
| neutral | six fixed seeds | a property that is really one lucky estate |

The neutral control is the seed list itself: `20260826, 20260927, 20261028, 20261129,
20261230, 20261331`, computed as `base + i * 101` from `--base-seed 20260826`. Seeds vary
the generated detail and event ordering and change nothing about what any drill asserts,
so a result that holds on one seed and not another is variance rather than a property.

## Scoring

`assurance/qualify.py` computes PASS/FAIL by deterministic Python over stored artifacts:
incident state, receipts, reservations, custody records, the fault log, and the drill's
declared expectations. No LLM is imported anywhere in that module. An LLM may explain a
failure; it cannot change the verdict.

Expectations are properties of the outcome — `no_duplicate_effect`,
`unsafe_destination_refused`, `blocked_revision_committed_nothing` — never scenario
identifiers. An agent cannot be tuned to pass D5; it can only pass by not creating a
duplicate effect.

Idempotency drills additionally require `fault_actually_fired`. A drill that was supposed
to inject a commit loss and did not proves nothing, and would otherwise pass.

An expectation with no registered evaluator is recorded as unmet with the detail
`no evaluator registered for this expectation`. A typo in an expectation key fails the
drill rather than silently passing it.

### The three drill-id branches, and what they are not

`assurance/controller.py` around lines 78 to 83 reads:

```python
if spec.id == "D10":
    _stage_poisoned_vendor_content(runtime, run)
if spec.id == "D11":
    _attempt_forbidden_tool(runtime, run)
if spec.id == "D12":
    _replay_duplicate_scan(runtime, run)
```

Read out of context this looks like the scorer special-casing three drills, which would
be disqualifying. It is stimulus, and it runs before any scoring happens. Each of those
three helpers applies the thing the drill is about and then stops:
`_stage_poisoned_vendor_content` writes a vendor reply into a work order and reads it
back through the real `get_work_order` tool so the broker's screening path sees genuine
agent traffic, `_attempt_forbidden_tool` has the Dispatch Agent's identity reach for two
restricted inventory tools, and `_replay_duplicate_scan` replays a pickup scan verbatim.
None of them inspects an expectation, and none of them writes a verdict.

Scoring happens on the next lines, in `score_drill` in `assurance/qualify.py`, which
receives only the collected evidence and the drill's declared expectations. That module
contains no drill-id branch at all: `spec.id` appears in it exactly twice, once to record
the id on the outcome and once to list which drills failed. Every check is dispatched
through an `EVALUATORS` dictionary keyed by expectation key, so what a drill is called
cannot change how its outcome is judged. Grep it yourself:

```bash
grep -nE '"(D|H)[0-9]+"' assurance/qualify.py    # no matches
```

## Failure attribution

A run that fails because our own harness or a service was unreachable is marked
`infrastructure_error` and **excluded from the scored denominator**, not counted as a
pass. That distinction is invariant N12: infrastructure failing is not the same as an
agent behaving unsafely.

Infrastructure errors are still published in the raw rows.

## What is published

- `evidence/campaign/results.json` — provenance, derived metrics, and every raw row
- `evidence/campaign/results.csv` — the same rows, flat
- `evidence/campaign/metrics.json` — derived metrics alone
- `evidence/campaign-agent/` — the same three, for the live-agent tier

Provenance on every run records the exact command, corpus version, seeds, model ID, ADK
version, skill revisions by content hash, and source commit.

### Where provenance is currently incomplete

Three published artifacts carry `"source_commit": "unknown"`:

- `evidence/campaign/results.json`
- `evidence/campaign-agent/results.json`
- `evidence/iam-denial.json`

The field whose whole job is to name the tree an artifact came from names nothing in
those three. The cause was mundane: `source_commit` was read from the `NIGHTSHIFT_COMMIT`
environment variable with a literal `unknown` fallback, and the runs that produced those
files were launched without it set. Nothing about those runs is less real than the ones
that carry a commit. What is missing is the chain from a published row back to the code
that produced it.

The generator no longer leaves that hole. `Settings.source_commit` falls back to
`git rev-parse --short HEAD` for the checkout, and reaches `unknown` only when there is no
git repository at all, which is the clean-room case where a `git archive` export has no
`.git` directory. Artifacts generated from now on carry a real commit. Those three predate
the fix and will keep reading `unknown` until they are regenerated.

The two `metrics.json` files and the two `results.csv` files carry no provenance block at
all by design. They are derived views, and the `results.json` beside them is the artifact
that carries provenance for the run.

The published incident manifests and `evidence/qualification.json` and
`evidence/content-screening.json` all name a real commit. See
[`README.md`](README.md) in this directory for the per-file breakdown.

## Reproduction

```bash
make evidence          # deterministic tier
make evidence-agent    # live-agent tier (needs GCP, slow)
```

Same seeds produce the same scripted results. The agent tier is not bit-reproducible —
the model is not deterministic even at temperature 0 — which is why its sample size and
variance are disclosed rather than averaged away.

## One estate, one failing unit

Every run in every tier uses the same estate topology, defined in `fixtures/estate.py`.
One synthetic site, `SITE-1`, holds eight ULT freezers across four zones, all at a -80C
setpoint with a -65C high alarm. `DEFAULT_FREEZERS` fixes their sizes and states:

| Freezer | Zone | Slots | Occupancy | Temp | Backup qualified |
|---|---|---|---|---|---|
| F-17 | B2 | 144 | 0.83 | -79.4 | no |
| F-03 | B2 | 144 | 0.72 | -79.8 | yes |
| F-08 | B1 | 120 | 0.91 | -80.2 | yes |
| F-11 | B1 | 96 | 0.55 | -78.9 | yes |
| F-22 | C1 | 144 | 0.96 | -79.1 | yes |
| F-24 | C1 | 96 | 0.34 | -68.5 | no |
| F-31 | C2 | 120 | 0.61 | -80.6 | yes |
| F-35 | C2 | 72 | 0.88 | -79.9 | yes |

The spread is deliberate. F-03 and F-31 have real headroom, F-22 and F-08 are nearly
full, F-11 is small but empty, and F-24 is cold-ish while sitting above the ULT ceiling,
so the kernel refuses it as a destination even though a naive "has free slots" reading
would pick it. That is what makes placement a decision rather than a lookup.

F-17 is the failing unit in every drill. It is the default `failed_freezer` on
`ScenarioConfig`, and `_container_count` gives it exactly 42 containers where every other
freezer gets a proportional share. So the 42-container impact set that appears throughout
the evidence is a fixture constant, not a measurement.

What that licenses. Every invariant result, every refusal, and every idempotency
observation is a real result about this system's behaviour under these conditions, and
the conditions are fully specified, so anyone can reproduce them exactly. Seeds vary the
generated detail on top of this topology: which study each container belongs to, specimen
counts, priorities, maintenance history, and event ordering.

What it does not license. Nothing here is evidence about how the system behaves on a
different estate shape. A site with one qualified destination instead of six, a failing
unit larger than the entire backup pool, failures cascading beyond the single competing
incident that D4 and H2 introduce, or a topology where the correct placement is genuinely
ambiguous are all untested. The invariants are written against state rather than this
fixture, and the property tests in `tests/property` generate arbitrary reservation mixes
and custody combinations rather than reading the estate, which is the strongest argument
available that the rules are not fitted to F-17. It is an argument, not a measurement.

## Honest reading of a zero

Every zero in the published metrics is an **observed** zero over a stated denominator, on
a stated corpus, at a stated commit. It is not a proof of impossibility. The property it
supports is that across those runs, the deterministic layer refused every attempt that
would have violated the invariant — which is the strongest claim the evidence can carry.
