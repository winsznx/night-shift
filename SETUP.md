# Setup

Two paths. The first needs nothing but a terminal. The second needs a Google Cloud
project with billing enabled.

---

## 1. Deterministic reproduction — no credentials

Everything in this section runs offline. No Google Cloud project, no API key, no
network beyond installing dependencies.

### Requirements

| Tool | Version | Install |
|---|---|---|
| `uv` | ≥ 0.5 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node | ≥ 20 | `nvm install 22` |
| `pnpm` | ≥ 9 | `corepack enable && corepack prepare pnpm@latest --activate` |

Python 3.12 is installed by `uv` — you do not need it beforehand.

### Steps

```bash
git clone <repository-url> night-shift
cd night-shift

make setup          # installs Python 3.12, Python deps, and web deps
make test           # 140 unit, property, and integration tests
make drills         # the full drill corpus, deterministic tier
make verify-demo    # verify every published manifest
```

`make test` and `make drills` should both finish in well under a minute. If
`make verify-demo` reports `PARTIAL` it means a manifest is unsigned, which is expected
when the manifest was produced without a KMS key. It never reports `PASS` for something
it could not check.

### Run the web app against the in-memory store

```bash
make run-local
# API  http://127.0.0.1:8081
# Web  http://127.0.0.1:3000
```

The estate is generated from a seed on first read, so the console is populated
immediately. No incident exists until one is run.

---

## 2. Live Google Cloud

### Requirements

- A Google Cloud project with an **open billing account**. Cloud Run, Cloud Storage,
  Cloud KMS, and Vertex AI all refuse to enable without one.
- `gcloud` CLI, authenticated.

### Authenticate

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

### Provision

```bash
make bootstrap PROJECT=YOUR_PROJECT_ID REGION=us-central1
```

This enables ~19 APIs and creates, idempotently:

- Firestore Native in `nam5`
- 7 Pub/Sub topics and 6 subscriptions with a dead-letter topic
- a versioned evidence bucket (retention deliberately **not** locked — see LIMITATIONS)
- a Cloud KMS `EC_SIGN_P256_SHA256` signing key
- a Model Armor template with prompt-injection and jailbreak filters
- an Artifact Registry repository
- 7 agent service accounts and 7 service service accounts

It prints the exact `.env` block to copy. Do that:

```bash
cp .env.example .env
# paste the block the bootstrap script printed
python -c "import secrets; print(secrets.token_urlsafe(32))"   # NIGHTSHIFT_AGENT_SECRET
```

### Deploy

```bash
make deploy PROJECT=YOUR_PROJECT_ID REGION=us-central1
```

Builds one image and deploys seven Cloud Run services: six authenticated domain services
and one public BFF. It then grants cross-service `run.invoker` by agent identity, which
is where the permission matrix becomes platform IAM. Service URLs are written to
`infra/deploy/urls.env`.

### Seed the demo and publish evidence

```bash
uv run python scripts/seed_demo.py --store firestore --namespace demo --rounds 8
```

Runs a real incident with the live Gemini fleet, then compiles, signs, and publishes the
evidence bundle to `evidence/incidents/` and Cloud Storage.

### Verify the deployment

```bash
make smoke-live
```

### Deploy the web app

The web app is a standard Next.js application. Point it at the BFF and deploy it
anywhere that runs Node, or run it locally against the live API:

```bash
cd apps/web
NIGHTSHIFT_API_URL=$(grep NIGHTSHIFT_API_URL ../../infra/deploy/urls.env | cut -d= -f2) pnpm dev
```

---

## Environment variables

Copy `.env.example` to `.env`. Nothing in `.env` is required for the deterministic path.

| Variable | Purpose |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | Project for Firestore, KMS, Vertex, Storage |
| `GOOGLE_CLOUD_LOCATION` | `global` — where Gemini 3.5 Flash is served |
| `NIGHTSHIFT_REGION` | `us-central1` — every regional resource |
| `NIGHTSHIFT_MODEL` | `gemini-3.5-flash` |
| `NIGHTSHIFT_STORE` | `memory` for offline, `firestore` for live |
| `NIGHTSHIFT_NAMESPACE` | Collection prefix. Drills get their own automatically. |
| `NIGHTSHIFT_KMS_KEY` | Full crypto key version resource name |
| `NIGHTSHIFT_SIGNER` | `auto` prefers KMS and falls back loudly to a local key |
| `NIGHTSHIFT_EVIDENCE_BUCKET` | Cloud Storage bucket for evidence bundles |
| `NIGHTSHIFT_MODEL_ARMOR_TEMPLATE` | Model Armor template resource name |
| `NIGHTSHIFT_AGENT_SECRET` | HMAC secret for local agent principal tokens |

---

## Command reference

```
make setup          install everything
make test           unit + property + integration
make lint           ruff
make typecheck      mypy + tsc
make build          build the web app
make check          lint + typecheck + test + secret scan
make run-local      BFF and web app against the in-memory store
make incident       one live incident with the real agent fleet
make drills         the drill corpus, deterministic tier
make evidence       the measurement campaign
make evidence-agent the live-agent campaign tier (slow)
make verify-demo    verify every published manifest
make seed-demo      run an incident and publish signed evidence
make spike          re-run the ADK resume seam spike
make bootstrap      enable APIs and provision GCP
make deploy         build and deploy to Cloud Run
make smoke-live     check the deployed public API
make e2e            Playwright judge-path suite
make clean-room     reproduce from a clean clone in a temp directory
```

---

## Troubleshooting

**`FAILED_PRECONDITION: Billing account ... is not open`** — link an open billing
account. Firestore, Pub/Sub, and Cloud Trace work without billing; Cloud Run, Storage,
KMS, and Vertex do not.

**`Publisher model gemini-3.5-flash was not found`** — the model location is wrong.
`NIGHTSHIFT_MODEL_LOCATION` must be `global`; `us-central1` only serves 2.5.

**Cloud Build `storage.objects.get` denied** — the default compute service account needs
access to its own staging bucket:

```bash
PN=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${PN}-compute@developer.gserviceaccount.com" \
  --role=roles/storage.admin --condition=None
```

**`ModuleNotFoundError` in a Cloud Run container that builds fine locally** — check
`.gcloudignore`. An unanchored pattern like `evidence/` also matches
`nightshift/evidence/` and silently removes a package from the build context.

**Destination reservations all refused as stale** — the fixture epoch has drifted past
the freshness window. `build_estate()` anchors to now by default; a pinned epoch is for
deterministic drills only.
