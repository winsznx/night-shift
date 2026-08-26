# Demo script — 4 minutes

Every beat below is a real surface in the deployed product. Nothing is staged, and
nothing needs to be explained from a diagram.

---

## 0:00–0:25 · The problem

**Show:** the landing page, then `/app/freezers` with F-17 above its alarm threshold.

> "A freezer alarm tells a lab something is wrong. The hard part is everything that has
> to happen after it — working out whether it's real, finding out what's inside, locating
> space that's actually safe, getting someone on site at 2 AM, and knowing afterwards
> that nothing was left behind."

Point at the estate table: eight ULT freezers, one of them failing, and note that F-24
has the most free slots of any unit and is unusable because it sits above the ULT
ceiling. Free space is not availability.

## 0:25–1:05 · The incident starts itself

**Show:** `/app/incidents/<id>` — the temperature chart with the threshold crossing
marked, the incident state badge, the impacted-material count.

> "No one prompted anything. Telemetry crossed a threshold, the incident opened, and the
> Signal Investigator classified it as equipment failure rather than a door excursion.
> Containment follows automatically — that's a reflex, not a decision, and no agent holds
> the authority to place or withhold it."

Point at the impact snapshot: 42 containers, several thousand synthetic specimen records,
five studies. Computed from fixture inventory, not typed.

## 1:05–1:45 · Capacity is arithmetic, not opinion

**Show:** `/app/capacity` — eligible and ineligible destinations with reasons attached.

> "The Broker proposes; the Capacity Service disposes. The reservation commits inside a
> Firestore transaction, so when two incidents race for the last slots, one wins and one
> is refused on N1 with the real numbers attached."

**Show:** the refused receipt in the incident's receipt table, red row, invariant named.

> "That refusal is evidence. It's on the timeline and it's in the signed manifest."

## 1:45–2:20 · Governance

**Show:** `/app/fleet` — the permission matrix.

> "Read this by its gaps. The Commander has no write authority anywhere; a compromised
> Commander can request a plan change and nothing else. The Dispatch Agent has no
> inventory column at all."

> "So when a vendor reply tells the Dispatch Agent to export the specimen list, Model
> Armor flags it, the semantic policy flags it — and neither of those is what saves us.
> What saves us is that the agent's identity isn't a `run.invoker` on the Inventory
> service. Google's infrastructure refuses the call before it reaches our code."

**Show:** the security event on the incident timeline.

## 2:20–2:55 · Crash and resume

**Show:** `/app/drills/D5`, then `/app/drills/D7`.

> "We didn't assume what ADK does to a committed tool on resume — we provoked three
> interruption shapes and measured. Only one re-invokes: an invocation cancelled
> mid-flight, which is what a dying worker actually looks like."

> "That run made two tool calls and produced one committed effect, because the semantic
> action ID was identical and the second call replayed the first one's receipt. If you
> test resume safety by raising from a plugin, you'll conclude idempotency is optional —
> and then a pod eviction books the freezer twice."

## 2:55–3:25 · The human boundary

**Show:** `/respond/<token>` on a phone viewport.

> "Claude can't move a freezer box. This is the responder's screen — one container at a
> time, and the destination temperature front and centre, because that's the number that
> decides whether the commit is accepted."

Scan a container in. Show the commit succeeding. Then show a refusal on a stale or warm
destination:

> "Refused by N4. The destination reading was 1,175 seconds old against a 900-second
> limit. Nobody argued with it."

## 3:25–3:45 · Reconciliation and proof

**Show:** the reconciliation panel reaching zero unresolved, the incident closing, then
`/proof/<id>`.

> "Closure is refused while anything is unresolved, any effect is uncertain, or
> containment hasn't been released against a validated recovery — and it's refused if
> material is still sitting in the failed freezer, whatever custody label it carries. A
> live drill run taught us that one: the agent quarantined all 42 containers when the
> destination warmed, which looked complete on paper and left every specimen where it
> started."

**Run live:**

```bash
python -m nightshift.verify --manifest evidence/incidents/<id>.manifest.json
```

> "No model, no network, no credentials. It rebuilds the world from the snapshot and
> re-runs the same kernel the services ran. Edit the state and the hash fails and the
> verdict diverges. Edit the verdict and the divergence shows. Both are reported
> separately."

## 3:45–4:00 · It's actually running

**Show:** `curl $API/api/meta` — model, store backend, signer backend, region, commit.

> "Gemini 3.5 Flash on Vertex. Six Cloud Run services under six service accounts.
> Firestore transactions holding capacity. Cloud KMS signing the evidence."

Close on:

> "Agents choose the rescue. Deterministic evidence decides what is allowed to become
> true."

---

## Setup before recording

```bash
uv run python scripts/seed_demo.py --store firestore --namespace demo --rounds 8
make evidence
make smoke-live
```

Have open in tabs: landing, incident detail, fleet, capacity, drills D5 and D7, the proof
page, and a terminal at the repo root.

## What not to claim

- Do not say Night Shift moves specimens. It coordinates the people who do.
- Do not present the deterministic drill tier as evidence about agent behaviour, or pool
  it with the live-agent tier.
- Do not describe the estate or the responder scans as real.
- Do not claim managed Agent Runtime or Agent Registry resources. The authority
  separation shown is Cloud Run IAM with distinct service accounts, which is what is
  actually deployed.
