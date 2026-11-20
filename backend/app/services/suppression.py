from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Suppression


async def suppressed_values(s: AsyncSession, org_id: str, client_id: str, channel: str) -> set[str]:
    """Client-specific plus organization-wide (global) suppressions."""
    rows = await s.execute(select(Suppression.value).where(
        Suppression.organization_id == org_id, Suppression.channel == channel,
        or_(Suppression.client_id == client_id, Suppression.client_id.is_(None))))
    return set(rows.scalars())


async def add_suppression(s: AsyncSession, *, org_id: str, client_id: str | None, channel: str, value: str,
                          reason: str, source: str) -> bool:
    value = value.strip().lower()
    exists = (await s.execute(select(Suppression).where(
        Suppression.organization_id == org_id, Suppression.channel == channel, Suppression.value == value,
        Suppression.client_id.is_(None) if client_id is None else Suppression.client_id == client_id))).scalar_one_or_none()
    if exists:
        return False
    s.add(Suppression(organization_id=org_id, client_id=client_id, channel=channel, value=value, reason=reason, source=source))
    # Apply to existing contacts immediately.
    from sqlalchemy import update

    from app.models import Contact

    col = Contact.email_normalized if channel == "email" else Contact.phone
    stmt = update(Contact).where(Contact.organization_id == org_id, col == value)
    if client_id:
        stmt = stmt.where(Contact.client_id == client_id)
    vals = {"status": "suppressed"} if channel == "email" else {"sms_consent": False}
    await s.execute(stmt.values(**vals))
    return True
