"""Deliverability (SPF/DKIM/DMARC), suppression lists, unsubscribe processing, bounces/complaints."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from quart import Blueprint, request
from sqlalchemy import func, select

from app.blueprints.common import load_scoped
from app.core.audit import audit
from app.core.auth import authenticated, ctx, get_client_checked
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import Unauthorized, ValidationFailed
from app.core.http import body, ok, page_args
from app.models import ComplianceEvent, SendingDomain, Suppression
from app.services import events
from app.services.ai.agents import run_agent
from app.services.dns_checks import check_domain
from app.services.suppression import add_suppression

bp = Blueprint("compliance", __name__)


class DomainIn(BaseModel):
    domain: str = Field(max_length=253, pattern=r"^([a-z0-9-]{1,63}\.)+[a-z]{2,}$")
    dkim_selectors: list[str] = []


@bp.get("/clients/<client_id>/domains")
@authenticated
async def list_domains(client_id: str):
    await get_client_checked(client_id, "compliance:read")
    async with session_scope() as s:
        return ok([d.to_dict() for d in (await s.execute(select(SendingDomain).where(SendingDomain.client_id == client_id))).scalars()])


@bp.post("/clients/<client_id>/domains")
@authenticated
async def add_domain(client_id: str):
    c = await get_client_checked(client_id, "compliance:write")
    data = await body(DomainIn)
    async with session_scope() as s:
        d = SendingDomain(organization_id=c.organization_id, client_id=client_id, domain=data.domain.lower(),
                          dkim_selectors=data.dkim_selectors)
        s.add(d)
    return ok(d.to_dict(), 201)


@bp.post("/domains/<domain_id>/check")
@authenticated
async def run_check(domain_id: str):
    d = await load_scoped(SendingDomain, domain_id, "compliance:read")
    try:
        result = await check_domain(d.domain, d.dkim_selectors)
    except Exception as exc:
        raise ValidationFailed(f"DNS lookup failed: {exc}") from exc
    async with session_scope() as s:
        x = await s.get(SendingDomain, domain_id)
        x.last_check, x.last_checked_at = result, datetime.now(UTC)
    return ok(x.to_dict())


class SuppressionIn(BaseModel):
    channel: Literal["email", "sms"]
    value: str = Field(min_length=3, max_length=320)
    reason: Literal["unsubscribe", "stop_keyword", "bounce", "complaint", "manual"] = "manual"
    scope: Literal["client", "global"] = "client"


@bp.get("/clients/<client_id>/suppressions")
@authenticated
async def list_suppressions(client_id: str):
    c = await get_client_checked(client_id, "compliance:read")
    limit, offset = page_args()
    async with session_scope() as s:
        q = select(Suppression).where(Suppression.organization_id == c.organization_id,
                                      (Suppression.client_id == client_id) | (Suppression.client_id.is_(None)))
        if request.args.get("q"):
            q = q.where(Suppression.value.contains(request.args["q"].lower()))
        rows = (await s.execute(q.order_by(Suppression.created_at.desc()).limit(limit).offset(offset))).scalars()
        return ok([r.to_dict() for r in rows])


@bp.post("/clients/<client_id>/suppressions")
@authenticated
async def add_supp(client_id: str):
    c = await get_client_checked(client_id, "compliance:write")
    data = await body(SuppressionIn)
    if data.scope == "global":
        ctx().require("compliance:approve", c.organization_id)
    async with session_scope() as s:
        created = await add_suppression(s, org_id=c.organization_id, client_id=None if data.scope == "global" else client_id,
                                        channel=data.channel, value=data.value, reason=data.reason, source="staff")
        audit(s, action="suppression.add", target_type="suppression", target_id=None, organization_id=c.organization_id,
              client_id=client_id, actor_user_id=ctx().user.id, details={"channel": data.channel, "scope": data.scope})
    return ok({"created": created}, 201 if created else 200)


@bp.get("/clients/<client_id>/suppressions/check")
@authenticated
async def check_supp(client_id: str):
    c = await get_client_checked(client_id, "compliance:read")
    value, channel = request.args.get("value", "").strip().lower(), request.args.get("channel", "email")
    async with session_scope() as s:
        hit = (await s.execute(select(Suppression).where(
            Suppression.organization_id == c.organization_id, Suppression.channel == channel, Suppression.value == value,
            (Suppression.client_id == client_id) | (Suppression.client_id.is_(None))))).scalars().first()
    return ok({"suppressed": hit is not None, "record": hit.to_dict() if hit else None})


# ------------------------------------------------------------------ unsubscribe processing
class InboundReplyIn(BaseModel):
    from_address: str = Field(min_length=3)
    text: str = Field(min_length=1, max_length=10_000)
    channel: Literal["email", "sms"] = "email"


async def process_reply(org_id: str, client_id: str, data: InboundReplyIn, user_id: str) -> dict:
    ex = await run_agent("unsubscribe_classifier", {"text": data.text}, organization_id=org_id, client_id=client_id,
                         user_id=user_id)
    cls = ex.output or {"intent": "unclear", "explicit": False, "rationale": "classifier failed"}
    value = data.from_address.strip().lower()
    async with session_scope() as s:
        if cls.get("intent") == "unsubscribe" and (cls.get("explicit") or cls.get("confidence", 0) >= 0.9):
            # Clear opt-out: suppress immediately, no human delay.
            await add_suppression(s, org_id=org_id, client_id=client_id, channel=data.channel, value=value,
                                  reason="unsubscribe", source="inbound_reply")
            status = "suppressed"
        elif cls.get("intent") in ("unsubscribe", "unclear") or ex.status == "failed":
            status = "needs_review"
        else:
            status = "dismissed"
        ev = ComplianceEvent(organization_id=org_id, client_id=client_id, kind="unsubscribe_request",
                             channel=data.channel, subject_value=value, raw_text=data.text[:2000],
                             classification=cls | {"execution_id": ex.id}, status=status)
        s.add(ev)
        await s.flush()
        audit(s, action=f"unsubscribe.{status}", target_type="compliance_event", target_id=ev.id, organization_id=org_id,
              client_id=client_id, actor_user_id=user_id)
    if status == "needs_review":
        await events.emit("compliance.issue_detected", organization_id=org_id, client_id=client_id,
                          data={"event_id": ev.id}, summary="Possible opt-out reply needs review")
    return ev.to_dict()


@bp.post("/clients/<client_id>/inbound-replies")
@authenticated
async def inbound_reply(client_id: str):
    c = await get_client_checked(client_id, "compliance:write")
    data = await body(InboundReplyIn)
    return ok(await process_reply(c.organization_id, client_id, data, ctx().user.id), 201)


@bp.post("/webhooks/replies/<org_id>/<client_id>")
async def inbound_reply_webhook(org_id: str, client_id: str):
    """Signed webhook for mail providers / Zapier to forward replies and bounce/complaint events."""
    secret = get_settings().webhook_signing_secret
    raw = await request.get_data(as_text=False)
    if not secret or not events.verify(secret, raw, request.headers.get("X-Spark-Signature", "")):
        raise Unauthorized("Invalid signature")
    payload = await request.get_json(force=True)
    from app.models import Client

    async with session_scope() as s:
        cl = await s.get(Client, client_id)
        if cl is None or cl.organization_id != org_id:
            raise ValidationFailed("unknown client")
    kind = payload.get("type", "reply")
    if kind in ("bounce", "complaint"):
        reason = "bounce" if kind == "bounce" else "complaint"
        if kind == "bounce" and payload.get("bounce_type", "hard") != "hard":
            return ok({"ignored": "soft bounce"})
        async with session_scope() as s:
            await add_suppression(s, org_id=org_id, client_id=client_id, channel="email",
                                  value=str(payload["email"]), reason=reason, source="provider_webhook")
            s.add(ComplianceEvent(organization_id=org_id, client_id=client_id, kind=kind, subject_value=str(payload["email"]).lower(),
                                  status="suppressed"))
        return ok({"suppressed": True})
    data = InboundReplyIn(from_address=payload.get("from", ""), text=payload.get("text", ""))
    return ok(await process_reply(org_id, client_id, data, "system"), 201)


@bp.get("/clients/<client_id>/compliance-events")
@authenticated
async def list_events(client_id: str):
    await get_client_checked(client_id, "compliance:read")
    limit, offset = page_args()
    async with session_scope() as s:
        q = select(ComplianceEvent).where(ComplianceEvent.client_id == client_id)
        if request.args.get("status"):
            q = q.where(ComplianceEvent.status == request.args["status"])
        rows = (await s.execute(q.order_by(ComplianceEvent.created_at.desc()).limit(limit).offset(offset))).scalars()
        return ok([r.to_dict() for r in rows])


class ReviewIn(BaseModel):
    decision: Literal["suppress", "dismiss"]


@bp.post("/compliance-events/<event_id>/review")
@authenticated
async def review(event_id: str):
    ev = await load_scoped(ComplianceEvent, event_id, "compliance:approve")
    if ev.status != "needs_review":
        raise ValidationFailed("Event does not need review")
    data = await body(ReviewIn)
    async with session_scope() as s:
        x = await s.get(ComplianceEvent, event_id)
        if data.decision == "suppress":
            await add_suppression(s, org_id=x.organization_id, client_id=x.client_id, channel=x.channel,
                                  value=x.subject_value, reason="unsubscribe", source="human_review")
            x.status = "suppressed"
        else:
            x.status = "dismissed"
        x.resolved_by = ctx().user.id
        audit(s, action=f"compliance_event.{x.status}", target_type="compliance_event", target_id=event_id,
              organization_id=x.organization_id, client_id=x.client_id, actor_user_id=ctx().user.id)
    return ok(x.to_dict())


@bp.get("/clients/<client_id>/deliverability")
@authenticated
async def deliverability(client_id: str):
    await get_client_checked(client_id, "compliance:read")
    async with session_scope() as s:
        kinds = dict((await s.execute(select(ComplianceEvent.kind, func.count()).where(
            ComplianceEvent.client_id == client_id).group_by(ComplianceEvent.kind))).all())
        sup = dict((await s.execute(select(Suppression.reason, func.count()).where(
            Suppression.client_id == client_id).group_by(Suppression.reason))).all())
        domains = [d.to_dict() for d in (await s.execute(select(SendingDomain).where(SendingDomain.client_id == client_id))).scalars()]
    return ok({"events": kinds, "suppressions": sup, "domains": domains})
