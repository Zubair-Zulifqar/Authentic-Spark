# One-time Google Cloud setup (manual, requires authorization — creates billable resources)

1. `gcloud artifacts repositories create authentic-spark --repository-format=docker --location=$REGION`
2. Cloud SQL for PostgreSQL 16 instance + database `authentic_spark`; store
   `postgresql+asyncpg://USER:PASS@/authentic_spark?host=/cloudsql/PROJECT:REGION:INSTANCE` in Secret Manager as `spark-database-url`.
3. Secrets: `spark-webhook-secret`, `spark-scheduler-token`, and provider credentials (`openai-api-key`, `zerobounce-api-key`, …).
4. Service account `spark-api@PROJECT.iam.gserviceaccount.com` with `roles/cloudsql.client`, `roles/secretmanager.secretAccessor`,
   `roles/storage.objectAdmin` on the uploads bucket only.
5. Cloud Storage bucket for list exports / creative assets with uniform bucket-level access, no public access, 30-day lifecycle on `exports/`.
6. Firebase project: enable Email/Password and Google providers; add the web app domain to authorized domains.
7. Run `infra/cloudbuild.yaml`, then `infra/scheduler.sh`.
