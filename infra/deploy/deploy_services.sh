#!/usr/bin/env bash
# Build one image and deploy the six domain services plus the public BFF to Cloud Run.
#
#   ./infra/deploy/deploy_services.sh [PROJECT_ID] [REGION]
#
# Each domain service runs as its own service account and requires authentication. Only
# the BFF is public, and it is read-only apart from responder scans gated on an
# unguessable dispatch token.
set -euo pipefail

PROJECT="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}}"
REGION="${2:-${NIGHTSHIFT_REGION:-us-central1}}"
REPO="nightshift"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/nightshift"
TAG="$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"
BUCKET="nightshift-evidence-${PROJECT}"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

[[ -n "${PROJECT}" && "${PROJECT}" != "(unset)" ]] || { echo "ERROR: no project" >&2; exit 1; }

say "Building ${IMAGE}:${TAG}"
gcloud builds submit --tag "${IMAGE}:${TAG}" --project="${PROJECT}" --quiet .

COMMON_ENV="GOOGLE_CLOUD_PROJECT=${PROJECT}"
COMMON_ENV="${COMMON_ENV},GOOGLE_CLOUD_LOCATION=global"
COMMON_ENV="${COMMON_ENV},GOOGLE_GENAI_USE_VERTEXAI=TRUE"
COMMON_ENV="${COMMON_ENV},NIGHTSHIFT_REGION=${REGION}"
COMMON_ENV="${COMMON_ENV},NIGHTSHIFT_MODEL_LOCATION=global"
COMMON_ENV="${COMMON_ENV},NIGHTSHIFT_MODEL=${NIGHTSHIFT_MODEL:-gemini-3.5-flash}"
COMMON_ENV="${COMMON_ENV},NIGHTSHIFT_STORE=firestore"
COMMON_ENV="${COMMON_ENV},NIGHTSHIFT_NAMESPACE=${NIGHTSHIFT_NAMESPACE:-demo}"
COMMON_ENV="${COMMON_ENV},NIGHTSHIFT_ENV=cloud-run"
COMMON_ENV="${COMMON_ENV},NIGHTSHIFT_TRACING=1"
COMMON_ENV="${COMMON_ENV},NIGHTSHIFT_COMMIT=${TAG}"
COMMON_ENV="${COMMON_ENV},NIGHTSHIFT_EVIDENCE_BUCKET=${BUCKET}"
COMMON_ENV="${COMMON_ENV},NIGHTSHIFT_KMS_KEY=projects/${PROJECT}/locations/${REGION}/keyRings/nightshift/cryptoKeys/evidence-signer/cryptoKeyVersions/1"
COMMON_ENV="${COMMON_ENV},NIGHTSHIFT_MODEL_ARMOR_TEMPLATE=projects/${PROJECT}/locations/${REGION}/templates/nightshift-vendor-content"

if [[ -n "${NIGHTSHIFT_AGENT_SECRET:-}" ]]; then
  COMMON_ENV="${COMMON_ENV},NIGHTSHIFT_AGENT_SECRET=${NIGHTSHIFT_AGENT_SECRET}"
fi

deploy() {
  local name="$1" service="$2" sa="$3" auth="$4"
  local flags=(--image="${IMAGE}:${TAG}"
               --region="${REGION}"
               --project="${PROJECT}"
               --service-account="${sa}@${PROJECT}.iam.gserviceaccount.com"
               --set-env-vars="${COMMON_ENV},NIGHTSHIFT_SERVICE=${service}"
               --min-instances=0
               --max-instances=4
               --cpu=1 --memory=1Gi
               --timeout=300
               --quiet)
  if [[ "${auth}" == "public" ]]; then
    flags+=(--allow-unauthenticated)
  else
    flags+=(--no-allow-unauthenticated)
  fi
  echo "  deploying ${name}…"
  gcloud run deploy "${name}" "${flags[@]}" >/dev/null
}

say "Deploying domain services (authenticated only)"
deploy nightshift-telemetry  telemetry        ns-svc-telemetry private
deploy nightshift-inventory  inventory        ns-svc-inventory private
deploy nightshift-capacity   capacity         ns-svc-capacity  private
deploy nightshift-facilities facilities       ns-svc-facilities private
deploy nightshift-custody    custody          ns-svc-custody   private
deploy nightshift-incident   incident_control ns-svc-incident  private

say "Deploying public BFF"
deploy nightshift-api bff ns-svc-bff public

url() { gcloud run services describe "$1" --region="${REGION}" --project="${PROJECT}" --format="value(status.url)"; }

TELEMETRY_URL=$(url nightshift-telemetry)
INVENTORY_URL=$(url nightshift-inventory)
CAPACITY_URL=$(url nightshift-capacity)
FACILITIES_URL=$(url nightshift-facilities)
CUSTODY_URL=$(url nightshift-custody)
INCIDENT_URL=$(url nightshift-incident)
API_URL=$(url nightshift-api)

say "Granting cross-service invoke, by agent identity"
# This is where the §11.3 matrix becomes Cloud Run IAM. An agent identity that has no
# business calling a service simply is not a run.invoker on it, so the denial happens at
# the platform edge — before the request reaches any Night Shift code.
invoker() {
  local svc="$1" sa="$2"
  gcloud run services add-iam-policy-binding "${svc}" \
    --region="${REGION}" --project="${PROJECT}" \
    --member="serviceAccount:${sa}@${PROJECT}.iam.gserviceaccount.com" \
    --role=roles/run.invoker --quiet >/dev/null 2>&1 && echo "  ${sa} -> ${svc}" || true
}

# Telemetry: read-only, and every agent that reasons about temperature needs some slice.
for sa in ns-commander ns-signal ns-impact ns-capacity ns-dispatch ns-custody ns-ingestor ns-svc-bff; do
  invoker nightshift-telemetry "${sa}"
done
# Inventory: impact analysis, custody scoping, and the ingestor's containment reflex.
for sa in ns-impact ns-custody ns-ingestor ns-svc-bff; do
  invoker nightshift-inventory "${sa}"
done
# Capacity: the broker writes; custody reads reservations.
for sa in ns-capacity ns-custody ns-svc-bff; do
  invoker nightshift-capacity "${sa}"
done
# Facilities: dispatch only. Note the absence of ns-impact and ns-custody.
for sa in ns-dispatch ns-svc-bff; do
  invoker nightshift-facilities "${sa}"
done
# Custody: the custody agent and the responder-facing BFF.
for sa in ns-custody ns-svc-bff; do
  invoker nightshift-custody "${sa}"
done
# Incident control: the commander requests transitions; the ingestor opens incidents.
for sa in ns-commander ns-ingestor ns-svc-bff; do
  invoker nightshift-incident "${sa}"
done

cat > infra/deploy/urls.env <<EOF
# Generated by deploy_services.sh at $(date -u +%Y-%m-%dT%H:%M:%SZ)
NIGHTSHIFT_TELEMETRY_URL=${TELEMETRY_URL}
NIGHTSHIFT_INVENTORY_URL=${INVENTORY_URL}
NIGHTSHIFT_CAPACITY_URL=${CAPACITY_URL}
NIGHTSHIFT_FACILITIES_URL=${FACILITIES_URL}
NIGHTSHIFT_CUSTODY_URL=${CUSTODY_URL}
NIGHTSHIFT_INCIDENT_URL=${INCIDENT_URL}
NIGHTSHIFT_API_URL=${API_URL}
NIGHTSHIFT_IMAGE=${IMAGE}:${TAG}
EOF

say "Deployed"
cat infra/deploy/urls.env
echo
echo "Public API:  ${API_URL}"
echo "Health:      curl -s ${API_URL}/healthz | jq"
