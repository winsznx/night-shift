#!/usr/bin/env bash
# Build and deploy the Next.js judge-facing app to Cloud Run.
#
#   ./infra/deploy/deploy_web.sh [PROJECT_ID] [REGION]
set -euo pipefail

PROJECT="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}}"
REGION="${2:-${NIGHTSHIFT_REGION:-us-central1}}"
REPO="nightshift"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/nightshift-web"
TAG="$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)"

[[ -n "${PROJECT}" && "${PROJECT}" != "(unset)" ]] || { echo "ERROR: no project" >&2; exit 1; }

API_URL="${NIGHTSHIFT_API_URL:-}"
if [[ -z "${API_URL}" && -f infra/deploy/urls.env ]]; then
  API_URL=$(grep '^NIGHTSHIFT_API_URL=' infra/deploy/urls.env | cut -d= -f2-)
fi
[[ -n "${API_URL}" ]] || { echo "ERROR: no NIGHTSHIFT_API_URL; run deploy_services.sh first" >&2; exit 1; }

printf '\n\033[1mBuilding %s:%s\033[0m\n' "${IMAGE}" "${TAG}"
gcloud builds submit --tag "${IMAGE}:${TAG}" --project="${PROJECT}" --quiet apps/web

printf '\n\033[1mDeploying nightshift-web\033[0m (API: %s)\n' "${API_URL}"
gcloud run deploy nightshift-web \
  --image="${IMAGE}:${TAG}" \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --service-account="ns-svc-bff@${PROJECT}.iam.gserviceaccount.com" \
  --set-env-vars="NIGHTSHIFT_API_URL=${API_URL},NODE_ENV=production" \
  --allow-unauthenticated \
  --min-instances=0 --max-instances=4 \
  --cpu=1 --memory=1Gi --timeout=120 \
  --quiet >/dev/null

WEB_URL=$(gcloud run services describe nightshift-web --region="${REGION}" --project="${PROJECT}" --format="value(status.url)")
grep -v '^NIGHTSHIFT_WEB_URL=' infra/deploy/urls.env > infra/deploy/urls.env.tmp 2>/dev/null || true
mv infra/deploy/urls.env.tmp infra/deploy/urls.env 2>/dev/null || true
echo "NIGHTSHIFT_WEB_URL=${WEB_URL}" >> infra/deploy/urls.env

printf '\n\033[1mDeployed\033[0m\n'
echo "  Web  ${WEB_URL}"
echo "  API  ${API_URL}"
