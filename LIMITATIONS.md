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
principal, marked `simulated: true`, and only in demo, drill, and test namespaces — it
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

| Capability | Status |
|---|---|
| Gemini 3.5 Flash on Vertex AI | delivered live |
| Google ADK agents, tools, resumability, plugin interception | delivered live |
| Cloud Run, Firestore, Pub/Sub, Cloud Storage, Cloud KMS, Cloud Trace API | delivered live |
| Model Armor prompt-injection screening | delivered live |
| Per-agent Google service accounts + Cloud Run IAM authorization | delivered live |
| Agent Registry / Agent Identity APIs | enabled and reachable; **agents are not registered as managed Agent Registry resources** |
| Agent Runtime (`reasoningEngines`) | API reachable; **agents run on Cloud Run and a local ADK runtime, not as managed Runtime resources** |
| Managed Runtime revision traffic splitting | **not delivered.** Qualification state is authoritative in Firestore and deployment code refuses unqualified revisions |
| Agent Registry managed skill revisions | **not delivered.** Skills are content-addressed by SHA-256 and referenced by hash from the manifest |
| Semantic Governance Policies | **local deterministic implementation of the §12 constraint set, in dry-run.** The managed Vertex policy engine was not provisioned |
| Agent Gateway | **not delivered.** Every agent tool call goes through Night Shift's own broker (`services/gateway/broker.py`), which is the single egress path and applies the §11.3 matrix, budget caps, content screening, and semantic policy. The managed Gateway product was not provisioned, so the broker is a local implementation of that role and is not presented as the Google product |
| Memory Bank | **local non-authoritative note store.** The managed Memory Bank resource was not provisioned |

The fallbacks are the PRD §0.3 documented paths, and none of them is presented as the
managed product. Where a managed resource is absent, `docs/CLAIMS.json` says so on the
specific claim.

### Why the governance fallbacks

Agent Registry, Agent Identity, and `reasoningEngines` are all reachable on this project
— that was verified in Phase 0 and is recorded in `docs/SPIKE_RESULTS.md`. What was not
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
Cloud Run edge to do the refusing — our own broker refused all 24 of them.

What is true now, and measured: over HTTP each call is minted as the calling agent's own
service account, and `evidence/iam-denial.json` records `ns-dispatch` being refused
**HTTP 403 by the Cloud Run edge** on the Inventory service, while `ns-impact` gets 200
on the same route. That contrast is the part that makes it a proof rather than an
anecdote — a broken endpoint denies everyone.

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

- The `/healthz` route on the deployed BFF returns 404 through the Cloud Run frontend
  while `/api/*` routes work. Health is checkable via `/api/meta`, and `make smoke-live`
  uses that.
- Agent tier runs are slow (roughly four minutes each) and occasionally produce a
  malformed structured output, which is recorded as a specialist failure rather than
  retried indefinitely.
- The Commander's specialist ordering is not deterministic across runs. The pipeline
  readout keeps it correct, but two runs of the same incident may consult specialists in a
  different order and take a different number of rounds.

## Not claimed at all

- No HIPAA, GxP, FDA, GLP, CLIA, or other regulatory compliance. None of it was assessed.
- No claim that the agents make good operational judgements. The claim is narrower and
  deliberately so: the deterministic rules held regardless of what the agents decided.
- No claim of security against an attacker with Firestore write access or the ability to
  sign with the KMS key. The evidence chain proves the state was signed by the key holder;
  it cannot prove the key holder was honest.
- No dollar figure for operational savings. The PRD explicitly forbids inventing one, and
  nothing here measures human coordination hours.
