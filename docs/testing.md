# Testing

| Suite | Tool | Count | Command |
|---|---|---|---|
| API + services | pytest (async) | 52 | `cd backend && .venv/bin/pytest -q` |
| Frontend units | Vitest + Testing Library | 8 | `cd frontend && npm test` |
| End-to-end | Playwright | 1 smoke | `npm run e2e` (API :8080 seeded, web :3000) |
| Static | ruff, mypy, ESLint, tsc | — | see CI |

Coverage map:
- **Auth**: missing/invalid tokens, Firebase mode rejects dev tokens, login provisioning, `/me` permissions.
- **Clients**: creation, isolation (404 across clients/orgs), client-scoped users cannot create clients, module
  restrictions, read-only cannot write, campaign association/validation, dashboard, audit.
- **Email**: HTML conversion, validation failures, calendar plan → approve → scheduled emails, human-author gate,
  Asana idempotency, Docs export, production approve/immutability/test/handoff, failing validation stays draft.
- **Contacts**: preview mapping, import stats, suppression matching, verification job + idempotency, export, CRM
  import, cross-list duplicates, import failures (type, binary, consent, vendor, mapping).
- **SMS**: consent counting, approval gate, STOP webhook suppression, compliance blocking, bad signatures,
  cross-client list rejection.
- **Invoicing**: totals/tax/terms, approval permissions, issue to QBO, PDF output, webhook signature, duplicate
  webhook deliveries, payment sync, provider idempotency.
- **Compliance**: DNS evaluation, classifier cases, explicit opt-out cannot be overridden by AI, human review flow,
  global suppression, bounce webhook, domain validation.
- **Integrations**: retries/backoff, 429 Retry-After, non-retryable errors, ZeroBounce batching, signatures,
  inbound idempotency, outbound delivery with retry and signature verification, job idempotency/failure, scheduler
  token, Asana handshake/signature, OAuth state (forged/single-use), secret-free integration config, Slack routing,
  rate limiter, ads checks/versioning/approval, AI hub runs and provider-failure recording.

All third-party HTTP is exercised with `httpx.MockTransport` or the explicit mock adapters; no real credentials or
personal data are used.
