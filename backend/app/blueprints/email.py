"""Email calendar planning and the email production pipeline."""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field
from quart import Blueprint, request
from sqlalchemy import select

from app.blueprints.common import load_scoped
from app.core.audit import audit
from app.core.auth import authenticated, ctx, get_client_checked
from app.core.db import session_scope
from app.core.errors import Conflict, ValidationFailed
from app.core.http import body, ok
from app.models import AgentExecution, EmailCalendar, ExternalMapping, ProductionRecord, ScheduledEmail
from app.services import events
from app.services.ai.agents import run_agent
from app.services.email_production import blocks_from_google_doc, blocks_from_text, render_html, validate_html
from app.services.integrations import registry

bp = Blueprint("email", __name__)


class CalendarIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    campaign_id: str | None = None
    objectives: str = ""
    start_date: date
    end_date: date


@bp.get("/clients/<client_id>/email-calendars")
@authenticated
async def list_calendars(client_id: str):
    await get_client_checked(client_id, "email:read")
    async with session_scope() as s:
        rows = (await s.execute(select(EmailCalendar).where(EmailCalendar.client_id == client_id)
                                .order_by(EmailCalendar.start_date.desc()))).scalars()
        return ok([r.to_dict() for r in rows])


@bp.post("/clients/<client_id>/email-calendars")
@authenticated
async def create_calendar(client_id: str):
    c = await get_client_checked(client_id, "email:write")
    data = await body(CalendarIn)
    if data.end_date < data.start_date:
        raise ValidationFailed("end_date before start_date")
    async with session_scope() as s:
        cal = EmailCalendar(organization_id=c.organization_id, client_id=client_id, **data.model_dump())
        s.add(cal)
        await s.flush()
        audit(s, action="email_calendar.create", target_type="email_calendar", target_id=cal.id,
              organization_id=c.organization_id, client_id=client_id, actor_user_id=ctx().user.id)
    return ok(cal.to_dict(), 201)


@bp.get("/email-calendars/<cal_id>")
@authenticated
async def get_calendar(cal_id: str):
    cal = await load_scoped(EmailCalendar, cal_id, "email:read")
    start = request.args.get("from")
    end = request.args.get("to")
    async with session_scope() as s:
        q = select(ScheduledEmail).where(ScheduledEmail.calendar_id == cal_id)
        if start:
            q = q.where(ScheduledEmail.send_date >= date.fromisoformat(start))
        if end:
            q = q.where(ScheduledEmail.send_date <= date.fromisoformat(end))
        emails = (await s.execute(q.order_by(ScheduledEmail.send_date))).scalars().all()
    return ok({**cal.to_dict(), "emails": [e.to_dict() for e in emails]})


class PlanIn(BaseModel):
    sends_per_week: int = Field(ge=1, le=7)
    themes: list[str] = Field(min_length=1)
    blackout_dates: list[date] = []
    draft_lead_days: int = 5


@bp.post("/email-calendars/<cal_id>/plan")
@authenticated
async def plan_calendar(cal_id: str):
    """Runs the planner agent; output awaits human approval before slots are created."""
    cal = await load_scoped(EmailCalendar, cal_id, "email:write")
    data = await body(PlanIn)
    ex = await run_agent("email_calendar_planner", {**data.model_dump(mode="json"),
                         "start_date": cal.start_date.isoformat(), "end_date": cal.end_date.isoformat()},
                         organization_id=cal.organization_id, client_id=cal.client_id, user_id=ctx().user.id)
    async with session_scope() as s:
        e = await s.get(AgentExecution, ex.id)
        e.input = {**e.input, "calendar_id": cal_id}
    return ok(ex.to_dict() | {"input": {**ex.input, "calendar_id": cal_id}}, 201)


class ScheduledIn(BaseModel):
    send_date: date
    theme: str = Field(min_length=1)
    brief: str = ""
    owner_user_id: str | None = None
    reviewer_user_id: str | None = None
    draft_deadline: date | None = None


class ScheduledPatch(BaseModel):
    send_date: date | None = None
    theme: str | None = None
    brief: str | None = None
    owner_user_id: str | None = None
    reviewer_user_id: str | None = None
    status: Literal["planned", "drafting", "in_review", "approved", "produced"] | None = None
    source_doc_id: str | None = None
    content_author: str | None = None


@bp.post("/email-calendars/<cal_id>/emails")
@authenticated
async def add_email(cal_id: str):
    cal = await load_scoped(EmailCalendar, cal_id, "email:write")
    data = await body(ScheduledIn)
    async with session_scope() as s:
        e = ScheduledEmail(organization_id=cal.organization_id, client_id=cal.client_id, calendar_id=cal_id,
                           owner_user_id=data.owner_user_id or ctx().user.id, **data.model_dump(exclude={"owner_user_id"}))
        s.add(e)
    await events.emit("email_calendar.updated", organization_id=cal.organization_id, client_id=cal.client_id,
                      data={"calendar_id": cal_id, "email_id": e.id})
    return ok(e.to_dict(), 201)


@bp.patch("/scheduled-emails/<email_id>")
@authenticated
async def patch_email(email_id: str):
    e = await load_scoped(ScheduledEmail, email_id, "email:write")
    data = await body(ScheduledPatch)
    if data.status == "approved" and not ctx().has("email:approve", e.organization_id, e.client_id):
        raise ValidationFailed("email:approve permission required to approve")
    if data.status in ("approved", "produced") and not (data.content_author or e.content_author):
        raise ValidationFailed("A human content_author must be recorded before approval")
    async with session_scope() as s:
        e = await s.get(ScheduledEmail, email_id)
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(e, k, v)
        audit(s, action="scheduled_email.update", target_type="scheduled_email", target_id=e.id,
              organization_id=e.organization_id, client_id=e.client_id, actor_user_id=ctx().user.id,
              details=data.model_dump(exclude_none=True, mode="json"))
    await events.emit("email_calendar.updated", organization_id=e.organization_id, client_id=e.client_id,
                      data={"email_id": e.id, "status": e.status})
    return ok(e.to_dict())


@bp.post("/email-calendars/<cal_id>/export-doc")
@authenticated
async def export_calendar_doc(cal_id: str):
    cal = await load_scoped(EmailCalendar, cal_id, "email:write")
    async with session_scope() as s:
        emails = (await s.execute(select(ScheduledEmail).where(ScheduledEmail.calendar_id == cal_id)
                                  .order_by(ScheduledEmail.send_date))).scalars().all()
    lines = [f"{cal.name} — review document", f"Objectives: {cal.objectives}", ""]
    for e in emails:
        lines.append(f"{e.send_date.isoformat()} | {e.theme} | status: {e.status} | draft due: {e.draft_deadline or '-'}")
        if e.brief:
            lines.append(f"    Brief: {e.brief}")
    gw = registry.get("google_workspace")
    doc_id = await gw.create_document(f"{cal.name} (review)", "\n".join(lines))
    async with session_scope() as s:
        c = await s.get(EmailCalendar, cal_id)
        c.google_doc_id = doc_id
        audit(s, action="email_calendar.export_doc", target_type="email_calendar", target_id=cal_id,
              organization_id=cal.organization_id, client_id=cal.client_id, actor_user_id=ctx().user.id,
              details={"doc_id": doc_id, "mode": gw.mode})
    return ok({"google_doc_id": doc_id, "mode": gw.mode})


@bp.post("/scheduled-emails/<email_id>/asana-handoff")
@authenticated
async def asana_handoff(email_id: str):
    e = await load_scoped(ScheduledEmail, email_id, "email:write")
    if e.status not in ("approved", "in_review", "drafting", "planned"):
        raise ValidationFailed("Email already produced")
    from app.models import Client

    async with session_scope() as s:
        client = await s.get(Client, e.client_id)
        key = f"scheduled_email:{e.id}"
        existing = (await s.execute(select(ExternalMapping).where(ExternalMapping.provider == "asana",
                                                                 ExternalMapping.idempotency_key == key))).scalar_one_or_none()
    if existing:
        return ok({"asana_task_gid": existing.external_id, "duplicate": True})
    project = (client.settings or {}).get("asana_project_gid")
    if not project:
        raise ValidationFailed("Client has no asana_project_gid configured in settings")
    asana = registry.get("asana")
    gid = await asana.create_task(project_gid=project, name=f"[Email] {e.send_date} — {e.theme}",
                                  notes=f"Brief: {e.brief}\nSource doc: {e.source_doc_id or 'TBD'}",
                                  due_on=(e.draft_deadline or e.send_date).isoformat())
    async with session_scope() as s:
        s.add(ExternalMapping(organization_id=e.organization_id, provider="asana", idempotency_key=key,
                              internal_type="scheduled_email", internal_id=e.id, external_id=gid))
        se = await s.get(ScheduledEmail, email_id)
        se.asana_task_gid = gid
        audit(s, action="asana.task_created", target_type="scheduled_email", target_id=e.id,
              organization_id=e.organization_id, client_id=e.client_id, actor_user_id=ctx().user.id, details={"gid": gid})
    return ok({"asana_task_gid": gid, "duplicate": False, "mode": asana.mode}, 201)


# ------------------------------------------------------------------ production pipeline
class ProductionIn(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    preheader: str = ""
    google_doc_id: str | None = None
    text: str | None = None
    scheduled_email_id: str | None = None
    template: Literal["standard", "minimal"] = "standard"
    sender_name: str = Field(min_length=1)
    sender_address: EmailStr


class ProductionPatch(BaseModel):
    subject: str | None = None
    preheader: str | None = None
    html: str | None = None


def _hist(rec: ProductionRecord, action: str, **extra) -> list[dict]:
    return [*rec.history, {"at": datetime.now(UTC).isoformat(), "by": ctx().user.id, "action": action, **extra}]


@bp.get("/clients/<client_id>/productions")
@authenticated
async def list_productions(client_id: str):
    await get_client_checked(client_id, "email:read")
    async with session_scope() as s:
        rows = (await s.execute(select(ProductionRecord).where(ProductionRecord.client_id == client_id)
                                .order_by(ProductionRecord.created_at.desc()))).scalars()
        return ok([{k: v for k, v in r.to_dict().items() if k not in ("html", "source_text")} for r in rows])


@bp.post("/clients/<client_id>/productions")
@authenticated
async def create_production(client_id: str):
    c = await get_client_checked(client_id, "email:write")
    data = await body(ProductionIn)
    if bool(data.google_doc_id) == bool(data.text):
        raise ValidationFailed("Provide exactly one of google_doc_id or text")
    if data.google_doc_id:
        doc = await registry.get("google_workspace").get_document(data.google_doc_id)
        blocks = blocks_from_google_doc(doc)
        source_text = "\n".join("".join(r["text"] for r in b["runs"]) for b in blocks)
    else:
        blocks = blocks_from_text(data.text or "")
        source_text = data.text or ""
    html = render_html(blocks, subject=data.subject, preheader=data.preheader, sender_name=data.sender_name,
                       sender_address=data.sender_address, template=data.template)
    validation = validate_html(html, subject=data.subject, sender_address=data.sender_address)
    validation["sender"] = {"name": data.sender_name, "address": data.sender_address}
    async with session_scope() as s:
        rec = ProductionRecord(organization_id=c.organization_id, client_id=client_id, subject=data.subject,
                               preheader=data.preheader, source_doc_id=data.google_doc_id, source_text=source_text,
                               html=html, template=data.template, validation=validation,
                               scheduled_email_id=data.scheduled_email_id,
                               status="validated" if validation["passed"] else "draft",
                               history=[{"at": datetime.now(UTC).isoformat(), "by": ctx().user.id, "action": "converted"}])
        s.add(rec)
        await s.flush()
        audit(s, action="production.create", target_type="production", target_id=rec.id,
              organization_id=c.organization_id, client_id=client_id, actor_user_id=ctx().user.id)
    return ok(rec.to_dict(), 201)


@bp.get("/productions/<rec_id>")
@authenticated
async def get_production(rec_id: str):
    return ok((await load_scoped(ProductionRecord, rec_id, "email:read")).to_dict())


@bp.get("/productions/<rec_id>/preview")
@authenticated
async def preview(rec_id: str):
    rec = await load_scoped(ProductionRecord, rec_id, "email:read")
    return rec.html, 200, {"Content-Type": "text/html; charset=utf-8",
                           "Content-Security-Policy": "default-src 'none'; img-src https: data:; style-src 'unsafe-inline'"}


@bp.patch("/productions/<rec_id>")
@authenticated
async def patch_production(rec_id: str):
    rec = await load_scoped(ProductionRecord, rec_id, "email:write")
    if rec.status in ("approved", "test_prepared", "handed_off"):
        raise Conflict("Approved productions are immutable; create a new version")
    data = await body(ProductionPatch)
    async with session_scope() as s:
        r = await s.get(ProductionRecord, rec_id)
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(r, k, v)
        sender = (r.validation or {}).get("sender", {})
        r.validation = validate_html(r.html, subject=r.subject, sender_address=sender.get("address", "")) | {"sender": sender}
        r.status = "validated" if r.validation["passed"] else "draft"
        r.history = _hist(r, "edited")
    return ok(r.to_dict())


@bp.post("/productions/<rec_id>/approve")
@authenticated
async def approve_production(rec_id: str):
    rec = await load_scoped(ProductionRecord, rec_id, "email:approve")
    if rec.status != "validated":
        raise ValidationFailed("Only productions that pass validation can be approved")
    async with session_scope() as s:
        r = await s.get(ProductionRecord, rec_id)
        r.status, r.approved_by, r.approved_at = "approved", ctx().user.id, datetime.now(UTC)
        r.history = _hist(r, "approved")
        if r.scheduled_email_id:
            se = await s.get(ScheduledEmail, r.scheduled_email_id)
            if se and se.client_id == r.client_id:
                se.status = "approved"
        audit(s, action="production.approve", target_type="production", target_id=rec_id,
              organization_id=r.organization_id, client_id=r.client_id, actor_user_id=ctx().user.id)
    return ok(r.to_dict())


class TestSendIn(BaseModel):
    recipients: list[EmailStr] = Field(min_length=1, max_length=10)


@bp.post("/productions/<rec_id>/prepare-test")
@authenticated
async def prepare_test(rec_id: str):
    """Prepares (does not send) a test send package: seed list + final HTML, recorded for the operator."""
    rec = await load_scoped(ProductionRecord, rec_id, "email:write")
    if rec.status not in ("approved", "test_prepared"):
        raise ValidationFailed("Production must be approved before preparing a test send")
    data = await body(TestSendIn)
    async with session_scope() as s:
        r = await s.get(ProductionRecord, rec_id)
        r.status = "test_prepared"
        r.history = _hist(r, "test_prepared", recipients=len(data.recipients))
    return ok({"status": "test_prepared", "recipients": [str(x) for x in data.recipients],
               "note": "Test send must be triggered by an operator in the sending platform."})


class HandoffIn(BaseModel):
    platform: Literal["action_network", "actionkit", "ngpvan", "manual"]


@bp.post("/productions/<rec_id>/handoff")
@authenticated
async def handoff(rec_id: str):
    rec = await load_scoped(ProductionRecord, rec_id, "email:approve")
    if rec.status not in ("approved", "test_prepared"):
        raise ValidationFailed("Production must be approved before CRM handoff")
    data = await body(HandoffIn)
    sender = (rec.validation or {}).get("sender", {})
    mode = "manual"
    if data.platform == "action_network":
        adapter = registry.get("action_network")
        ref = await adapter.create_message_draft(subject=rec.subject, body_html=rec.html,
                                                 from_name=sender.get("name", ""), reply_to=sender.get("address", ""))
        mode = adapter.mode
    elif data.platform == "actionkit":
        adapter = registry.get("actionkit")
        ref = await adapter.create_mailing_draft(subject=rec.subject, html=rec.html, from_line=sender.get("name", ""))
        mode = adapter.mode
    else:
        # NGP VAN/EveryAction email content creation is not exposed for this use in the public API we rely on;
        # export HTML for authorized manual upload.
        ref = f"manual-export-{rec.id[:8]}"
    async with session_scope() as s:
        r = await s.get(ProductionRecord, rec_id)
        r.status, r.crm_platform, r.crm_reference = "handed_off", data.platform, ref
        r.history = _hist(r, "handed_off", platform=data.platform, mode=mode)
        if r.scheduled_email_id:
            se = await s.get(ScheduledEmail, r.scheduled_email_id)
            if se and se.client_id == r.client_id:
                se.status = "produced"
    await events.emit("production.completed", organization_id=rec.organization_id, client_id=rec.client_id,
                      data={"production_id": rec.id, "platform": data.platform}, actor_user_id=ctx().user.id,
                      summary=f"Email '{rec.subject}' handed off to {data.platform} as a draft")
    return ok({"status": "handed_off", "reference": ref, "mode": mode,
               "note": "Created as a draft only. Sending is performed by a human in the platform."})
