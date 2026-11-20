# Authentication & authorization

## Authentication
- Web: Firebase JS SDK — email/password, Google sign-in, password reset, email verification, sign-out.
- API: `Authorization: Bearer <Firebase ID token>`, verified with `firebase_admin.auth.verify_id_token(check_revoked=True)`.
  Unverified emails are rejected. First login links to an invited (pre-provisioned) user by email.
- `AUTH_MODE=dev` accepts `dev:<email>` tokens for local development and tests only; refused when `APP_ENV=production`.

## Authorization (RBAC)
Permissions are `<module>:<read|write|approve>` across modules: clients, campaigns, email, contacts, sms, ads,
billing, compliance, ai, integrations, analytics, admin.

| Role | Summary |
|---|---|
| agency_admin | everything |
| operations_manager | all modules except admin; cannot approve billing |
| account_manager | client-facing modules read/write; approve clients/campaigns |
| email_specialist | email read/write/approve |
| sms_specialist | sms + contacts read/write (approval by others) |
| advertising_specialist | ads read/write |
| finance_user | billing read/write/approve |
| compliance_reviewer | compliance read/write/approve; approve sms/ads/email |
| read_only | read everything except admin |

A **membership** grants a role at agency scope (`client_id` NULL) or for one client, optionally narrowed to a module
list. Checks happen in every route (`ctx().require`, `get_client_checked`, `load_scoped`). Records outside the
caller's orgs/clients return **404** to avoid leaking existence.

## OAuth (Google, QuickBooks)
`GET /oauth/<provider>/start` stores a random single-use `state` bound to user/org/client; the callback rejects
missing, reused, mismatched or >10-minute-old states. Scopes are least-privilege (`documents`, `drive.file`,
`spreadsheets`, `adwords`, `com.intuit.quickbooks.accounting`). Tokens belong in Secret Manager (see limitations).
