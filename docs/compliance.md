# Compliance & deliverability

```mermaid
flowchart TD
  R[Inbound reply / event<br/>webhook or staff log] --> K{Rule check:<br/>explicit opt-out?}
  K -->|yes| SUP[Suppress immediately<br/>client scope]
  K -->|no| AI[AI classifier]
  AI -->|unsubscribe ≥0.9| SUP
  AI -->|unclear / failure| REV[needs_review]
  AI -->|other| DIS[dismissed]
  REV -->|compliance:approve| SUP
  REV --> DIS
  SUP --> CRM[Contacts marked suppressed /<br/>sms consent removed]
  SUP --> AUD[(audit log + compliance event)]
  B[Hard bounce / complaint webhook] --> SUP
```

- **Explicit opt-outs are never overridden by AI** (enforced in `run_agent` and tested with a provider that lies).
- AI failure never delays a clear opt-out (rules run first) and routes unclear cases to people.
- Suppression lists: client scope and organization-wide global scope (global requires `compliance:approve`);
  enforced at list import, SMS eligibility and on add (existing contacts updated).
- DNS: SPF (single record, permissive `all` warning), DMARC policy (`none` warns), DKIM at configured selectors;
  daily scheduled check opens a compliance event and alert on failure.
- These tools support review and are not legal advice.
