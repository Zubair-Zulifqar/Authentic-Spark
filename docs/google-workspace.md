# Google Workspace

Adapter: `GoogleWorkspaceClient` (REST, OAuth bearer token).

| Feature | Endpoint | Scope |
|---|---|---|
| Retrieve doc | `GET docs.googleapis.com/v1/documents/{id}` | documents |
| Create doc | `POST /v1/documents` + `:batchUpdate insertText` | documents |
| List files / folder | `GET drive/v3/files?q='<folder>' in parents` | drive.file |
| Read/write sheet | `GET/PUT sheets/v4/spreadsheets/{id}/values/{range}` | spreadsheets |

`drive.file` limits Drive access to files the app created or the user explicitly opened — no broad Drive access.
Doc conversion understands headings, bullets, bold/italic and links. Until OAuth token storage is wired (see
PROJECT_PROGRESS), the mock adapter serves a seeded synthetic document `mock-doc-spring-update`.
