# Architecture

## The one rule

> Agents decide what to do. Deterministic code decides what is true and whether state may
> change.

Gemini interprets noisy telemetry, prioritises material, chooses among valid backup
options, and explains tradeoffs. It is never the authority on whether capacity exists,
whether an effect already happened, whether a responder is authorised, whether custody
may change, or whether an incident may close.

## The dominant mechanism

```
live incident evidence
  → specialist agents plan and delegate
    → tool broker restricts reachable tools by identity
      → deterministic Rescue Safety Kernel validates preconditions
        → idempotent domain service commits the effect
          → immutable receipt enters the incident ledger
            → incident advances only when the required evidence exists
```

And before any revision reaches that path:

```
candidate revision
  → deterministic disaster drill corpus
    → faults injected at tool boundaries
      → side effects and state scored against hard invariants
        → QUALIFIED revision receives operational traffic
        → failing revision is BLOCKED
```

## Component map

```
                          PUBLIC WEB (Next.js)
                                  │
                          Public BFF (Cloud Run)
                     read-only · responder scans · bounded drills
                                  │
        ┌─────────────────────────┼──────────────────────────┐
        │                         │                          │
   Incident Ingestor      Agent fleet (ADK)            Evidence compiler
   deterministic          Gemini 3.5 Flash             deterministic, no LLM
        │                         │                          │
        │                    Tool broker                     │
        │            registry → identity → policy            │
        │            → faults → transport → screen           │
        │                         │                          │
        └────────────┬────────────┴──────────┬───────────────┘
                     │                       │
        ┌────────────┴───────────────────────┴────────────┐
        │   Six domain services, six Cloud Run identities │
        │   telemetry · inventory · capacity              │
        │   facilities · custody · incident control       │
        └────────────────────────┬────────────────────────┘
                                 │
                     Rescue Safety Kernel (pure)
                        N1–N13, state machines
                                 │
                            Firestore
                    incidents · receipts · transfers
                                 │
                    KMS-signed evidence manifest
                       Cloud Storage + verifier
```

## Why the orchestration loop is not an ADK agent-transfer graph

The Commander decides which specialist works next, and
[`agents/orchestrator.py`](agents/orchestrator.py) executes that decision. Specialist
ordering, tool-call budgets, and resume points have to be observable state that a drill
can interrupt and a manifest can replay. An emergent conversation is a poor place to keep
something a verifier has to reproduce.

The Commander is given a deterministic *what is needed next* readout — the same "why
can't this advance" line an operations console would show, computed by the same guards
that will refuse the transition. That readout exists because early live runs without it
had the Commander run custody before any capacity was reserved and never ask for a
signal verdict at all, leaving containment permanently unplaced.

## Exactly-once, in three layers

A semantic action ID is `sha256` over the *meaning* of an action, never over a timestamp
or a retry counter:

```python
reservation_action_id = sha256("reservation" | incident | destination | placement_group)
work_order_action_id  = sha256("work_order"  | incident | freezer     | fault_class)
transfer_action_id    = sha256("transfer"    | incident | container   | destination_slot)
close_action_id       = sha256("close"       | incident | reconciliation_snapshot_hash)
```

Every mutating service then runs the same seven steps inside one transaction
([`services/common/effects.py`](services/common/effects.py)):

1. validate caller authority
2. validate request schema
3. look up an existing receipt by `action_id`
4. if one exists, return it verbatim
5. otherwise evaluate Safety Kernel preconditions
6. commit the effect and its receipt atomically
7. return the receipt

Steps 3–4 are why a resumed workflow, a redelivered Pub/Sub message, and a double-tapped
responder button all converge on one effect. Step 6 sharing a transaction with the
capacity read is why two concurrent incidents cannot both win the last slots.

The close action ID is keyed on the reconciliation snapshot hash specifically so a stale
close request cannot replay an earlier close receipt.

## The Safety Kernel

[`nightshift/safety_kernel/`](nightshift/safety_kernel/) is pure Python: no model calls,
no network, no datastore, and no wall clock. Every function is total over an explicit
`KernelState` snapshot, which is what lets the production services and the offline
verifier evaluate literally the same code against the same inputs.

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

Tests assert against these functions rather than reimplementing what they *should* say.

## Authority, enforced three times

The §11.3 permission matrix is applied at three independent layers, so skipping any one
of them changes only *where* the refusal happens:

1. **Toolset construction.** An agent's tools are derived from its authority domains, so
   a forbidden tool is absent from the schema the model ever sees.
2. **Tool broker.** Deny-by-default: unregistered tools are unreachable, and the calling
   identity must hold the tool's domain.
3. **Domain service.** Every route re-checks server-side against the same kernel table.

On Cloud Run there is a fourth: each agent runs as its own service account, and an
identity with no business calling a service is not a `run.invoker` on it. The Dispatch
Agent's attempt to read specimen inventory is refused by Cloud Run IAM before it reaches
any Night Shift code.

Read the matrix by its gaps. The Commander holds summary-only telemetry and no
inventory, capacity, facilities, or custody authority — a compromised Commander can
request a plan change and nothing else. The Dispatch Agent has no inventory column at
all, which is what makes the poisoned-vendor drill a real authorization denial rather
than a prompt that happened to work.

## Layered defence against untrusted content

A poisoned vendor reply that asks the Dispatch Agent to export specimen inventory meets:

1. **Model Armor** screening on untrusted tool output — live, and it matched the
   published payload family at HIGH confidence
2. **Semantic Governance** constraints — probabilistic, advisory, deployed dry-run first
3. **Identity authorization** — the Dispatch Agent holds no inventory domain
4. **Deterministic egress filter** — outbound vendor messages containing container IDs,
   study names, or specimen references do not leave, and the block is recorded as a
   security event

Layers 1 and 2 can be wrong in either direction without changing what is possible. Layers
3 and 4 are the ones that actually hold.

## Evidence

At completion the deterministic evidence compiler canonicalises the incident record,
hashes referenced artifacts, embeds the full authoritative state snapshot, and signs the
manifest hash with a Cloud KMS asymmetric key. No LLM output touches any of it.

The manifest stores its own evaluation timestamp and kernel thresholds, because N4 asks
"how old is this reading *now*" and a verifier running next week has to ask the same
question against the same `now` or it reaches a different, useless answer.

The verifier rebuilds a `KernelState` from the snapshot, re-runs the same invariant
functions, and compares. Editing the state produces a hash failure *and* a divergent
verdict; editing the stored verdict produces a divergence alone; editing the signature
fails signature verification. All three are reported separately so a mismatch says which
happened.

## Two-tier drill range

The hard invariants are properties of the deterministic layer, and whether they hold
under fault injection does not depend on a model being in the loop.

* **Scripted tier** — a fixed policy drives the same broker, services, and kernel with no
  model. Fast enough to run the whole corpus across many seeds.
* **Agent tier** — the real Gemini fleet. Slower, so a smaller disclosed sample.

Results are reported separately and never pooled. Mixing them would let the cheap tier's
volume flatter the expensive tier's behaviour, which is precisely the kind of number this
project exists to avoid.

## Repository layout

```
nightshift/          deterministic core
  safety_kernel/     N1–N13, state machines, preconditions, authority (pure)
  schemas/           Pydantic models and closed vocabularies
  evidence/          manifest, signing, publication
  verify/            offline verifier and CLI
  common/            canonical JSON, action IDs, clock, store, config, skills
services/            six domain services + tool broker + field simulator
  common/            repository, effect commit sequence, identity, app factory
agents/              prompts, toolsets, fleet, orchestrator
assurance/           drill corpus, fault injection, scripted driver, qualification
fixtures/            synthetic estate generator
apps/api/            public BFF
apps/web/            Next.js operator and judge surfaces
infra/               bootstrap and deploy scripts
corpus/              exported drill definitions (public + holdout)
skills/              versioned operational playbooks
tests/               unit, property, integration, adversarial, e2e
```
