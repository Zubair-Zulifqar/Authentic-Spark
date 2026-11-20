# Email production pipeline

```mermaid
sequenceDiagram
  participant S as Staff
  participant API
  participant GD as Google Docs
  participant CRM as Action Network / ActionKit
  S->>API: POST /clients/{id}/productions (doc id or pasted copy)
  API->>GD: documents.get (authorized)
  API->>API: blocks → template HTML → 14 validation checks
  API-->>S: status validated | draft (issues)
  S->>API: GET /productions/{id}/preview (sandboxed, CSP)
  S->>API: POST /approve (email:approve)
  S->>API: POST /prepare-test (seed list recorded, not sent)
  S->>API: POST /handoff {platform}
  API->>CRM: create draft (never send)
  API-->>S: handed_off + reference; event production.completed
```

Validation checks: HTML structure, https links (merge tags allowed), descriptive link text, image alt text, https
images, unsubscribe link, mailing-address merge tag, sender address, subject present/length, viewport meta, max
width ≤ 640px, size < 102KB (Gmail clipping).

Approved productions are immutable; history records each transition. NGP VAN/EveryAction content creation is a
**manual export** handoff (no API used for that operation).
