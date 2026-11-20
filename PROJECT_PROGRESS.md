# Project progress

Last updated: 2026-11-20

## Status by phase

| Phase | Status | Notes |
|---|---|---|
| 1 Foundation | Done | Quart API, SQLAlchemy models, Firebase/dev auth, RBAC, orgs/clients/memberships, Docker files |
| 2 Operations dashboard | Done | Agency dashboard, client workspaces, campaigns, projects, teams, members, audit/activity |
| 3 Email operations | Done | Calendars (day/week/month/list), AI plan + approval, Docs export, conversion, validation, preview, approval, test prep, handoff, Asana |
| 4 Contacts & SMS | Done (Scale to Win mock-only) | CSV pipeline, ZeroBounce, NGP VAN bulk import, SMS consent/STOP/approval/provisioning |
| 5 Advertising & billing | Done | Creative checks/versioning/approval, Google Ads reporting, invoices, PDF, QBO create + webhooks |
| 6 AI & automation | Done | 6 agents, orchestration, approvals, job queue, scheduler tick, signed webhooks in/out |
| 7 Compliance & analytics | Done | DNS checks, suppression, unsubscribe classification, Mixpanel, analytics endpoints/UI |
| 8 Testing & deployment | Done | 52 pytest, 8 Vitest, 1 Playwright E2E; Cloud Build/Run/Scheduler configs; CI workflow |
| 9 GitHub delivery | See final report | |

## Verified locally

- `pytest`: 52 passed. `ruff`: clean. `mypy`: clean (with documented relaxations, see limitations).
- Frontend: ESLint clean, `tsc --noEmit` clean, Vitest 8 passed, `next build` succeeded.
- Playwright smoke test passed against a seeded API + production web build.
- Docker images: **not built locally** (Docker not installed on the dev machine); CI builds both.

## Integration status

| Integration | Implementation | Mode without credentials |
|---|---|---|
| Firebase Auth | Server-side ID-token verification (revocation checked), web SDK login/Google/reset/verify | Dev tokens |
| OpenAI | Structured outputs via strict JSON schema | Rule-based provider (labelled `rule_based`) |
| ZeroBounce | `/v2/validate`, `/v2/getcredits`, bulk `/v2/validatebatch` | Mock |
| NGP VAN | Basic auth, `/v4/echoes`, `/v4/bulkImportJobs` create + status | Mock |
| Action Network | `POST /api/v2/messages` (draft) | Mock |
| ActionKit | `POST /rest/v1/mailer/` (draft) | Mock |
| Scale to Win | **Interface + mock only** — API reference not public | Mock |
| Google Docs/Drive/Sheets | REST clients, least-privilege scopes, OAuth start/callback with state | Mock (seeded doc) |
| Google Ads | REST `listAccessibleCustomers`, GAQL search (read-only) | Mock |
| QuickBooks Online | OAuth URLs, token refresh, invoice create (requestid idempotency), webhook HMAC | Mock |
| Asana | Tasks create/update/comment, webhook handshake + signature | Mock |
| Slack | `chat.postMessage`, per-client channel routing | Mock |
| Mixpanel | `/track` | Disabled |
| Zapier | First-party signed webhooks (REST hooks) | Live |

## Required credentials (none committed)

`FIREBASE_PROJECT_ID` + web config, `OPENAI_API_KEY`, `ZEROBOUNCE_API_KEY`, `NGPVAN_APP_NAME`/`NGPVAN_API_KEY`,
Action Network API token, ActionKit instance credentials, Scale to Win API access + reference, `GOOGLE_OAUTH_CLIENT_ID`/`SECRET`,
`GOOGLE_ADS_DEVELOPER_TOKEN`, `QBO_CLIENT_ID`/`SECRET`/`QBO_WEBHOOK_VERIFIER_TOKEN`, `ASANA_ACCESS_TOKEN`/`ASANA_WEBHOOK_SECRET`,
`SLACK_BOT_TOKEN`, `MIXPANEL_TOKEN`, `WEBHOOK_SIGNING_SECRET`, `SCHEDULER_TOKEN`, Cloud SQL `DATABASE_URL`.

## Known limitations / next steps

1. **OAuth token exchange**: start/callback with single-use 10-minute state are implemented; exchanging the code and
   writing tokens to Secret Manager, plus loading per-tenant tokens into the Google/QBO adapters, is not wired yet —
   those adapters run in mock mode until then. Action Network/ActionKit live clients exist but are not selected by the
   registry (no per-tenant credential loading yet).
2. **Scale to Win** has no live client (no public API reference). Implement `SmsProvider` against your account docs.
3. **Migrations**: tables are created with `metadata.create_all` at startup. Add Alembic before the first production
   schema change.
4. **Rate limiting** is per instance (in-memory). Use Cloud Armor or a shared store for global limits.
5. **File storage**: CSV uploads are parsed in memory and not persisted; creative assets are referenced by URI.
   Signed-URL upload to Cloud Storage is documented, not implemented.
6. **mypy** runs with `union-attr`/`arg-type`/etc. disabled because `session.get()` returns Optional after ownership
   checks; tightening this is a follow-up.
7. AI agents: OpenAI path is implemented but was exercised in tests only via provider fakes (no API key available).
8. Retention: audit logs 3 years, succeeded jobs 90 days (daily `retention` job). Contact data retention policy is
   client-specific and should be configured per agreement.
