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

## Reproduction

```bash
make evidence          # deterministic tier
make evidence-agent    # live-agent tier (needs GCP, slow)
```

Same seeds produce the same scripted results. The agent tier is not bit-reproducible —
the model is not deterministic even at temperature 0 — which is why its sample size and
variance are disclosed rather than averaged away.

## Honest reading of a zero

Every zero in the published metrics is an **observed** zero over a stated denominator, on
a stated corpus, at a stated commit. It is not a proof of impossibility. The property it
supports is that across those runs, the deterministic layer refused every attempt that
would have violated the invariant — which is the strongest claim the evidence can carry.
