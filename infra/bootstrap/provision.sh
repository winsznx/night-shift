#!/usr/bin/env bash
# Provision Night Shift's stateful resources and per-agent identities. Idempotent.
#
#   ./infra/bootstrap/provision.sh [PROJECT_ID] [REGION]
#
# Creates: Firestore Native, Pub/Sub topics + DLQ, evidence bucket, KMS signing key,
# Model Armor template, Artifact Registry repo, and one service account per operational
# agent and per domain service.
#
# Deliberately NOT created: a locked bucket retention policy. Locking is irreversible
# and PRD §28 requires explicit approval before it happens.
set -euo pipefail

PROJECT="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}}"
REGION="${2:-${NIGHTSHIFT_REGION:-us-central1}}"
FIRESTORE_LOCATION="${NIGHTSHIFT_FIRESTORE_LOCATION:-nam5}"
BUCKET="nightshift-evidence-${PROJECT}"
KEYRING="nightshift"
KEY="evidence-signer"
ARMOR_TEMPLATE="nightshift-vendor-content"
REPO="nightshift"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()  { printf '  ok    %s\n' "$*"; }
skip(){ printf '  exists %s\n' "$*"; }

[[ -n "${PROJECT}" && "${PROJECT}" != "(unset)" ]] || { echo "ERROR: no project" >&2; exit 1; }
say "Provisioning Night Shift in ${PROJECT} (${REGION})"

# --- Firestore ------------------------------------------------------------------------
say "Firestore"
if gcloud firestore databases describe --database='(default)' --project="${PROJECT}" >/dev/null 2>&1; then
  skip "Firestore Native database"
else
  gcloud firestore databases create --location="${FIRESTORE_LOCATION}" \
    --type=firestore-native --project="${PROJECT}" >/dev/null
  ok "Firestore Native (${FIRESTORE_LOCATION})"
fi

# --- Pub/Sub --------------------------------------------------------------------------
say "Pub/Sub"
for topic in sensor-events incident-events field-scan-events facilities-events agent-work drill-events dead-letter-events; do
  if gcloud pubsub topics describe "${topic}" --project="${PROJECT}" >/dev/null 2>&1; then
    skip "topic ${topic}"
  else
    gcloud pubsub topics create "${topic}" --project="${PROJECT}" >/dev/null
    ok "topic ${topic}"
  fi
done

for topic in sensor-events incident-events field-scan-events facilities-events agent-work drill-events; do
  sub="${topic}-sub"
  if gcloud pubsub subscriptions describe "${sub}" --project="${PROJECT}" >/dev/null 2>&1; then
    skip "subscription ${sub}"
  else
    gcloud pubsub subscriptions create "${sub}" --topic="${topic}" \
      --dead-letter-topic="dead-letter-events" --max-delivery-attempts=5 \
      --ack-deadline=60 --project="${PROJECT}" >/dev/null
    ok "subscription ${sub} (DLQ after 5 attempts)"
  fi
done

# --- Cloud Storage --------------------------------------------------------------------
say "Evidence bucket"
if gcloud storage buckets describe "gs://${BUCKET}" --project="${PROJECT}" >/dev/null 2>&1; then
  skip "gs://${BUCKET}"
else
  gcloud storage buckets create "gs://${BUCKET}" --location="${REGION}" \
    --uniform-bucket-level-access --project="${PROJECT}" >/dev/null
  ok "gs://${BUCKET}"
fi
gcloud storage buckets update "gs://${BUCKET}" --versioning --project="${PROJECT}" >/dev/null
ok "object versioning on (retention policy deliberately NOT locked — see PRD §28)"

# --- Cloud KMS ------------------------------------------------------------------------
say "Cloud KMS signing key"
if gcloud kms keyrings describe "${KEYRING}" --location="${REGION}" --project="${PROJECT}" >/dev/null 2>&1; then
  skip "keyring ${KEYRING}"
else
  gcloud kms keyrings create "${KEYRING}" --location="${REGION}" --project="${PROJECT}" >/dev/null
  ok "keyring ${KEYRING}"
fi
if gcloud kms keys describe "${KEY}" --keyring="${KEYRING}" --location="${REGION}" --project="${PROJECT}" >/dev/null 2>&1; then
  skip "key ${KEY}"
else
  gcloud kms keys create "${KEY}" --keyring="${KEYRING}" --location="${REGION}" \
    --purpose=asymmetric-signing --default-algorithm=ec-sign-p256-sha256 \
    --project="${PROJECT}" >/dev/null
  ok "key ${KEY} (EC_SIGN_P256_SHA256)"
fi

mkdir -p keys
gcloud kms keys versions get-public-key 1 --key="${KEY}" --keyring="${KEYRING}" \
  --location="${REGION}" --project="${PROJECT}" --output-file=keys/kms-evidence-signer.pub.pem 2>/dev/null || true
ok "public key exported to keys/kms-evidence-signer.pub.pem"

# --- Model Armor ----------------------------------------------------------------------
say "Model Armor"
if gcloud model-armor templates describe "${ARMOR_TEMPLATE}" --location="${REGION}" --project="${PROJECT}" >/dev/null 2>&1; then
  skip "template ${ARMOR_TEMPLATE}"
else
  gcloud model-armor templates create "${ARMOR_TEMPLATE}" --location="${REGION}" \
    --project="${PROJECT}" \
    --pi-and-jailbreak-filter-settings-enforcement=enabled \
    --pi-and-jailbreak-filter-settings-confidence-level=LOW_AND_ABOVE \
    --basic-config-filter-enforcement=enabled >/dev/null
  ok "template ${ARMOR_TEMPLATE} (prompt-injection + jailbreak, LOW_AND_ABOVE)"
fi

# --- Artifact Registry ------------------------------------------------------------------
say "Artifact Registry"
if gcloud artifacts repositories describe "${REPO}" --location="${REGION}" --project="${PROJECT}" >/dev/null 2>&1; then
  skip "repository ${REPO}"
else
  gcloud artifacts repositories create "${REPO}" --repository-format=docker \
    --location="${REGION}" --description="Night Shift service images" \
    --project="${PROJECT}" >/dev/null
  ok "repository ${REPO}"
fi

# --- Identities -------------------------------------------------------------------------
# One service account per operational agent, and one per domain service. This is the
# least-privilege boundary: a compromised Dispatch Agent runs as an identity that has no
# grant on the Inventory service at all, so the denial happens at Cloud Run's edge and
# not only inside our own code.
say "Service accounts"
AGENT_SAS=(ns-commander ns-signal ns-impact ns-capacity ns-dispatch ns-custody ns-ingestor)
SERVICE_SAS=(ns-svc-telemetry ns-svc-inventory ns-svc-capacity ns-svc-facilities ns-svc-custody ns-svc-incident ns-svc-bff)

for sa in "${AGENT_SAS[@]}" "${SERVICE_SAS[@]}"; do
  email="${sa}@${PROJECT}.iam.gserviceaccount.com"
  if gcloud iam service-accounts describe "${email}" --project="${PROJECT}" >/dev/null 2>&1; then
    skip "${sa}"
  else
    gcloud iam service-accounts create "${sa}" --display-name="Night Shift ${sa}" \
      --project="${PROJECT}" >/dev/null
    ok "${sa}"
  fi
done

say "Baseline IAM"
grant() {
  gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:$1@${PROJECT}.iam.gserviceaccount.com" \
    --role="$2" --condition=None >/dev/null 2>&1 && ok "$1 -> $2" || true
}
for sa in "${SERVICE_SAS[@]}"; do
  grant "${sa}" roles/datastore.user
  grant "${sa}" roles/cloudtrace.agent
  grant "${sa}" roles/logging.logWriter
done
for sa in "${AGENT_SAS[@]}"; do
  grant "${sa}" roles/aiplatform.user
  grant "${sa}" roles/cloudtrace.agent
  grant "${sa}" roles/logging.logWriter
done
# Per-agent identity: the runtime that hosts agent execution must mint ID tokens *as*
# each agent account, otherwise every outbound call carries the container's ambient
# identity and the per-agent run.invoker grants are never exercised.
#
# Only ns-svc-bff gets this. An earlier version granted it to every domain service, which
# meant the Custody service could mint a token as the Dispatch Agent — a lateral path
# that contradicts the least-privilege claim this system is built on. The agent loop runs
# in exactly one place, so exactly one identity needs to impersonate, and a domain service
# that is compromised cannot borrow an agent's authority to call its peers.
say "Per-agent impersonation"
AGENT_RUNTIME_SA="ns-svc-bff"
for agent_sa in "${AGENT_SAS[@]}"; do
  gcloud iam service-accounts add-iam-policy-binding \
    "${agent_sa}@${PROJECT}.iam.gserviceaccount.com" \
    --member="serviceAccount:${AGENT_RUNTIME_SA}@${PROJECT}.iam.gserviceaccount.com" \
    --role=roles/iam.serviceAccountTokenCreator \
    --project="${PROJECT}" --quiet >/dev/null 2>&1 || true
done
ok "${AGENT_RUNTIME_SA} may mint tokens as the ${#AGENT_SAS[@]} agent accounts (no other service can)"

# Revoke the over-broad grants an earlier revision of this script created, so re-running
# it on an existing project actually tightens the policy instead of leaving it wide.
for runtime_sa in "${SERVICE_SAS[@]}"; do
  [[ "${runtime_sa}" == "${AGENT_RUNTIME_SA}" ]] && continue
  for agent_sa in "${AGENT_SAS[@]}"; do
    gcloud iam service-accounts remove-iam-policy-binding \
      "${agent_sa}@${PROJECT}.iam.gserviceaccount.com" \
      --member="serviceAccount:${runtime_sa}@${PROJECT}.iam.gserviceaccount.com" \
      --role=roles/iam.serviceAccountTokenCreator \
      --project="${PROJECT}" --quiet >/dev/null 2>&1 || true
  done
done
ok "revoked impersonation from domain services (idempotent tightening)"

grant ns-svc-bff roles/storage.objectViewer
grant ns-svc-incident roles/cloudkms.signerVerifier
grant ns-svc-incident roles/storage.objectAdmin

say "Done"
cat <<EOF

Provisioned:
  Firestore Native    (default) in ${FIRESTORE_LOCATION}
  Pub/Sub             7 topics, 6 subscriptions with a dead-letter topic
  Evidence bucket     gs://${BUCKET} (versioned, retention NOT locked)
  KMS signing key     ${REGION}/${KEYRING}/${KEY}
  Model Armor         ${ARMOR_TEMPLATE}
  Artifact Registry   ${REGION}/${REPO}
  Identities          ${#AGENT_SAS[@]} agent + ${#SERVICE_SAS[@]} service accounts

Add to your .env:
  GOOGLE_CLOUD_PROJECT=${PROJECT}
  NIGHTSHIFT_REGION=${REGION}
  NIGHTSHIFT_EVIDENCE_BUCKET=${BUCKET}
  NIGHTSHIFT_KMS_KEY=projects/${PROJECT}/locations/${REGION}/keyRings/${KEYRING}/cryptoKeys/${KEY}/cryptoKeyVersions/1
  NIGHTSHIFT_MODEL_ARMOR_TEMPLATE=projects/${PROJECT}/locations/${REGION}/templates/${ARMOR_TEMPLATE}

Next: ./infra/deploy/deploy_services.sh ${PROJECT} ${REGION}
EOF
