"""SMS campaign operations with consent, opt-out and approval gates. The platform never sends messages."""
from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from quart import Blueprint, request
from sqlalchemy import func, select

from app.blueprints.common import load_scoped
from app.core.audit import audit
from app.core.auth import authenticated, ctx, get_client_checked
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import Unauthorized, ValidationFailed
from app.core.http import body, ok
from app.models import ComplianceEvent, Contact, SmsCampaign
from app.services import events
from app.services.contacts import normalize_phone
from app.services.integrations import registry
from app.services.suppression import add_suppression, suppressed_values

bp = Blueprint("sms", __name__)

STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "revoke", "optout", "opt out", "opt-out"}
OPT_OUT_LANGUAGE = re.compile(r"\b(reply|text)\s+stop\b", re.I)


def compliance_review(c: SmsCampaign) -> dict:
    checks = []

    def add(name, passed, detail=""):
        checks.append({"check": name, "passed": passed, "detail": detail})

    add("opt_out_instructions", bool(OPT_OUT_LANGUAGE.search(c.message_body)), "Message must include 'Reply STOP to opt out'")
    add("sender_identified", bool(c.sender_id) and c.sender_id.lower() in c.message_body.lower(),
        "Message must identify the sender (sender_id) in body")
    add("length", len(c.message_body) <= 640, f"{len(c.message_body)} chars (<=640)")
    add("human_author", bool(c.message_author.strip()), "Human author recorded")
    add("contact_list", bool(c.contact_list_id), "Contact list associated")
    add("eligible_recipients", c.eligible_recipients > 0, f"{c.eligible_recipients} consented, non-suppressed recipients")
    add("sending_limit", 0 < c.daily_send_limit <= 50_000, f"daily limit {c.daily_send_limit}")
    return {"passed": all(x["passed"] for x in checks), "checks": checks, "reviewed_at": datetime.now(UTC).isoformat()}


class SmsIn(BaseModel):
    name: str = Field(min_length=2)
    message_body: str = Field(min_length=1, max_length=1600)
    message_author: str = Field(min_length=2, description="Human who wrote the message")
    sender_id: str = Field(min_length=2, max_length=40)
    contact_list_id: str | None = None
    campaign_id: str | None = None
    daily_send_limit: int = Field(default=1000, ge=1, le=50_000)


async def _eligible(s, org_id: str, client_id: str, list_id: str | None) -> int:
    if not list_id:
        return 0
    sup = await suppressed_values(s, org_id, client_id, "sms")
    phones = (await s.execute(select(Contact.phone).where(
        Contact.list_id == list_id, Contact.client_id == client_id, Contact.sms_consent.is_(True),
        Contact.phone.is_not(None)))).scalars().all()
    return len({p for p in phones if p not in sup})


@bp.get("/clients/<client_id>/sms-campaigns")
@authenticated
async def list_sms(client_id: str):
    await get_client_checked(client_id, "sms:read")
    async with session_scope() as s:
        return ok([r.to_dict() for r in (await s.execute(select(SmsCampaign).where(
            SmsCampaign.client_id == client_id).order_by(SmsCampaign.created_at.desc()))).scalars()])


@bp.post("/clients/<client_id>/sms-campaigns")
@authenticated
async def create_sms(client_id: str):
    c = await get_client_checked(client_id, "sms:write")
    data = await body(SmsIn)
    async with session_scope() as s:
        if data.contact_list_id:
            from app.models import ContactList

            cl = await s.get(ContactList, data.contact_list_id)
            if cl is None or cl.client_id != client_id:
                raise ValidationFailed("contact_list_id does not belong to this client")
        camp = SmsCampaign(organization_id=c.organization_id, client_id=client_id, **data.model_dump())
        camp.eligible_recipients = await _eligible(s, c.organization_id, client_id, data.contact_list_id)
        camp.compliance = compliance_review(camp)
        s.add(camp)
        await s.flush()
        audit(s, action="sms.create", target_type="sms_campaign", target_id=camp.id, organization_id=c.organization_id,
              client_id=client_id, actor_user_id=ctx().user.id)
    return ok(camp.to_dict(), 201)


@bp.get("/sms-campaigns/<sms_id>")
@authenticated
async def get_sms(sms_id: str):
    return ok((await load_scoped(SmsCampaign, sms_id, "sms:read")).to_dict())


@bp.post("/sms-campaigns/<sms_id>/submit")
@authenticated
async def submit(sms_id: str):
    c = await load_scoped(SmsCampaign, sms_id, "sms:write")
    if c.status not in ("draft", "rejected"):
        raise ValidationFailed(f"Cannot submit from status {c.status}")
    async with session_scope() as s:
        x = await s.get(SmsCampaign, sms_id)
        x.eligible_recipients = await _eligible(s, x.organization_id, x.client_id, x.contact_list_id)
        x.compliance = compliance_review(x)
        if not x.compliance["passed"]:
            return ok(x.to_dict(), 422)
        x.status = "pending_approval"
    await events.emit("approval.requested", organization_id=c.organization_id, client_id=c.client_id,
                      data={"sms_campaign_id": sms_id}, summary=f"SMS campaign '{c.name}' awaiting approval")
    return ok(x.to_dict())


class DecisionIn(BaseModel):
    approve: bool
    note: str = ""


@bp.post("/sms-campaigns/<sms_id>/decision")
@authenticated
async def decide(sms_id: str):
    c = await load_scoped(SmsCampaign, sms_id, "sms:approve")
    if c.status != "pending_approval":
        raise ValidationFailed("Campaign is not awaiting approval")
    data = await body(DecisionIn)
    async with session_scope() as s:
        x = await s.get(SmsCampaign, sms_id)
        x.status = "approved" if data.approve else "rejected"
        if data.approve:
            x.approved_by, x.approved_at = ctx().user.id, datetime.now(UTC)
        audit(s, action=f"sms.{x.status}", target_type="sms_campaign", target_id=sms_id, organization_id=x.organization_id,
              client_id=x.client_id, actor_user_id=ctx().user.id, details={"note": data.note})
    return ok(x.to_dict())


@bp.post("/sms-campaigns/<sms_id>/provision")
@authenticated
async def provision(sms_id: str):
    """Creates the campaign at the provider in a not-yet-launched state. Launch happens in the provider UI."""
    c = await load_scoped(SmsCampaign, sms_id, "sms:write")
    if c.status != "approved" or not c.approved_by:
        raise ValidationFailed("Campaign must be approved before provisioning")
    if c.provider_reference:
        return ok(c.to_dict())
    async with session_scope() as s:
        eligible = await _eligible(s, c.organization_id, c.client_id, c.contact_list_id)
    prov = registry.get("scale_to_win")
    res = await prov.provision_campaign(name=c.name, body=c.message_body, sender_id=c.sender_id,
                                        recipients=min(eligible, c.daily_send_limit))
    async with session_scope() as s:
        x = await s.get(SmsCampaign, sms_id)
        x.status, x.provider_reference, x.provider_status = "provisioned", res["reference"], res["status"]
        x.eligible_recipients = eligible
        audit(s, action="sms.provisioned", target_type="sms_campaign", target_id=sms_id, organization_id=x.organization_id,
              client_id=x.client_id, actor_user_id=ctx().user.id, details={"mode": prov.mode, "ref": res["reference"]})
    await events.emit("sms_campaign.provisioned", organization_id=c.organization_id, client_id=c.client_id,
                      data={"sms_campaign_id": sms_id}, summary=f"SMS campaign '{c.name}' provisioned (not launched)")
    return ok(x.to_dict())


@bp.post("/sms-campaigns/<sms_id>/refresh-status")
@authenticated
async def refresh(sms_id: str):
    c = await load_scoped(SmsCampaign, sms_id, "sms:read")
    if not c.provider_reference:
        raise ValidationFailed("Not provisioned")
    st = await registry.get("scale_to_win").campaign_status(c.provider_reference)
    async with session_scope() as s:
        x = await s.get(SmsCampaign, sms_id)
        x.provider_status = st.get("status")
        x.delivery_stats = {k: st.get(k, 0) for k in ("delivered", "failed", "opt_outs")}
    return ok(x.to_dict())


@bp.post("/webhooks/sms/inbound/<org_id>/<client_id>")
async def inbound_sms(org_id: str, client_id: str):
    """Provider inbound-message webhook. STOP keywords suppress immediately — no human or AI gate."""
    settings = get_settings()
    from app.services.events import verify

    raw = await request.get_data(as_text=False)
    if not settings.webhook_signing_secret or not verify(settings.webhook_signing_secret, raw,
                                                         request.headers.get("X-Spark-Signature", "")):
        raise Unauthorized("Invalid signature")
    payload = await request.get_json(force=True)
    phone = normalize_phone(str(payload.get("from", "")))
    text = str(payload.get("body", "")).strip().lower()
    if not phone:
        raise ValidationFailed("invalid from number")
    is_stop = text in STOP_WORDS or text.split(" ")[0] in STOP_WORDS
    async with session_scope() as s:
        from app.models import Client

        cl = await s.get(Client, client_id)
        if cl is None or cl.organization_id != org_id:
            raise ValidationFailed("unknown client")
        if is_stop:
            await add_suppression(s, org_id=org_id, client_id=client_id, channel="sms", value=phone,
                                  reason="stop_keyword", source="sms_inbound")
            s.add(ComplianceEvent(organization_id=org_id, client_id=client_id, kind="sms_stop", channel="sms",
                                  subject_value=phone, raw_text=text[:500], status="suppressed",
                                  classification={"intent": "unsubscribe", "explicit": True}))
        count = (await s.execute(select(func.count()).select_from(ComplianceEvent))).scalar_one()
    return ok({"suppressed": is_stop, "events": count})
