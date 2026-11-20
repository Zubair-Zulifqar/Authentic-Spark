# Automation (Zapier-compatible)

```mermaid
flowchart LR
  E[Domain event<br/>emit()] --> S{Subscriptions<br/>for event type}
  S --> X[(automation_executions<br/>unique sub+event)]
  X --> J[[deliver_webhook job]]
  J -->|POST signed| T[Target URL]
  J -->|fail| R[retry w/ backoff ≤3]
  R -->|exhausted| F[failed + visible in Settings]
  IN[Inbound webhook<br/>signed + Idempotency-Key] --> A[suppression.add / compliance.flag]
```

Events: client.created, campaign.created, email_calendar.updated, production.completed, contact_list.uploaded,
list_validation.completed, sms_campaign.provisioned, invoice.approved, payment.received, compliance.issue_detected,
workflow.failed, approval.requested.

Signature: `X-Spark-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>`, 5-minute tolerance.
Subscribe/unsubscribe endpoints follow Zapier's REST-hook pattern; the per-subscription secret is returned once.
Core workflows never depend on Zapier — it only consumes events or calls the inbound endpoint.
