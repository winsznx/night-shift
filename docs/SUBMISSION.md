# Submission

Everything a judge needs in one place: the track and why, what to check and in what
order, how each requirement is met, what is not delivered, and every link.

---

## Track: Fortified Enterprise Fleet

A -80C freezer failure is not one task. It is a confirmation problem, an impact
assessment, a capacity search under hard physical constraints, a dispatch, a chain of
custody, and a reconciliation that has to close cleanly or not at all. Each of those
needs different authority over different systems, and most of them must be refused
outright when the evidence is stale. That is what makes it a fleet rather than an agent
with six tools.

Night Shift runs six agents on Gemini 3.5 Flash through Vertex AI, coordinated with
Google's Agent Development Kit, against six authenticated Cloud Run services with
Firestore underneath and Cloud KMS sealing the result.

### The unlikely hero

The person this is built for is a biobank lab manager who gets a phone call at 2am.

They are not a developer. They are not in a standard corporate role. They are one
person, at home, holding a phone, responsible for specimen collections that took years to
assemble and cannot be recollected. Existing monitoring tells them something is wrong.
Everything after that alarm is theirs: work out what is affected, find somewhere cold
enough with enough slots, get someone into the building, track every box, and be able to
prove afterwards where each one went.

Night Shift owns that whole span. The person's job becomes reviewing what happened
rather than performing it at 2am.

### What the track asks for, answered by name

The track names three things that must be demonstrated. Two are delivered and one is
partial, and the partial one is stated as such rather than dressed up.

**"Agents cataloged for cross-department use."** This is the weakest of the three, so it
goes first. What is delivered is a catalog with teeth in the places that matter
operationally: each of the six agents is a distinct principal with its own Google service
account, its own tool authority derived from a single declarative permission matrix, its
own content-addressed revision, and its own qualification state that deployment code
refuses to override. `/app/fleet` renders that matrix live, gaps included. What is not
delivered is registration as managed Agent Registry resources. `LIMITATIONS.md` says so
in the same words.

**"Context safely maintained across weeks of asynchronous operations."** Incident state
lives in Firestore, physically isolated by an `ns_{namespace}__` collection prefix rather
than a query filter, and every effect commits through a seven-step transaction keyed on a
semantic action ID so the same logical action attempted twice produces one effect and a
replayed receipt. That is the property that makes a week-long, interruptible workflow
safe, and it is measured rather than asserted: the ADK resume spike in
`CONTRIBUTIONS.md` proves a mid-flight cancellation genuinely re-invokes a committed
tool. Cloud Scheduler drives the fleet on a schedule through the judging window, so this
is demonstrated by still running in week three rather than described.

**"Interaction with production data without violating compliance, sovereignty, or
security policies."** Every agent calls as its own service account, so a forbidden call
is refused by Cloud Run's IAM edge before any of our code runs.
`evidence/iam-denial.json` records that 403 for `ns-dispatch` alongside a 200 for
`ns-impact` on the identical route. Above that, a deny-by-default broker refuses any tool
outside an agent's declared domains, and each domain service independently re-checks the
calling principal. Untrusted vendor text passes three screening layers before it can
reach a model's context. All estate and specimen data here is synthetic, disclosed on
every page and in `/api/meta`.

---

## The one-sentence version

Night Shift is a six-agent Gemini 3.5 fleet on Google Cloud that takes a -80C freezer
failure from alarm to reconciled custody with no human in the loop: in a live
Gemini-driven run it moved all 42 specimen containers to qualified destinations, recorded
every refusal with the deterministic invariant that caused it, and sealed the outcome
into a Cloud KMS-signed manifest that anyone can re-verify offline in under a second,
with no credentials.

Agents decide what to do. Deterministic code decides what is true and whether state may
change.

---

## What a reviewer should check, in order

Five questions, the artifact that answers each, and the command. None needs credentials.

| # | Question | Artifact | Command |
|---|---|---|---|
| 1 | Does the stored verdict follow from the stored state? | the two signed manifests | `make verify-demo` |
| 2 | What happens if I change one byte? | the same manifests | edit a manifest, re-run, get `RESULT: MISMATCH` and exit 1 |
| 3 | Does it refuse things it should refuse? | the 21-drill corpus | `make drills` |
| 4 | Does the repo reproduce from scratch? | a clean `git archive` extraction | `make clean-room` |
| 5 | Does every public number have a source? | `docs/CLAIMS.json` | each claim carries its evidence path, reproduce command, and limitation |

The single most informative page is `/app/fleet`. It is the permission matrix, and the
gaps in it are the whole thesis.

---

## Requirement by requirement

| # | Requirement | How it is met |
|---|---|---|
| 1 | Gemini 3.5+ via Gemini API or Vertex AI | `gemini-3.5-flash` through Vertex AI, `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, served from the `global` endpoint. Single model id in `nightshift/common/config.py`; no 2.x fallback path exists. Live at `/api/meta`. |
| 2 | A Google agent framework | Google ADK 2.7.1, load-bearing. Six `LlmAgent`s in `agents/fleet.py`, driven through `Runner.run_async` in `agents/orchestrator.py`. Version read at runtime and reported by `/api/meta`. |
| 3 | A Google Cloud infrastructure service | Eight Cloud Run services, Firestore with transactional commits, Cloud KMS asymmetric signing, Cloud Storage, Cloud Trace, Vertex AI. All confirmed live. |
| 4 | Newly created during the submission period | All application code written during the window. First commit `6b49e9c`, 2026-08-26. No vendored trees, no pre-existing code incorporated. |
| 5 | One track selected | Fortified Enterprise Fleet. |
| 6 | Text description | This document, and the Devpost description drawn from it. |
| 7 | Hosted URL | https://nightshift-web-xk6xxtobta-uc.a.run.app |
| 8 | Public repository | https://github.com/winsznx/night-shift |
| 9 | Spin-up instructions in the README | Two paths in `README.md`: a credential-free local path with expected output for each command, and a cloud path from `gcloud auth login` through `make deploy-web` and `make smoke-live`. |
| 10 | Architecture diagram | Inline in `README.md` and `ARCHITECTURE.md`, light and dark, naming Gemini, ADK, the Cloud Run services, Firestore, and the Next.js frontend. Two interactive HTML diagrams ship under `apps/web/public/diagrams/`. |
| 11 | Demo video, under 4 minutes, public | See Links. |

---

## What the numbers are, and what they are not

Two measurement tiers, never pooled, because the commands, seeds, drill selection and
holdout policy genuinely differ and a combined pass rate would describe no experiment
that was ever run.

**Deterministic tier.** 126 runs across the 21-drill corpus, six seeds. A fixed policy
drives the same broker, the same services and the same kernel with no model in the loop.
126 passed. 3,252 container custody commits. 54 faults injected across 36 runs. 24 broker
denials. Median run 0.6s.

**Live-agent tier.** 18 runs across 9 of the 21 drills, holdout excluded, two seeds, the
real Gemini fleet. 17 of 18 passed. 332 container commits, 0 unresolved. 162 model calls.
Median run 191.12s. No human in the loop.

The one failure is published rather than hidden, and it produced two new safety rules.
`docs/PROOF.md` tells that story.

**Content screening**, measured against a disclosed nine-payload family with three benign
controls: the Gemma classifier caught 6 of 6 malicious payloads, the offline regex layer
4 of 6, live Model Armor 2 of 6, with zero false positives across all three. Two payloads
were added specifically because the original set did not separate the layers. Raw result
in `evidence/content-screening.json`.

None of these three layers is what protects the system. The Dispatch Agent holds no
inventory authority, so a payload asking it to export specimen data has nothing to reach
whatever the screening concludes.

---

## Origination and disclosure

- All application code was written during the submission period. First commit `6b49e9c`,
  2026-08-26.
- Standard frameworks and libraries are used as intended. No pre-existing project code,
  no vendored trees.
- An AI coding assistant was used during development, which the rules permit explicitly.
- Every estate, specimen, responder and study record is synthetic. Physical responder
  movements are simulated by a bounded field simulator, disclosed on every page, in
  `/api/meta`, and inside every signed manifest.
- Two responder task tokens were published inside signed manifests before the writer
  redacted them. Both are rotated and dead; git history keeps them because rewriting it
  would invalidate the signatures. Disclosed in `LIMITATIONS.md`.
- What is not delivered is listed in `LIMITATIONS.md`, including agent cataloging via
  Agent Registry and Pub/Sub as an exercised transport.
- The Safety Kernel was ablated and measured. The same corpus at the same six seeds runs
  126 of 126 with the kernel and 96 of 126 without it, unmasking six N4 and six N10
  violations. Raw output in `evidence/ablation/ablation.json`, reproducible with
  `make ablation`. The live-agent tier was not ablated, and N1, N2 and N3 hold in both
  arms because authorization and the transactional commit are separate mechanisms.

---

## Links

| What | Where |
|---|---|
| Demo video | *(fill in: public YouTube URL)* |
| Repository walkthrough video | *(fill in, optional)* |
| Live product | https://nightshift-web-xk6xxtobta-uc.a.run.app |
| Public API | https://nightshift-api-xk6xxtobta-uc.a.run.app/api/meta |
| Repository | https://github.com/winsznx/night-shift |
| Signed proof page | https://nightshift-web-xk6xxtobta-uc.a.run.app/proof/INC-0E7C54F8B5 |
| Verify it yourself | https://nightshift-web-xk6xxtobta-uc.a.run.app/verify |
| Signed manifest, public and directly fetchable | https://storage.googleapis.com/nightshift-public-evidence-project-2ac1d1fb-7da1-46b4-90e/incidents/INC-0E7C54F8B5/manifest.json |
| Permission matrix | https://nightshift-web-xk6xxtobta-uc.a.run.app/app/fleet |
| Build writeup | https://medium.com/@winszn/i-tested-whether-a-resumable-adk-agent-runs-your-tool-twice-the-answer-depends-on-how-it-died-cda9920b42c2 |
| Social post | https://x.com/winsznlabs/status/2094490263175508372 |
