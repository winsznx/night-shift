# Limitations

What Night Shift is not, what it did not deliver, and what its numbers do and do not
mean. Every limitation here is also reflected in `docs/CLAIMS.json` and in the manifests
themselves.

## The environment is synthetic

- The research estate, specimen records, studies, and responder roster are generated from
  a seed by [`fixtures/estate.py`](fixtures/estate.py). Every record carries
  `synthetic: true`.
- Responder names are invented. No real person is represented.
- There is no real patient data, PHI, PII, or confidential research data anywhere.
- Freezer temperature curves are injected, not measured.

## Physical movement is simulated

No language model can move a freezer box. The bounded field simulator emits exactly the scan and
acknowledgment events the responder web interface emits, under the `responder-app`
principal, marked `simulated: true`, and only in demo, drill, and test namespaces. It
raises `PermissionError` anywhere else.

The responder screen itself is real and works end to end against live services. What is
simulated is the human on the other side of it.

Post-repair recovery telemetry is likewise simulated. Note what that simulation does
*not* do: it writes readings, and the deterministic release rule decides whether those
readings constitute a validated recovery. Writing a "repaired" flag would have been the
fabrication this system exists to prevent.

## What the measured numbers mean

The campaign publishes raw rows and derives every headline from them. Read them with
these boundaries:

- **Two tiers, never pooled.** The scripted tier runs the corpus across many seeds with a
  fixed policy instead of a model. The agent tier runs the real Gemini fleet, is far
  slower, and therefore has a much smaller sample. Reporting a combined percentage would
  let the cheap tier's volume flatter the expensive tier.
- **The scripted tier is not a mock**, but it is also not evidence about model behaviour.
  It makes real tool calls through the real broker with real authorization and real fault
  injection. It proves the deterministic layer holds; it says nothing about judgement.
- **Zero observed violations is not zero possible violations.** Every count is over a
  stated denominator on a stated corpus at a stated commit.
- **Model Armor results describe one payload family.** The published injection payload was
  matched at HIGH confidence. That is an observation, not a detection rate.

## Delivered versus available

| Managed Google product | Delivered here | What Night Shift delivers instead |
|---|---|---|
| Gemini 3.5 Flash on Vertex AI | yes | |
| Google ADK agents, tools, resumability, plugin interception | yes | |
| Cloud Run, Firestore, Cloud Storage, Cloud KMS, Cloud Trace | yes | |
| Model Armor prompt-injection screening | yes | |
| Gemma 4 on Vertex AI, as the semantic content-screening layer | yes | |
| Cloud Scheduler and Cloud Run Jobs, driving the fleet unattended | yes | |
| Per-agent Google service accounts, Cloud Run IAM authorization | yes | |
| Pub/Sub | no | Topics are provisioned and no Python file publishes to or subscribes from them. Field events arrive through an in-process hook. A real deployment would attach a subscriber where `_tick_world` sits |
| Agent Registry, Agent Identity APIs | no | Reachable on this project. Agents are not registered as managed Agent Registry resources. Each agent is a distinct principal with its own service account, its own tool authority, its own content-addressed revision, and its own qualification state |
| Agent Runtime (`reasoningEngines`) | no | Agents run on Cloud Run and a local ADK runtime rather than as managed Runtime resources |
| Managed Runtime revision traffic splitting | no | Qualification state is authoritative in Firestore and deployment code refuses an unqualified revision |
| Agent Registry managed skill revisions | no | Skills are content-addressed by SHA-256 and referenced by hash from the manifest |
| Semantic Governance Policies | no | A local deterministic implementation of the constraint set, running in dry-run. The managed Vertex policy engine was not provisioned |
| Agent Gateway | no | Every agent tool call goes through Night Shift's own broker, which is the single egress path and applies the permission matrix, budget caps, content screening, and semantic policy. It is a local implementation of that role and is not presented as the Google product |
| Memory Bank | no | A local, non-authoritative note store. The managed Memory Bank resource was not provisioned |

The fallbacks are the PRD §0.3 documented paths, and none of them is presented as the
managed product. Where a managed resource is absent, `docs/CLAIMS.json` says so on the
specific claim.

### Why the governance fallbacks

Agent Registry, Agent Identity, and `reasoningEngines` are all reachable on this project.
That was verified in Phase 0 and is recorded in `docs/SPIKE_RESULTS.md`. What was not
done is migrating the fleet onto managed Runtime resources and registering agents and
skills as managed entities. That is a deployment-topology change, not a capability gap,
and it was left undone rather than half-done and overclaimed.

The authority separation that matters is delivered by a mechanism that is arguably
stronger for this purpose: seven distinct Google service accounts with Cloud Run
`run.invoker` grants that mirror the permission matrix.

Being exact about what that buys, because the obvious sentence to write here is an
overclaim. An earlier version of this file said the Dispatch Agent's attempt to read
specimen inventory "is refused by Google's infrastructure, not by our code". That was
not true of any run that had actually happened. Every recorded denial in the drill
corpus ran through `InProcessTransport`, where there is no network hop and therefore no
Cloud Run edge to do the refusing. Our own broker refused all 24 of them.

What is true now, and measured: over HTTP each call is minted as the calling agent's own
service account, and `evidence/iam-denial.json` records `ns-dispatch` being refused
**HTTP 403 by the Cloud Run edge** on the Inventory service, while `ns-impact` gets 200
on the same route. That contrast is the part that makes it a proof rather than an
anecdote, because a broken endpoint denies everyone.

Each call records whether it actually carried that identity, successes included, so the
evidence distinguishes the two cases instead of letting the stronger reading stand by
default.

Both layers are real and both are exercised. The honest phrasing is that the same denial
is enforced twice, and only one of those two enforcers is Google's. The drill corpus
still runs in-process, so its 24 denials remain **our** denials; the platform denial is
demonstrated separately and is not pooled into the corpus counts.

## Deliberate operational choices

- **Cloud Storage retention is versioned but not locked.** Locking is irreversible and
  PRD §28 requires explicit approval first. It was not requested, so it was not done.
- **The public demo drill endpoint runs the scripted driver only.** Exposing model-driven
  runs to unauthenticated callers is an unbounded cost surface. Rate-limited to 6/hour per
  client bucket, 3 concurrent, in a throwaway namespace.
- **Transfer volume is capped per run** and always reported. A run that moved 6 of 42
  containers says so, and the incident correctly stays open.
- **The local agent principal token is an HMAC** over a shared secret. On Cloud Run this
  sits behind Google-issued OIDC ID tokens; it carries the Night Shift principal, which
  transport identity alone cannot distinguish.

## Known rough edges

- Google's front end answers `/healthz` itself with an HTML 404 before the request reaches
  the container, so that path was never servable. The route is registered at
  `/api/healthz`, which reaches the app and also works through the web app's proxy.
- The public demo drill endpoint blocks the BFF's event loop for about three seconds by
  design. That is what makes the throwaway-namespace isolation true, and it should not be
  "optimised" into something concurrent without replacing that isolation first.
- Agent tier runs are slow, roughly three minutes each. Malformed structured output is
  re-asked exactly once with the parser's own error attached, and recorded as a specialist
  failure if the second attempt also fails. The bound is deliberate: an unbounded repair
  loop is the failure mode it exists to prevent.
- The Commander's specialist ordering is not deterministic across runs. The pipeline
  readout keeps it correct, but two runs of the same incident may consult specialists in a
  different order and take a different number of rounds.

## What was not measured

- **No control arm without the Safety Kernel.** Every one of the 144 published runs across
  both tiers ran the full kernel. Nothing here compares Night Shift against a system that
  lacks it, so the counts show that violations did not occur, not that the kernel is what
  prevented them. The nearest thing to a counterfactual in the repo is drill D12, where
  disabling the committed-receipt short-circuit turns a passing run into a failing one,
  and that arm was not run as part of the published campaign.
- **One estate, one failing unit.** All runs use a single synthetic estate topology with
  F-17 fixed as the freezer that fails. That licenses claims about this system's behaviour
  under the disclosed fault set. It licenses nothing about a different estate shape, a
  different failure mode, or a larger site.
- **Layer 3 runs on the committed default HMAC secret in the deployed environment.**
  Nothing in the repo or the deploy script sets `NIGHTSHIFT_AGENT_SECRET`, so the shipped
  deployment authenticates Night Shift principal tokens against the literal
  `nightshift-local-dev-secret`. Layer 4, Cloud Run IAM, is unaffected and still refuses a
  forbidden call at the edge. `SECURITY.md` states what this costs and the one-line fix.
- **Responder capture evidence is measured on its logic, not on model accuracy.** The
  deterministic adjudication is covered by tests. What is not measured is how often Gemini
  misreads a real label or a real freezer display under real lighting, because no such
  corpus was collected. A misread produces a refusal rather than a wrong commit, so the
  cost of that gap is a responder retaking a photo.

## Running cost through the judging window

Cloud Scheduler drives two jobs: a telemetry tick every ten minutes, which calls no model,
and an agent-fleet incident every six hours, capped at four model-driven runs per UTC day
and 200 for the life of the deployment. The caps are enforced in the job against a
Firestore counter rather than by the schedule, so a retry storm cannot spend past them.

Order of magnitude, on measured numbers: a live-agent incident makes roughly 9 model calls
and runs about 191 seconds. Four a day for the judging month is on the order of a thousand
model calls plus the Cloud Run time to make them, which sits inside the remaining
hackathon credit. The telemetry tick is Firestore writes and no model calls at all. If
that turns out to be wrong, `gcloud scheduler jobs pause nightshift-tick-incident` stops
the model spend and leaves the console live.

## Not claimed at all

- No HIPAA, GxP, FDA, GLP, CLIA, or other regulatory compliance. None of it was assessed.
- No claim that the agents make good operational judgements. The claim is narrower and
  deliberately so: the deterministic rules held regardless of what the agents decided.
- No claim of security against an attacker with Firestore write access or the ability to
  sign with the KMS key. The evidence chain proves the state was signed by the key holder;
  it cannot prove the key holder was honest.
- No dollar figure for operational savings. The PRD explicitly forbids inventing one, and
  nothing here measures human coordination hours.
- No claim that the drill corpus is exhaustive. It is 21 disclosed drills plus a three-case
  holdout, chosen to attack the mechanisms this system claims, and an attacker is not
  limited to the failure modes its author thought of.
