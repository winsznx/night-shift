#!/usr/bin/env bash
# Keep Night Shift running by itself through the judging window.
#
#   ./infra/deploy/schedule_operations.sh [PROJECT_ID] [REGION]
#
# Creates one Cloud Run Job and two Cloud Scheduler jobs:
#
#   nightshift-tick-telemetry   every 5 minutes, no model calls
#   nightshift-tick-incident    every 6 hours, runs the real agent fleet
#
# Why two cadences. The N4 freshness window is 900 seconds, so telemetry written once at
# seed time makes every backup destination ineligible a quarter of an hour later and the
# console reads as a dead system. That needs a tick faster than the window. A full agent
# rescue costs model calls and takes minutes, so it runs on its own slower schedule and
# under a hard cap.
#
# Run this AFTER deploy_services.sh, because the job runs the image that deploy builds.
set -euo pipefail

PROJECT="${1:-${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}}"
REGION="${2:-${NIGHTSHIFT_REGION:-us-central1}}"
SHOWCASE_NAMESPACE="${NIGHTSHIFT_NAMESPACE:-demo}"
AUTONOMOUS_NAMESPACE="${NIGHTSHIFT_AUTONOMOUS_NAMESPACE:-demo2}"
# Two namespaces, because an incident run re-seeds the estate from the fixture and that
# resets container custody. Running one in the namespace the console serves would reset
# the containers of an already-closed incident, so a settled rescue would start rendering
# as unreconciled. The showcase namespace is never re-seeded; the autonomous stream gets
# its own.
JOB="nightshift-tick"
SA="ns-scheduler@${PROJECT}.iam.gserviceaccount.com"
BUCKET="nightshift-evidence-${PROJECT}"

# The scheduler identity is deliberately not the API's. ns-svc-bff serves an
# unauthenticated public surface, and giving it KMS signing and bucket write so a
# background job could reuse it would widen the blast radius of the one service anyone
# on the internet can reach.
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

[[ -n "${PROJECT}" && "${PROJECT}" != "(unset)" ]] || { echo "ERROR: no project" >&2; exit 1; }

IMAGE="$(grep '^NIGHTSHIFT_IMAGE=' infra/deploy/urls.env | cut -d= -f2-)"
[[ -n "${IMAGE}" ]] || { echo "ERROR: no NIGHTSHIFT_IMAGE in infra/deploy/urls.env" >&2; exit 1; }

say "Job image: ${IMAGE}"

ENV_VARS="GOOGLE_CLOUD_PROJECT=${PROJECT}"
ENV_VARS="${ENV_VARS},GOOGLE_CLOUD_LOCATION=global"
ENV_VARS="${ENV_VARS},GOOGLE_GENAI_USE_VERTEXAI=TRUE"
ENV_VARS="${ENV_VARS},NIGHTSHIFT_REGION=${REGION}"
ENV_VARS="${ENV_VARS},NIGHTSHIFT_MODEL_LOCATION=global"
ENV_VARS="${ENV_VARS},NIGHTSHIFT_MODEL=${NIGHTSHIFT_MODEL:-gemini-3.5-flash}"
ENV_VARS="${ENV_VARS},NIGHTSHIFT_STORE=firestore"
ENV_VARS="${ENV_VARS},NIGHTSHIFT_NAMESPACE=${SHOWCASE_NAMESPACE}"
ENV_VARS="${ENV_VARS},NIGHTSHIFT_ENV=cloud-run"
ENV_VARS="${ENV_VARS},NIGHTSHIFT_TRACING=1"
ENV_VARS="${ENV_VARS},NIGHTSHIFT_EVIDENCE_BUCKET=${BUCKET}"
ENV_VARS="${ENV_VARS},NIGHTSHIFT_KMS_KEY=projects/${PROJECT}/locations/${REGION}/keyRings/nightshift/cryptoKeys/evidence-signer/cryptoKeyVersions/1"
ENV_VARS="${ENV_VARS},NIGHTSHIFT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
# The six domain-service URLs, so a scheduled rescue makes the same authenticated
# Cloud Run calls a manual one does rather than quietly falling back in-process.
while IFS= read -r line; do
  case "${line}" in
    NIGHTSHIFT_*_URL=*) ENV_VARS="${ENV_VARS},${line}" ;;
  esac
done < infra/deploy/urls.env

say "Creating Cloud Run Job ${JOB}"
if gcloud run jobs describe "${JOB}" --region "${REGION}" --project "${PROJECT}" >/dev/null 2>&1; then
  ACTION=update
else
  ACTION=create
fi
gcloud run jobs "${ACTION}" "${JOB}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --service-account "${SA}" \
  --set-env-vars "${ENV_VARS}" \
  --max-retries 1 \
  --task-timeout 30m \
  --memory 2Gi \
  --command python \
  --args "scripts/scheduled_tick.py,--mode,telemetry" \
  --quiet

# Cloud Scheduler needs more than run.invoker to start a job with argument overrides.
# roles/run.invoker returns PERMISSION_DENIED on :run with an overrides body, at project
# level and on the job, on both the v1 namespaces path and the v2 path. The role that
# actually carries it is run.jobsExecutorWithOverrides, which exists for this exact case.
say "Scheduler invoke permission"
gcloud run jobs add-iam-policy-binding "${JOB}" \
  --region "${REGION}" --project "${PROJECT}" \
  --member "serviceAccount:${SA}" \
  --role roles/run.jobsExecutorWithOverrides --quiet >/dev/null 2>&1 \
  && echo "  ${SA} may run ${JOB} with overrides" || true

say "Scheduler jobs"
schedule_job() {
  local name="$1" cron="$2" mode="$3" extra="$4"
  # The v2 jobs endpoint. The v1 namespaces path answers PERMISSION_DENIED for a
  # scheduler identity even with run.invoker on the job, and v2 is the surface the
  # overrides field is actually documented on.
  local uri="https://run.googleapis.com/v2/projects/${PROJECT}/locations/${REGION}/jobs/${JOB}:run"
  local body
  body="{\"overrides\":{\"containerOverrides\":[{\"args\":[\"scripts/scheduled_tick.py\",\"--mode\",\"${mode}\"${extra}]}]}}"
  local action=create
  gcloud scheduler jobs describe "${name}" --location "${REGION}" --project "${PROJECT}" >/dev/null 2>&1 && action=update
  gcloud scheduler jobs "${action}" http "${name}" \
    --location "${REGION}" \
    --project "${PROJECT}" \
    --schedule "${cron}" \
    --time-zone "Etc/UTC" \
    --uri "${uri}" \
    --http-method POST \
    --headers "Content-Type=application/json" \
    --message-body "${body}" \
    --oauth-service-account-email "${SA}" \
    --attempt-deadline 1800s \
    --quiet
  echo "  ${name}: ${cron} (${mode})"
}

# Every five minutes against a 900 second freshness window. Ten minutes would also be
# "faster than the window", but it leaves only 300 seconds of margin, so a single missed
# or slow tick puts the estate over the threshold. A judge arriving at a random moment in
# a month-long window is exactly the case that margin exists for.
schedule_job "nightshift-tick-telemetry" "*/5 * * * *" "telemetry" \
  ",\"--namespace\",\"${SHOWCASE_NAMESPACE}\""

# Four a day is the cap the job itself enforces, so this cadence and that cap agree.
schedule_job "nightshift-tick-incident" "0 */6 * * *" "incident" \
  ",\"--namespace\",\"${AUTONOMOUS_NAMESPACE}\",\"--max-per-day\",\"4\",\"--max-total\",\"200\""

# The autonomous namespace needs its own freshness tick too, or a rescue that starts six
# hours after the last one finds every destination past the N4 window and refuses,
# correctly, to place anything.
schedule_job "nightshift-tick-autonomous-telemetry" "*/5 * * * *" "telemetry" \
  ",\"--namespace\",\"${AUTONOMOUS_NAMESPACE}\""

say "Scheduled"
gcloud scheduler jobs list --location "${REGION}" --project "${PROJECT}" \
  --format="table(name.basename(),schedule,state)" 2>/dev/null || true
echo
echo "Run one now:   gcloud scheduler jobs run nightshift-tick-telemetry --location ${REGION}"
echo "Job logs:      gcloud run jobs executions list --job ${JOB} --region ${REGION}"
echo "Pause spend:   gcloud scheduler jobs pause nightshift-tick-incident --location ${REGION}"
