# Slack integration

- Bot token (`chat:write`) in Secret Manager → `SLACK_BOT_TOKEN`.
- Per-client routing in `clients.settings.slack_channels`: `approvals`, `alerts`, `campaigns`, `finance`.
- Events notified: `approval.requested`, `workflow.failed`, `compliance.issue_detected`, `sms_campaign.provisioned`,
  `production.completed`, `invoice.approved`, `payment.received`. Others are not sent (no noise).
- Messages are short summaries prefixed with the client name and **never include contact data**.
- Delivery runs as an idempotent `slack_notify` job (retries on failure). Without a token, `MockSlack` records messages.
