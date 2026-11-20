#!/usr/bin/env bash
# Creates the Cloud Scheduler job that drives background work. Review before running; it creates billable resources.
set -euo pipefail
: "${PROJECT_ID:?}" "${REGION:?}" "${API_URL:?}" "${SCHEDULER_TOKEN:?}"
# Every 5 minutes: enqueue daily jobs (idempotent per day) and drain the queue.
gcloud scheduler jobs create http spark-jobs-tick \
  --project "$PROJECT_ID" --location "$REGION" --schedule "*/5 * * * *" \
  --uri "${API_URL}/api/v1/jobs/tick" --http-method POST \
  --headers "Authorization=Bearer ${SCHEDULER_TOKEN}" \
  --attempt-deadline 300s
