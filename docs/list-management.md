# Contact-list management (List Buys)

```mermaid
flowchart LR
  U[CSV upload] --> P[Preview + suggested mapping]
  P --> I[Import]
  I -->|invalid email/phone, missing both| X[Import issues]
  I -->|duplicate in file / in other lists| X
  I -->|on suppression list| S[status suppressed]
  I --> C[Contacts pending]
  C --> J[[Job: verify_contact_list]]
  J --> ZB[ZeroBounce batch ≤200]
  ZB --> V[valid / invalid / risky]
  V --> E[Export valid CSV]
  E --> N[NGP VAN bulkImportJobs]
  N --> J2[[Job: import status]]
```

- Required provenance: list name, **source vendor**, **usage permission** (`opt_in`, `vendor_attested_opt_in`,
  `transactional`) and **consent evidence** (except transactional). Transactional lists cannot go to CRM import.
- File checks: `.csv` only, ≤20MB, ≤200k rows, binary sniffing, UTF‑8/Latin‑1.
- Phone normalization to E.164 (US); SMS consent column is mapped explicitly.
- Verification never implies permission to send marketing.
- ZeroBounce usage: credits endpoint (integration test), API-call counts recorded on the list stats.
