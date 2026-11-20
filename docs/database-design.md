# Database design

**Choice:** PostgreSQL on Cloud SQL in production (relational integrity, transactions for approvals and payments,
JSON columns for flexible validation/check payloads, mature backups/PITR). SQLAlchemy 2 async with `asyncpg`.
SQLite (`aiosqlite`) is used for local development and tests through the same models.

```mermaid
erDiagram
  ORGANIZATION ||--o{ CLIENT : has
  ORGANIZATION ||--o{ MEMBERSHIP : grants
  USER ||--o{ MEMBERSHIP : holds
  CLIENT ||--o{ MEMBERSHIP : "scoped (optional)"
  CLIENT ||--o{ CAMPAIGN : runs
  CLIENT ||--o{ EMAIL_CALENDAR : plans
  EMAIL_CALENDAR ||--o{ SCHEDULED_EMAIL : contains
  CLIENT ||--o{ PRODUCTION_RECORD : produces
  CLIENT ||--o{ CONTACT_LIST : acquires
  CONTACT_LIST ||--o{ CONTACT : contains
  CONTACT_LIST ||--o{ IMPORT_ISSUE : logs
  CLIENT ||--o{ SMS_CAMPAIGN : runs
  CLIENT ||--o{ AD_CREATIVE : owns
  AD_CREATIVE ||--o{ AD_CREATIVE_VERSION : versions
  CLIENT ||--o{ INVOICE : billed
  INVOICE ||--o{ PAYMENT : receives
  CLIENT ||--o{ SUPPRESSION : "client scope"
  ORGANIZATION ||--o{ SUPPRESSION : "global scope"
  CLIENT ||--o{ COMPLIANCE_EVENT : records
  CLIENT ||--o{ SENDING_DOMAIN : sends_from
  ORGANIZATION ||--o{ AUTOMATION_SUBSCRIPTION : configures
  AUTOMATION_SUBSCRIPTION ||--o{ AUTOMATION_EXECUTION : delivers
```

Other tables: `teams`, `projects`, `integration_connections`, `oauth_states`, `external_mappings`, `webhook_events`,
`jobs`, `agent_executions`, `audit_logs`.

Key constraints and indexes:
- Every tenant table has `organization_id` (+ `client_id`), indexed; composite indexes on hot paths
  (`contacts(client_id,email_normalized)`, `scheduled_emails(client_id,send_date)`, `audit_logs(org,client,created_at)`).
- Uniques: `memberships(user,org,client)`, `contacts(list_id,email_normalized)`, `suppressions(org,client,channel,value)`,
  `invoices(org,number)`, `payments(source,external_id)`, `webhook_events(provider,event_key)`,
  `jobs(idempotency_key)`, `external_mappings(provider,idempotency_key)`, `automation_executions(subscription,event)`.
- Timestamps `created_at`/`updated_at` (UTC) on all rows; UUID hex primary keys.

Retention: audit logs 3 years, succeeded jobs 90 days (daily `retention` job). Contact records follow client
agreements. Only synthetic data is used in development and tests.

Migrations: currently `create_all` at startup; adopt Alembic before the first production schema change
(`alembic init`, autogenerate from `Base.metadata`, run `alembic upgrade head` as a Cloud Run job before deploy).
