# Email calendar

Workflow: select client → create calendar (dates, objectives) → **Plan with AI** (sends/week, staff-approved themes,
blackout dates) → review proposal → approve (creates scheduled emails with owner and draft deadlines) → edit each
email (brief, human content author, source doc, review status) → export review doc to Google Docs → hand off to Asana.

- Views: month, week (grid) and list (searchable/filterable); day detail via the email editor.
- Approval of a scheduled email requires `email:approve` and a recorded human `content_author`.
- Asana handoff is idempotent (`external_mappings` key `scheduled_email:<id>`).
- Nothing is published or sent.

Endpoints: `GET/POST /clients/{id}/email-calendars`, `GET /email-calendars/{id}?from&to`, `POST .../plan`,
`POST .../emails`, `PATCH /scheduled-emails/{id}`, `POST .../export-doc`, `POST /scheduled-emails/{id}/asana-handoff`,
`POST /agent-executions/{id}/decision`.
