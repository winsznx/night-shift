# Phase 0 — Sponsor seam spike results

Recorded 26 Aug 2026 against project `project-2ac1d1fb-7da1-46b4-90e`, region
`us-central1`. Every row below was produced by running the command shown, not inferred
from documentation.

## Environment

| Component | Version |
|---|---|
| Google Cloud SDK | 582.0.0 |
| Python | 3.12.14 (via `uv`) |
| `google-adk` | 2.7.1 |
| `google-genai` | 2.20.0 |
| `google-cloud-firestore` | 2.29.0 |
| `google-cloud-kms` | 3.16.0 |
| Node | 24.19.0 |
| Next.js | 15.5.4 |

## What worked

| Capability | Result | How it was proved |
|---|---|---|
| Gemini 3.5 Flash on Vertex AI | ✅ live | `POST .../global/publishers/google/models/gemini-3.5-flash:generateContent` → 200 |
| Google ADK agents + tools | ✅ live | six `LlmAgent` specialists driving a full incident to `CLOSED` |
| ADK resumability | ✅ live | `App(resumability_config=ResumabilityConfig(is_resumable=True))` |
| ADK plugin tool interception | ✅ live | `BasePlugin.after_tool_callback` fired mid-run |
| Firestore Native | ✅ live | database created in `nam5`, transactional reservation commits |
| Firestore transactions | ✅ live | concurrent reservation test: one commits, one refused on N1 |
| Pub/Sub | ✅ live | 7 topics, 6 subscriptions with a dead-letter topic |
| Cloud Run | ✅ live | 7 services deployed, 6 authenticated + 1 public |
| Cloud KMS asymmetric signing | ✅ live | `EC_SIGN_P256_SHA256`, signature verifies, tamper detected |
| Cloud Storage | ✅ live | versioned evidence bucket |
| Cloud Trace API | ✅ live | `traces:batchWrite` → 200 |
| Model Armor | ✅ live | prompt-injection payload matched at **HIGH** confidence |
| Agent Registry API | ✅ reachable | `gcloud alpha agent-registry agents list` returned results |
| Agent Identity API | ✅ reachable | `gcloud agent-identity auth-providers list --location=us-central1` |
| Agent Runtime (`reasoningEngines`) | ✅ reachable | `GET .../v1beta1/.../reasoningEngines` → 200 |

## The finding that shaped the architecture

PRD §22 asks what ADK does to an effectful tool on resume. Rather than assume, three
different interruption shapes were provoked against a real Gemini-backed run
(`scripts/spike_adk_resume.py`):

| Variant | Tool re-invoked on resume? | Duplicate effect? |
|---|---|---|
| A — `after_tool_callback` raises after the effect commits | no | no |
| B — the tool itself raises after committing | no | no |
| C — the invocation is cancelled mid-flight (a worker actually dying) | **yes** | no |

Variant C is the one that matters. The resumed run called `reserve_capacity` a second
time — 2 tool calls, 1 committed effect — and the second call returned the first call's
receipt because the semantic action ID was identical.

That is the empirical basis for the whole idempotency design. Semantic action IDs and
receipt replay are load-bearing, not defensive: without them, a worker dying at the
wrong moment double-books a freezer.

Reproduce:

```bash
uv run python scripts/spike_adk_resume.py
```

## Model endpoint location

Gemini 3.5 Flash is **not** served from `us-central1`:

```
us-central1  gemini-3.5-flash   HTTP 404  Publisher model ... was not found
global       gemini-3.5-flash   HTTP 200  -> OK
us-central1  gemini-2.5-flash   HTTP 200  -> OK
```

So `NIGHTSHIFT_MODEL_LOCATION=global` while all regional infrastructure stays in
`us-central1`. PRD §6.4 permits a coherent alternative where service availability forces
one; this is that case, and using 2.5 Flash to keep a single region would have violated
the "Gemini 3.5 or newer" requirement instead.

## Blocked, then unblocked

The first project's billing account was in state `closed`, which blocks Cloud Run,
Cloud Storage, Cloud KMS, and all Vertex surfaces:

```
ERROR: FAILED_PRECONDITION: Billing account for project '570142838740' is not open.
       reason: UREQ_PROJECT_BILLING_NOT_OPEN
```

Notably, Firestore Native, Pub/Sub, and Cloud Trace *did* enable and work without
billing. The build moved to a project with an open billing account and the full sponsor
path became available. This was the one blocker PRD §0.2 classifies as requiring user
input, and it was raised once.

## Deployment defects found

Two, both silent until runtime:

1. Cloud Build's default compute service account had no `storage.objects.get` on its own
   staging bucket. Fixed by granting `roles/storage.admin`,
   `roles/artifactregistry.writer`, and `roles/cloudbuild.builds.builder`.
2. `.gcloudignore` contained an unanchored `evidence/` pattern, which also matched
   `nightshift/evidence/` and stripped a Python package out of the build context. The
   container failed to start with `ModuleNotFoundError: No module named
   'nightshift.evidence'` — an error that says nothing about ignore rules. Every pattern
   is now anchored with a leading `/`.
