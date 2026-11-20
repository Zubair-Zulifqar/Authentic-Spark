# Authentic Spark

An AI-assisted operations platform for digital agencies, nonprofits, fundraising organizations and campaigns. One
multi-tenant application replaces disconnected tools for client management, email planning and production, vendor
contact lists, SMS administration, ad creative review, invoicing, deliverability/compliance and automation.

> Original project with synthetic data. Not affiliated with any agency, vendor or client.

## Highlights

- **Multi-client isolation** — agency → clients → campaigns; every query is tenant-scoped and every route enforces
  RBAC server-side (9 roles, agency/client/module-level grants). Cross-tenant access returns 404.
- **Email operations** — calendar planning (AI proposal → human approval → scheduled emails), Google Doc → email-safe
  HTML conversion, 14 validation checks, sandboxed preview, approval, test-send prep, CRM draft handoff, Asana tasks.
- **List Buys** — CSV upload with column mapping, validation, in-file and cross-list de-duplication, suppression
  matching, ZeroBounce verification as a background job, auditable source/consent, NGP VAN bulk-import handoff.
- **SMS** — consent-only recipient counts, STOP keyword auto-suppression, compliance checks, approval gate,
  provisioning (never sending).
- **Advertising** — Meta/Google creatives with character limits, proofreading, disclosure and brand checks,
  versioning, review/approval; read-only Google Ads reporting.
- **Invoicing** — previews, finance approval, idempotent QuickBooks invoice creation, PDF generation, signed and
  de-duplicated QuickBooks webhooks syncing payments.
- **Compliance** — SPF/DKIM/DMARC DNS checks, global + client suppression lists, AI-assisted unsubscribe
  classification where **explicit opt-outs are always honored by rules first**, human review for ambiguous cases.
- **AI hub** — six agents with input/output JSON schemas, permissions, approval requirements, execution history,
  token usage and audit logs; OpenAI structured outputs with a labelled deterministic fallback.
- **Automation** — signed outbound webhooks (Zapier REST-hook compatible) with retries and idempotency, signed
  inbound webhooks, DB-backed job queue driven by Cloud Scheduler, per-client Slack routing, Mixpanel events.

## Stack

| Layer | Tech |
|---|---|
| Web | Next.js 15, React 19, TypeScript, Tailwind CSS 4, Radix UI, TanStack Query, Zustand |
| API | Python 3.12+, Quart (async), SQLAlchemy 2 async, Pydantic 2, Hypercorn |
| Data | PostgreSQL (Cloud SQL) in production; SQLite for local dev/tests |
| Auth | Firebase Authentication (ID token verification server-side) |
| AI | OpenAI Chat Completions with strict JSON-schema outputs, provider-independent interface |
| Infra | Docker, Cloud Run, Cloud Build, Cloud Scheduler, Secret Manager, Cloud Storage, GitHub Actions |

## Quick start (local, no credentials needed)

```bash
# API
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env   # optional; defaults work
.venv/bin/python -m app.seed
.venv/bin/hypercorn app.main:app -b 127.0.0.1:8080

# Web (new terminal)
cd frontend
npm install
cp .env.example .env.local
npm run dev            # http://localhost:3000 — sign in as admin@spark.example
```

`AUTH_MODE=dev` accepts `dev:<email>` bearer tokens for local work only; it is refused when `APP_ENV=production`.
Seeded users: `admin@`, `ops@`, `email@`, `finance@`, `compliance@` (agency-wide) and `am@spark.example`
(account manager scoped to one client — useful for seeing isolation).

With Docker: `docker compose up --build` then `docker compose exec api python -m app.seed`.

## Tests

```bash
cd backend && .venv/bin/pytest -q            # 52 API/unit tests
cd frontend && npm test && npm run build     # Vitest + production build
npm run e2e                                  # Playwright (needs API on :8080 and web on :3000)
```

## Documentation

See [`docs/`](docs) — architecture, database, auth, multi-client design, every module and integration, deployment
and testing — and [`PROJECT_PROGRESS.md`](PROJECT_PROGRESS.md) for status, required credentials and limitations.
API reference: `GET /api/v1/openapi.json`.

## Safety and policy constraints (by design)

- No outbound email or SMS is ever sent by the platform; it prepares, validates, approves and hands off drafts.
- Campaign-facing copy is human-authored and human-approved; AI is limited to administrative assistance.
- No voter profiling, sensitive-trait targeting or political persuasion generation.
- Advertising activation and spend happen only in the ad platforms, by people.
- Compliance features support review; they are not legal advice.
