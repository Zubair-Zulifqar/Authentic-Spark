"""Authentication (Firebase ID tokens) and per-request authorization context."""
from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from quart import g, request
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import Forbidden, NotFound, Unauthorized
from app.core.rbac import role_allows
from app.models import Client, Membership, User

_firebase_app = None


def _verify_firebase(token: str) -> dict[str, Any]:
    global _firebase_app
    import firebase_admin
    from firebase_admin import auth as fb_auth

    if _firebase_app is None:
        opts = {"projectId": get_settings().firebase_project_id} if get_settings().firebase_project_id else None
        _firebase_app = firebase_admin.initialize_app(options=opts)
    try:
        return fb_auth.verify_id_token(token, check_revoked=True)
    except Exception as exc:  # invalid, expired, revoked
        raise Unauthorized("Invalid or expired token") from exc


def verify_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    if settings.auth_mode == "firebase":
        return _verify_firebase(token)
    if settings.is_production:
        raise Unauthorized("Dev auth disabled in production")
    # Development tokens: "dev:<email>". Never accepted when AUTH_MODE=firebase.
    if not token.startswith("dev:") or "@" not in token:
        raise Unauthorized("Invalid token")
    email = token[4:].strip().lower()
    return {"uid": f"dev-{email}", "email": email, "email_verified": True, "name": email.split("@")[0]}


@dataclass
class AuthContext:
    user: User
    memberships: list[Membership] = field(default_factory=list)

    @property
    def org_ids(self) -> set[str]:
        return {m.organization_id for m in self.memberships}

    def has(self, perm: str, org_id: str, client_id: str | None = None) -> bool:
        for m in self.memberships:
            if m.organization_id != org_id:
                continue
            if m.client_id is not None and m.client_id != client_id:
                continue
            if role_allows(m.role, perm, m.modules):
                return True
        return False

    def visible_client_ids(self, org_id: str, perm: str) -> set[str] | None:
        """None => all clients in org (agency-wide grant)."""
        ids: set[str] = set()
        for m in self.memberships:
            if m.organization_id != org_id or not role_allows(m.role, perm, m.modules):
                continue
            if m.client_id is None:
                return None
            ids.add(m.client_id)
        return ids

    def require(self, perm: str, org_id: str, client_id: str | None = None) -> None:
        if not self.has(perm, org_id, client_id):
            raise Forbidden(f"Missing permission {perm}")


async def load_context() -> AuthContext:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise Unauthorized("Missing bearer token")
    claims = verify_token(header[7:])
    if get_settings().auth_mode == "firebase" and not claims.get("email_verified"):
        raise Unauthorized("Email address not verified")
    async with session_scope() as s:
        user = (await s.execute(select(User).where(User.firebase_uid == claims["uid"]))).scalar_one_or_none()
        if user is None:
            # First login: link by email to a pre-provisioned (invited) user if present.
            user = (await s.execute(select(User).where(User.email == claims.get("email", "")))).scalar_one_or_none()
            if user is None:
                user = User(firebase_uid=claims["uid"], email=claims.get("email", ""), display_name=claims.get("name", ""))
                s.add(user)
            else:
                user.firebase_uid = claims["uid"]
            await s.flush()
        if not user.is_active:
            raise Forbidden("User disabled")
        memberships = list((await s.execute(select(Membership).where(Membership.user_id == user.id))).scalars())
    return AuthContext(user=user, memberships=memberships)


def authenticated(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        g.ctx = await load_context()
        return await fn(*args, **kwargs)

    return wrapper


def ctx() -> AuthContext:
    return g.ctx


async def get_client_checked(client_id: str, perm: str) -> Client:
    """Load a client and enforce permission. Returns 404 (not 403) for clients outside the user's orgs
    so existence of other tenants is not leaked."""
    async with session_scope() as s:
        client = await s.get(Client, client_id)
    if client is None or client.organization_id not in ctx().org_ids:
        raise NotFound("Client not found")
    if not ctx().has(perm, client.organization_id, client.id):
        if not ctx().has(perm.split(":")[0] + ":read", client.organization_id, client.id) and not ctx().has(
            "clients:read", client.organization_id, client.id
        ):
            raise NotFound("Client not found")
        raise Forbidden(f"Missing permission {perm}")
    return client
