# Decisions

Material engineering decisions taken during the build, and why. Several were forced by
something that actually broke.

---

## D-01 · Gemini 3.5 Flash is served from `global`, not `us-central1`

**Context.** The PRD defaults all regional components to `us-central1` and requires
Gemini 3.5 or newer.

**Finding.** `gemini-3.5-flash` returns 404 from the `us-central1` Vertex endpoint and 200
from `global`. Only `gemini-2.5-flash` is available regionally.

**Decision.** `NIGHTSHIFT_MODEL_LOCATION=global` for the model endpoint; every regional
component stays in `us-central1`. PRD §6.4 permits a coherent alternative where service
availability forces one.

**Rejected.** Dropping to 2.5 Flash to keep a single region. That trades a hard model
requirement for a soft locality preference.

---

## D-02 · Orchestration is deterministic; delegation is not

**Decision.** The Commander decides *which specialist works next*; a deterministic loop
executes that decision, enforces budgets, and drives state transitions.

**Why.** Specialist ordering, tool-call budgets, and resume points have to be observable
state that a drill can interrupt and a manifest can replay. An ADK agent-transfer graph
puts that information inside a conversation, which is a poor place to keep something a
verifier has to reproduce.

**Consequence.** The Commander needed a deterministic "what is needed next" readout.
Without it, live runs had it delegate to custody before any capacity was reserved and
never request a signal verdict, leaving containment permanently unplaced. The readout
reports pipeline facts computed by the same guards that would refuse the transition. It
does not tell the Commander what to decide.

---

## D-03 · Containment is a reflex, not a decision

**Decision.** When the Signal Investigator classifies an event as `EQUIPMENT_FAILURE`, the
containment hold is placed automatically under the ingestor principal. No agent holds
`inventory.write`.

**Why.** Freezing normal traffic on a failing freezer is not a judgement call, and giving
an agent the authority to place it would also give it the authority to withhold it.

Same shape for the impact snapshot: the Impact Analyst decides *which containers and how
urgently*; the deterministic service records the authoritative snapshot from that
validated output. The placement-group arithmetic that reservation IDs depend on is not
left to a model, because a differently-grouped retry would derive a different action ID
and defeat idempotency.

---

## D-04 · Reservations track `slots_remaining` separately from `slots`

**Found by.** A live run failed N1 with "1 destination reserved beyond verified capacity".

**Cause.** Committing a transfer increments the destination's occupancy but the
reservation still held its original slot count, so the freezer was double-counted against
its own completed work.

**Decision.** `slots` is the original ask and never changes; `slots_remaining` decrements
on each commit. Capacity accounting uses `held_slots`, which is what the destination is
actually withholding from other incidents.

---

## D-05 · A placement group may hold at most one live reservation

**Found by.** Drill D5. The reservation response was lost after the effect committed, the
broker re-planned to a different destination, derived a *different* action ID, and
legitimately created a second reservation, booking the same boxes into two freezers.

**Why idempotency does not catch this.** Two different destinations are genuinely two
different semantic actions. N2 is correct to allow both. The problem is operational, not
an identity collision.

**Decision.** `_pre_capacity_reserve` refuses a second live reservation for a group at a
different destination and names the existing one. Re-planning stays available; it just has
to release the first reservation.

---

## D-06 · Forward progress needs an explicit order

**Found by.** An incident oscillated between `RESCUE_PLANNING` and `CAPACITY_RESERVED`
until the round budget ran out.

**Cause.** `next_natural_state` iterated `INCIDENT_TRANSITIONS[current]`, a frozenset with
legitimate backward edges. Set iteration order picked one arbitrarily.

**Decision.** An explicit `PROGRESSION` tuple defines the forward path. `next_natural_state`
only ever returns the next forward state, and only when its guard allows. Backward
transitions remain legal but require an explicit request.

---

## D-07 · Closure requires a hold that existed, released, and carried evidence

**Found by.** An incident reached `CLOSED` having never been contained at all.

**Cause.** N6 checked that no hold was *active*. That is also true when no hold was ever
placed, so an uncontained incident looked identical to a properly contained one.

**Decision.** `_containment_blockers` requires a hold that exists, is released, and carries
recovery evidence. Separately, `RESCUE_PLANNING` now requires an active hold. The graph
allowed `CONFIRMED → ESCALATED → RESCUE_PLANNING`, and an early run took exactly that
route and planned a rescue while normal traffic continued on the failing freezer. Guarding
the destination state, not just the path to it, closes both.

---

## D-08 · The drill corpus runs in two tiers

**Decision.** A scripted deterministic driver runs the whole corpus across many seeds; the
real Gemini fleet runs a smaller disclosed sample. Results are reported separately and
never pooled.

**Why.** The hard invariants are properties of the deterministic layer. Whether they hold
under fault injection does not depend on a model being in the loop, and a full agent run
takes about four minutes against under a second for the scripted equivalent. Pooling them
would let the cheap tier's volume flatter the expensive tier's behaviour.

The scripted tier is not a mock: it makes real tool calls through the real broker with
real authorization and real fault injection. Only the choice of which call to make next is
fixed rather than reasoned.

---

## D-09 · Commit loss is injected around the transport, not before it

**Decision.** `CommitThenLoseTransport` invokes the real transport and *then* discards the
result.

**Why.** Raising before transport simulates "the call never happened", which is the easy
case. The case PRD §22 asks about is "the effect exists but nobody knows", and only the
wrapper produces it. That is the difference between a retry meeting an existing receipt
and a retry meeting an empty store.

---

## D-10 · A fault that never fires fails its drill

**Decision.** Idempotency drills carry a `fault_actually_fired` expectation.

**Why.** A drill that was supposed to inject a commit loss and did not proves nothing, and
without this it would pass. That is the loudest possible false green.

---

## D-11 · One image, seven Cloud Run services

**Decision.** All services share a container image; `NIGHTSHIFT_SERVICE` selects the ASGI
app. Each deploys as a separate Cloud Run service with a separate service account.

**Why.** The authority boundaries are the product story and must be real. What differs
between services is the identity they run as and the routes they expose. Both are
runtime configuration, not build output. Seven near-identical images would add build
time and drift risk for nothing.

---

## D-12 · The estate's telemetry is anchored to now by default

**Found by.** An integration test failed with "destination reading is 8299s old".

**Cause.** The fixture epoch was pinned while `now` floated, so N4 correctly rejected every
destination as stale.

**Decision.** `build_estate(epoch=None)` anchors to the current time; drills and the
published reference proof pass an explicit epoch. The structural layout is seeded either
way. Only timestamps move.

---

## D-13 · A dedicated red, used strictly semantically

**Context.** DESIGN.md is monochrome plus one electric blue, with tangerine, green, and
violet as supporting accents. §34.1 permits a dedicated red only where accessibility or
usability requires it.

**Decision.** `#dc2626` is introduced for refusals, invariant violations, and above-alarm
temperature.

**Why.** A refused custody commit and a merely delayed one must not look alike at a
glance, and tangerine is already carrying "in progress". It is never used decoratively.

---

## D-14 · Orchestrator-driven transitions do not consume the agent loop budget

**Found by.** A 42-container incident hit the tool-call budget before it could close.

**Decision.** `ToolBroker.call(..., system=True)` marks deterministic progress:
requesting the transition the evidence already supports, or attempting closure. Those
still pass every authorization and policy layer and are still recorded; they just do not
count against a guard whose purpose is detecting an agent looping.

---

## D-15 · A batch custody commit that still validates individually

**Context.** The headline incident moves 42 containers. One `CustodyDecision` per
container would need 42 model turns.

**Decision.** `commit_ready_transfers` commits every container whose evidence is complete,
running each through the full single-commit path, with the same action ID, the same
N3/N4 evaluation, and the same receipt.

**Why it is not a bulk override.** A batch of forty with one warmed destination commits
thirty-nine and refuses one, with the reason attached to that container specifically.

---

## D-16 · H2's expectation was wrong, and was corrected rather than deleted

**Found by.** Holdout drill H2 (contention plus a warming destination) asserted the
incident must not close, and failed a run that had released the bad reservation,
re-planned to a cold destination, and reconciled everything.

**Decision.** The expectation was replaced with the properties that actually matter:
capacity conserved under contention, and no commit on out-of-bounds evidence. The
reasoning is recorded in the drill's own description.

**Why this is worth recording.** Weakening a drill to make it pass is exactly the failure
mode this project exists to prevent. The distinction is that the *system* was right and
the assertion encoded an assumption about recovery that was never true.

---

## D-17 · Per-agent impersonation belongs to one runtime, not every service

**Found by.** External review of the identity work, before deployment.

**What was wrong.** The provisioning script granted every domain service account
`serviceAccountTokenCreator` on every agent account. That was 49 bindings. The intent
was to make per-agent identity work regardless of which process made the call. The
effect was that a compromised Custody service could mint a token as the Dispatch Agent
and call its peers holding that agent's authority.

**Decision.** Only `ns-svc-bff`, the account the agent loop actually runs as, may
impersonate agents. The script now also revokes the wider grant, so re-running it on an
existing project tightens the policy instead of leaving the old bindings in place. 42
were revoked from the live project.

**Why this is worth recording.** The whole least-privilege claim is that an agent cannot
reach what it has no business reaching. A grant that lets any service borrow any agent's
identity does not weaken that claim slightly. It supplies exactly the lateral path the
model is supposed to deny, while every layer above it keeps reporting success.

---

## D-18 · A platform denial is not an infrastructure error

**Found by.** External review, reading `HttpTransport` against what Cloud Run actually
returns.

**What was wrong.** The transport parsed the response body before looking at the status.
Cloud Run's edge refuses an unauthorized caller with an HTML error page, so the JSON
decoder raised first and the denial surfaced as `TransportError`, classified N12
INFRASTRUCTURE, which the qualification engine is designed to *excuse* rather than score.

**Decision.** Authorization statuses are settled before the body is parsed, and 401/403
bodies are parsed best-effort because on that path the status line is the fact and the
body is decoration. `tests/unit/test_transport_authorization.py` pins the ordering with
real Cloud Run HTML, and keeps a 500 classified as infrastructure so the guard cannot
swallow genuine outages.

**Why this is worth recording.** The single most valuable result this system can produce
is the platform refusing a forbidden call. Filing it under the one failure class that
gets waived meant the better the enforcement worked, the less the evidence showed.

---

## D-19 · Live screening is opt-in, so "credential-free" is structural

**Found by.** External review noting that the deterministic suite's headline property
depended on the developer's `.env` being empty.

**What was wrong.** Live Model Armor was selected whenever a template happened to be
configured. Anyone with a populated `.env` ran the "deterministic, credential-free" drill
corpus against a live Google API without asking for it.

**Decision.** `NIGHTSHIFT_LIVE_CONTENT_SCREEN` gates it, default off, independent of
whether a template exists. The deployment sets it; local runs and CI do not.

**Why this is worth recording.** A property that holds only on an unconfigured machine is
not a property. It is a coincidence that passes CI.

---

## D-20 · No embedding index

**Context.** The operational corpus is six versioned playbooks in `skills/`, each routed
to the agents it applies to by `skills_for_agent`, and referenced in the manifest by the
SHA-256 of its body.

**Decision.** Procedures are selected by agent identity and referenced by content hash.
There is no vector store, no embedding, and no similarity retrieval anywhere in the
system.

**Why.** A manifest has to let the offline verifier reproduce exactly which procedure was
in force, and an approximate-nearest-neighbour lookup over a mutable index is not
reproducible. With six fixed playbooks routed by identity, an approximate match is a
correctness regression rather than a retrieval improvement.

**Rejected.** Embedding the playbooks so an agent could retrieve across them. At this
corpus size it buys nothing an explicit routing table does not already give, and it costs
the reproducibility the whole evidence chain rests on.

---

## D-21 · Corroborating capture evidence for custody scans

**Found by.** Reading the responder scan path against a published manifest.

**What was wrong.** A custody commit rested entirely on a bearer task token, and that
token was published in plaintext inside the signed manifest, so it was not even a secret.
Anyone holding the string could post a pickup or a receipt for any container in the batch.
The token proved a session had been issued. It was being asked to prove that a physical
box had moved, which it never could.

**Decision.** A responder may attach capture evidence to a scan: a photographed container
label, a photographed freezer display, a spoken confirmation. Gemini reads it in
[`nightshift/multimodal/reader.py`](nightshift/multimodal/reader.py) and returns strings
and numbers describing what it saw or heard, nothing else. Deterministic code in
[`nightshift/safety_kernel/corroboration.py`](nightshift/safety_kernel/corroboration.py)
then compares those readings against authoritative state: the label against the container
being scanned, normalised for case, spacing and punctuation and nothing more; the display
against the telemetry reading for that destination, within a 2.0C agreement window and
below the same N4 ceiling a commit needs; the transcript against a negation check that
runs before the affirmation check, because "no, that is not confirmed" contains an
affirmative token. The token still authenticates the session.

**The property that makes this safe.** Capture evidence can refuse a scan the token would
have allowed, and can never permit one the token would not. `adjudicate` refuses on any
single contradiction, and its allow path returns exactly the authority the token already
granted. A forged photograph therefore gains an attacker nothing, and that asymmetry is
why the adjudication can run on an unauthenticated responder route at all.

**Absence degrades, it does not block.** Every reader fails to `None` rather than raising,
and an all-absent result is allowed and recorded as having rested on the token alone. A
responder in a cold room with a dead phone battery still has to be able to move specimens.
The receipt records which channel carried the authority, and a digest of each capture
travels into the manifest while the capture itself is never stored.

**Deliberately not a confidence threshold.** "The model was 0.83 sure" is not evidence
about a freezer. Either the string it read equals the container the responder claims to be
holding or it does not, and either the temperature it read agrees with the telemetry this
system already holds or it does not. A model that hallucinates a container id produces a
MISMATCH, which is a correct outcome. A model allowed to conclude anything would produce a
commit, which is not.
