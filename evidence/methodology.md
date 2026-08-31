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
tier's volume flatter the expensive tier's behaviour. That is precisely the kind of
number this project exists to avoid.

## Isolation

Every drill run gets its own namespace, which is a collection prefix rather than a field
filter. A drill physically cannot read or write another drill's state, let alone
operational state.

## Fault injection

Faults are keyed on `(tool_name, action_id, call_number_within_action)`, never on
wall-clock timing. "Fail the second call to `reserve_capacity` for this placement group"
reproduces exactly; "fail 400ms in" reproduces differently on every machine.

Two kinds:

- `commit_loss` means the tool runs to completion and its response is discarded. The
  effect exists and nobody knows. This is the case PRD §22 asks about, and producing it
  requires wrapping the transport rather than raising before it.
- `tool_failure` means the tool never runs. A plain infrastructure error.

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

### The ablated arm

Those controls rule out an inert or an eager system. None of them answers the question a
sceptic should ask next, which is whether the Safety Kernel is what produced the result or
whether the rest of the architecture would have got there anyway.

`assurance/ablation.py` runs the corpus twice over the same six seeds. The `kernel` arm
rebinds `services.common.effects.evaluate_action` to a function that allows every action.
`effects.py` imports that symbol at module scope, so the rebind removes exactly step 5 of
the seven-step commit sequence and duplicates no logic: the transaction, the receipt
lookup, the authorization check and the write all still run. What is measured is the
kernel's contribution, not the contribution of everything at once.

| Arm | Passed | Invariant violations |
|---|---|---|
| control | 126 / 126 | none |
| kernel removed | 96 / 126 | N4 x6, N10 x6 across D5, D8, D14, D16, H3 |

Raw output is `evidence/ablation/ablation.json`, reproduced with `make ablation`. The
control arm reproduces the published campaign exactly, which is the check that the harness
did not change underneath the comparison.

Two honest readings. First, N1, N2 and N3 hold in **both** arms. Removing the preconditions
does not produce overbooking or duplicate effects, because Firestore's transaction and the
receipt short-circuit are separate mechanisms. That is a null result and it is what defence
in depth is supposed to look like, so it is reported rather than buried. Second, the
ablation runs on the deterministic tier only. Ablating the live-agent tier would cost model
calls for a comparison the scripted tier already makes cleanly, so the kernel's contribution
is measured, and measured on one tier.

The guard in `assurance/ablation.py` refuses to run against anything but the in-memory
store, and a unit test asserts `effects.evaluate_action` is still bound to the real kernel
at import, so a leaked patch from an ablation arm fails the suite rather than silently
disarming production.

## Scoring

`assurance/qualify.py` computes PASS/FAIL by deterministic Python over stored artifacts:
incident state, receipts, reservations, custody records, the fault log, and the drill's
declared expectations. No LLM is imported anywhere in that module. An LLM may explain a
failure; it cannot change the verdict.

Expectations are properties of the outcome such as `no_duplicate_effect`,
`unsafe_destination_refused` and `blocked_revision_committed_nothing`, never scenario
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

- `evidence/campaign/results.json` has provenance, derived metrics, and every raw row
- `evidence/campaign/results.csv` has the same rows, flat
- `evidence/campaign/metrics.json` has the derived metrics alone
- `evidence/campaign-agent/` has the same three, for the live-agent tier

Provenance on every run records the exact command, corpus version, seeds, model ID, ADK
version, skill revisions by content hash, and source commit.

### Where provenance is currently incomplete

One published artifact still carries `"source_commit": "unknown"`:
`evidence/campaign-agent/results.json`, the live-agent tier.

The cause was mundane: `source_commit` was read from the `NIGHTSHIFT_COMMIT` environment
variable with a literal `unknown` fallback, and the run that produced that file was
launched without it set. Nothing about the run is less real than the ones that carry a
commit. What was missing is the chain from a published row back to the code that produced
it.

That chain is recoverable here, and the artifact is left as it was written rather than
back-stamped, because a commit hash inserted after the fact is not a record of anything.
The run's own `generated_at` is `2026-08-26T05:00:12.789Z`. The last commit authored
before that instant is `877a9f7`, and the next one after it is `5df2f03`, five minutes
later. Both are ancestors of `main`. So the live-agent campaign ran at `877a9f7`, and
`5df2f03` is the commit that recorded what it found: its message states the 17-of-18
result, the zero N1/N2/N3/N6/N7/N8 violations, the 332 custody commits, and the D8
quarantine failure that produced two new safety rules. The artifact and the commit that
describes it are five minutes apart, which is a tighter binding than the missing field
would have given.

`evidence/traces.json` carries no `source_commit` field at all rather than an `unknown`
one, which is a different gap and is noted here so the count is right.

The generator no longer leaves the hole. `Settings.source_commit` falls back to
`git rev-parse --short HEAD` for the checkout, and reaches `unknown` only when there is no
git repository at all, which is the clean-room case where a `git archive` export has no
`.git` directory. `evidence/campaign/results.json` and `evidence/iam-denial.json` have
since been regenerated and now carry real commits.

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

Same seeds produce the same scripted results. The agent tier is not bit-reproducible,
because the model is not deterministic even at temperature 0. That is why its sample size
and variance are disclosed rather than averaged away.

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
would have violated the invariant. That is the strongest claim the evidence can carry.
