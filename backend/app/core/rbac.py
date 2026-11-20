"""Role-based access control with agency-, client- and module-level scoping.

A permission is "<module>:<action>" where action in {read, write, approve}.
A Membership with client_id NULL applies to every client in the organization;
one with a client_id applies only to that client. `modules` optionally narrows a role.
"""
from __future__ import annotations

MODULES = (
    "clients", "campaigns", "email", "contacts", "sms", "ads",
    "billing", "compliance", "ai", "integrations", "analytics", "admin",
)

R, W, A = "read", "write", "approve"


def _p(modules: tuple[str, ...] | list[str], *actions: str) -> set[str]:
    return {f"{m}:{a}" for m in modules for a in actions}


ALL = list(MODULES)

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "agency_admin": _p(ALL, R, W, A),
    "operations_manager": _p([m for m in ALL if m != "admin"], R, W, A) - {"billing:approve"},
    "account_manager": _p(["clients", "campaigns", "email", "contacts", "sms", "ads", "analytics", "ai"], R, W)
    | _p(["clients", "campaigns"], A) | _p(["billing", "compliance", "integrations"], R),
    "email_specialist": _p(["email", "ai"], R, W) | _p(["email"], A) | _p(["clients", "campaigns", "contacts", "compliance"], R),
    "sms_specialist": _p(["sms", "contacts", "ai"], R, W) | _p(["clients", "campaigns", "compliance"], R),
    "advertising_specialist": _p(["ads", "ai"], R, W) | _p(["clients", "campaigns", "analytics"], R),
    "finance_user": _p(["billing"], R, W, A) | _p(["clients", "analytics"], R),
    "compliance_reviewer": _p(["compliance"], R, W, A) | _p(["sms", "ads", "email"], R, A)
    | _p(["clients", "campaigns", "contacts", "ai"], R),
    "read_only": _p(ALL, R) - {"admin:read"},
}
ROLES = tuple(ROLE_PERMISSIONS)


def role_allows(role: str, perm: str, modules: list[str] | None) -> bool:
    if perm not in ROLE_PERMISSIONS.get(role, set()):
        return False
    if modules is not None and perm.split(":")[0] not in modules:
        return False
    return True
