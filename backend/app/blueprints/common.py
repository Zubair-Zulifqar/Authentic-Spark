from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import select

from app.core.auth import ctx, get_client_checked
from app.core.db import session_scope
from app.core.errors import Forbidden, NotFound
from app.models import Client

M = TypeVar("M")


async def load_scoped(model: type[M], obj_id: str, perm: str) -> M:
    """Load a tenant-scoped record and enforce the caller's permission on its client."""
    async with session_scope() as s:
        obj = await s.get(model, obj_id)
    if obj is None or getattr(obj, "organization_id", None) not in ctx().org_ids:
        raise NotFound(f"{model.__name__} not found")
    client_id = getattr(obj, "client_id", None)
    if not ctx().has(perm, obj.organization_id, client_id):
        if not ctx().has("clients:read", obj.organization_id, client_id):
            raise NotFound(f"{model.__name__} not found")
        raise Forbidden(f"Missing permission {perm}")
    return obj


async def client_ids_for(org_id: str, perm: str) -> list[str]:
    """Clients in org the caller may access with `perm` (enforces client isolation in list queries)."""
    if org_id not in ctx().org_ids:
        raise NotFound("Organization not found")
    allowed = ctx().visible_client_ids(org_id, perm)
    async with session_scope() as s:
        q = select(Client.id).where(Client.organization_id == org_id)
        if allowed is not None:
            q = q.where(Client.id.in_(allowed))
        return list((await s.execute(q)).scalars())


__all__ = ["load_scoped", "client_ids_for", "get_client_checked", "Any"]
