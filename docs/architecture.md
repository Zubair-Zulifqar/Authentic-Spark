# Architecture

```mermaid
flowchart LR
  U[Agency staff browser] -->|HTTPS| W[Next.js web<br/>Cloud Run]
  W -->|Bearer Firebase ID token| A[Quart API<br/>Cloud Run]
  U -.->|sign-in| F[Firebase Auth]
  A -->|verify token| F
  A --> DB[(Cloud SQL<br/>PostgreSQL)]
  A --> SM[Secret Manager]
  A --> GCS[Cloud Storage]
  CS[Cloud Scheduler] -->|POST /jobs/tick| A
  A --> AI[OpenAI]
  A --> EXT[Integrations<br/>Google, NGP VAN, Action Network, ActionKit,<br/>Scale to Win, ZeroBounce, QuickBooks,<br/>Asana, Slack, Mixpanel]
  EXT -->|signed webhooks| A
  A -->|signed webhooks| Z[Zapier / automation targets]
```

## Backend layout

```
backend/app/
  core/        config, db, auth (Firebase), rbac, errors, logging, audit, rate limit, http helpers
  models.py    SQLAlchemy models (tenant-scoped)
  blueprints/  core, email, contacts, sms, ads, billing, compliance, ai, platform  (all under /api/v1)
  services/    email_production, contacts, dns_checks, suppression, text_checks, events, invoice_pdf
  services/ai  providers (OpenAI / rule-based), agents (registry + orchestrator)
  services/integrations  base HTTP adapter + one module per provider + registry (live vs mock)
  jobs/        DB-backed queue (runner) and handlers
```

Principles:
- **Thin routes, reusable services.** Routes validate (Pydantic), authorize, call services, audit.
- **Server-side authorization on every route**, independent of UI visibility.
- **Adapters behind interfaces**; live clients use only documented endpoints; mocks are explicit (`mode="mock"`).
- **Human approval gates** on outbound communications, ad activation, billing and AI-proposed changes.
- **Idempotency** for jobs, webhook events, outbound creates (`external_mappings`) and payments.

Responses are `{"data": ...}` or `{"error": {"code","message","details"}}`; API version prefix `/api/v1`;
OpenAPI at `/api/v1/openapi.json`. Logs are JSON (Cloud Logging-compatible) with secret/PII key redaction and a
request ID per request.

## Third-party integrations

```mermaid
flowchart LR
  subgraph Core[Authentic Spark API]
    REG[Adapter registry<br/>live if credentials else mock]
  end
  REG --> GW[Google Docs / Drive / Sheets<br/>OAuth, least-privilege scopes]
  REG --> GA[Google Ads<br/>read-only reporting]
  REG --> VAN[NGP VAN<br/>bulk import]
  REG --> AN[Action Network / ActionKit<br/>draft creation only]
  REG --> STW[Scale to Win<br/>interface + mock]
  REG --> ZB[ZeroBounce<br/>validation]
  REG --> QBO[QuickBooks Online<br/>invoices, OAuth refresh]
  REG --> AS[Asana<br/>tasks]
  REG --> SL[Slack<br/>notifications]
  REG --> MP[Mixpanel<br/>events]
  QBO -->|intuit-signature| WH[Webhook endpoints<br/>verify + dedupe]
  AS -->|X-Hook-Signature| WH
  STW -->|X-Spark-Signature| WH
  WH --> Core
```

All live adapters share `HttpAdapter`: 20s timeouts, retry with exponential backoff on 429/5xx, `Retry-After`
support, and errors normalized to `IntegrationError` (HTTP 502) with provider details.
