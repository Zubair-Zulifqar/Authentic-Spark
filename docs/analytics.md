# Analytics

- **Mixpanel** (`/track`, project token) receives operational events: login, client/campaign creation, workflow
  events, invoice creation, integration connection, approvals. Properties are IDs only (org, client) — no contact data,
  no political or inferred personal attributes.
- **In-app analytics** (`GET /organizations/{org}/analytics?client_id=`): workflow (job) success rate, job/agent/
  webhook outcomes, production/scheduled email/invoice/compliance status distributions, production throughput per
  client. Results are restricted to clients the caller can read (`analytics:read`).
