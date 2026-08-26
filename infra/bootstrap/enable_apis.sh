#!/usr/bin/env bash
# Enable every Google Cloud API Night Shift needs. Idempotent.
#
#   ./infra/bootstrap/enable_apis.sh [PROJECT_ID]
set -euo pipefail

PROJECT="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}}"
if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "ERROR: no project. Pass one as \$1 or run: gcloud config set project PROJECT_ID" >&2
  exit 1
fi

echo "Project: ${PROJECT}"

BILLING=$(gcloud billing projects describe "${PROJECT}" --format="value(billingEnabled)" 2>/dev/null || echo "false")
if [[ "${BILLING}" != "True" && "${BILLING}" != "true" ]]; then
  cat >&2 <<EOF
ERROR: billing is not enabled on ${PROJECT}.

Cloud Run, Cloud Storage, Cloud KMS, and Vertex AI all refuse to enable without it.
Link an open billing account, then re-run this script:

  gcloud billing projects link ${PROJECT} --billing-account=YOUR_BILLING_ACCOUNT_ID
EOF
  exit 1
fi

REQUIRED=(
  run.googleapis.com
  artifactregistry.googleapis.com
  cloudbuild.googleapis.com
  firestore.googleapis.com
  pubsub.googleapis.com
  storage.googleapis.com
  cloudkms.googleapis.com
  secretmanager.googleapis.com
  cloudscheduler.googleapis.com
  aiplatform.googleapis.com
  cloudtrace.googleapis.com
  logging.googleapis.com
  monitoring.googleapis.com
  iam.googleapis.com
  iamcredentials.googleapis.com
  modelarmor.googleapis.com
  agentregistry.googleapis.com
  agentidentity.googleapis.com
  agentidentitycredentials.googleapis.com
)

echo "Enabling ${#REQUIRED[@]} APIs (this takes a minute)…"
gcloud services enable "${REQUIRED[@]}" --project="${PROJECT}"

echo
echo "Enabled. Next: ./infra/bootstrap/provision.sh ${PROJECT}"
