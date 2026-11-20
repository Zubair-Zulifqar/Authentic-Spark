# Asana integration

- Client mapping: `clients.settings.asana_project_gid`.
- Create task (`POST /tasks`) from an approved/planned scheduled email with name, notes (brief + source doc), due date
  (draft deadline). Idempotency via `external_mappings(provider='asana', key='scheduled_email:<id>')`.
- Update (`PUT /tasks/{gid}`) and comment (`POST /tasks/{gid}/stories`) helpers.
- Webhooks `POST /webhooks/asana`: echoes `X-Hook-Secret` on handshake, verifies `X-Hook-Signature`
  (HMAC-SHA256 hex), de-duplicates events, and moves linked scheduled emails to `in_review` when the task completes.
- Errors surface as `IntegrationError` (HTTP 502) with provider detail; 429/5xx retried with backoff.
