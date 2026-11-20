from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import redact
from app.models import AuditLog


def audit(
    s: AsyncSession,
    *,
    action: str,
    target_type: str,
    target_id: str | None,
    organization_id: str | None,
    client_id: str | None = None,
    actor_user_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    s.add(
        AuditLog(
            organization_id=organization_id,
            client_id=client_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=redact(details or {}),
        )
    )
