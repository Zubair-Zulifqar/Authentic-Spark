"""Integrations, OAuth, automation (Zapier-compatible), Asana webhooks, background jobs, analytics."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl
from quart import Blueprint, redirect, request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.blueprints.common import client_ids_for
from app.core.audit import audit
from app.core.auth import authenticated, ctx, get_client_checked
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import NotFound, Unauthorized, ValidationFailed
from app.core.http import body, ok, page_args
from app.jobs import handlers
from app.jobs.runner import run_pending
from app.models import (
    AgentExecution,
    AutomationExecution,
    AutomationSubscription,
    Client,
    ComplianceEvent,
    ContactList,
    IntegrationConnection,
    Invoice,
    Job,
    OAuthState,
    ProductionRecord,
    ScheduledEmail,
    WebhookEvent,
)
from app.services import events
from app.services.integrations import google, quickbooks, registry
from app.services.suppression import add_suppression

bp = Blueprint("platform", __name__)

# ------------------------------------------------------------------ integrations
NON_SECRET_KEYS = {"channel_ids", "project_gid", "workspace_gid", "customer_id", "realm_id", "folder_id",
                   "instance", "committee_id", "notes"}


@bp.get("/organizations/<org_id>/integrations")
@authenticated
async def list_integrations(org_id: str):
    ctx().require("integrations:read", org_id)
    client_id = request.args.get("client_id")
    async with session_scope() as s:
        q = select(IntegrationConnection).where(IntegrationConnection.organization_id == org_id)
        q = q.where(IntegrationConnection.client_id == client_id) if client_id else q.where(IntegrationConnection.client_id.is_(None))
        conns = {c.provider: c for c in (await s.execute(q)).scalars()}
    out = []
    for p in registry.PROVIDERS:
        c = conns.get(p)
        out.append({"provider": p, "mode": registry.mode(p), "status": c.status if c else ("mock" if registry.mode(p) == "mock" else "available"),
                    "config": c.config if c else {}, "last_error": c.last_error if c else None,
                    "last_synced_at": c.last_synced_at.isoformat() if c and c.last_synced_at else None})
    return ok(out)


class ConnIn(BaseModel):
    provider: str
    client_id: str | None = None
    config: dict = {}
    secret_ref: str | None = Field(default=None, pattern=r"^projects/[^/]+/secrets/[^/]+(/versions/[^/]+)?$")


@bp.post("/organizations/<org_id>/integrations")
@authenticated
async def configure_integration(org_id: str):
    data = await body(ConnIn)
    if data.client_id:
        await get_client_checked(data.client_id, "integrations:write")
    else:
        ctx().require("integrations:write", org_id)
    if data.provider not in registry.PROVIDERS:
        raise ValidationFailed("unknown provider")
    if set(data.config) - NON_SECRET_KEYS:
        raise ValidationFailed(f"config may only contain non-secret keys {sorted(NON_SECRET_KEYS)}; store secrets in Secret Manager")
    async with session_scope() as s:
        q = select(IntegrationConnection).where(IntegrationConnection.organization_id == org_id,
                                                IntegrationConnection.provider == data.provider)
        q = q.where(IntegrationConnection.client_id == data.client_id) if data.client_id else q.where(IntegrationConnection.client_id.is_(None))
        conn = (await s.execute(q)).scalar_one_or_none()
        if conn is None:
            conn = IntegrationConnection(organization_id=org_id, client_id=data.client_id, provider=data.provider)
            s.add(conn)
        conn.config, conn.secret_ref = data.config, data.secret_ref
        conn.status = "configured" if data.secret_ref else registry.mode(data.provider)
        audit(s, action="integration.configure", target_type="integration", target_id=data.provider, organization_id=org_id,
              client_id=data.client_id, actor_user_id=ctx().user.id)
    await registry.get("mixpanel").track("integration_connected", ctx().user.id, {"provider": data.provider})
    return ok(conn.to_dict(), 201)


@bp.post("/organizations/<org_id>/integrations/<provider>/test")
@authenticated
async def test_integration(org_id: str, provider: str):
    ctx().require("integrations:read", org_id)
    try:
        if provider == "zerobounce":
            detail = {"credits": await registry.get(provider).credits()}
        elif provider == "ngpvan":
            detail = {"auth": await registry.get(provider).check_auth()}
        elif provider == "google_ads":
            detail = {"customers": await registry.get(provider).accessible_customers()}
        else:
            detail = {"mode": registry.mode(provider)}
        status, err = "ok", None
    except Exception as exc:
        status, err, detail = "error", str(exc), {}
    return ok({"provider": provider, "mode": registry.mode(provider), "status": status, "error": err, **detail})


OAUTH_PROVIDERS = {"google_docs", "google_sheets", "google_ads", "quickbooks"}


@bp.get("/oauth/<provider>/start")
@authenticated
async def oauth_start(provider: str):
    if provider not in OAUTH_PROVIDERS:
        raise NotFound("unknown provider")
    org_id, client_id = request.args.get("organization_id", ""), request.args.get("client_id")
    ctx().require("integrations:write", org_id, client_id)
    st = get_settings()
    state = secrets.token_urlsafe(32)
    async with session_scope() as s:
        s.add(OAuthState(state=state, provider=provider, user_id=ctx().user.id, organization_id=org_id, client_id=client_id))
    redirect_uri = f"{st.oauth_redirect_base}/api/v1/oauth/{provider}/callback"
    if provider == "quickbooks":
        if not st.qbo_client_id:
            raise ValidationFailed("QBO_CLIENT_ID not configured")
        url = quickbooks.authorization_url(st.qbo_client_id, redirect_uri, state)
    else:
        if not st.google_client_id:
            raise ValidationFailed("GOOGLE_OAUTH_CLIENT_ID not configured")
        url = google.authorization_url(provider, st.google_client_id, redirect_uri, state)
    return ok({"authorization_url": url})


@bp.get("/oauth/<provider>/callback")
async def oauth_callback(provider: str):
    """Validates the single-use, 10-minute state. Token exchange stores tokens in Secret Manager
    (see docs/authentication.md); here we record the connection and redirect back to the UI."""
    state, code = request.args.get("state", ""), request.args.get("code", "")
    async with session_scope() as s:
        row = (await s.execute(select(OAuthState).where(OAuthState.state == state))).scalar_one_or_none()
        created = row.created_at.replace(tzinfo=UTC) if row and row.created_at.tzinfo is None else (row.created_at if row else None)
        if row is None or row.consumed or row.provider != provider or created < datetime.now(UTC) - timedelta(minutes=10):
            raise Unauthorized("Invalid or expired OAuth state")
        if not code:
            raise ValidationFailed("Missing authorization code")
        row.consumed = True
        q = select(IntegrationConnection).where(IntegrationConnection.organization_id == row.organization_id,
                                                IntegrationConnection.provider == provider)
        q = q.where(IntegrationConnection.client_id == row.client_id) if row.client_id else q.where(IntegrationConnection.client_id.is_(None))
        conn = (await s.execute(q)).scalar_one_or_none() or IntegrationConnection(
            organization_id=row.organization_id, client_id=row.client_id, provider=provider)
        conn.status, conn.last_synced_at = "pending_token_exchange", datetime.now(UTC)
        conn.config = {**(conn.config or {}), **({"realm_id": request.args["realmId"]} if "realmId" in request.args else {})}
        s.add(conn)
    return redirect(f"{get_settings().cors_origins.split(',')[0]}/integrations?connected={provider}")


# ------------------------------------------------------------------ automation
class SubIn(BaseModel):
    event_type: str
    target_url: HttpUrl
    client_id: str | None = None


@bp.get("/automation/event-types")
async def event_types():
    return ok(events.EVENT_TYPES)


@bp.get("/organizations/<org_id>/automations")
@authenticated
async def list_subs(org_id: str):
    ctx().require("integrations:read", org_id)
    async with session_scope() as s:
        subs = (await s.execute(select(AutomationSubscription).where(AutomationSubscription.organization_id == org_id))).scalars()
        return ok([{k: v for k, v in x.to_dict().items() if k != "secret"} for x in subs])


@bp.post("/organizations/<org_id>/automations")
@authenticated
async def create_sub(org_id: str):
    """Zapier 'REST Hook' subscribe endpoint. Returns the signing secret once."""
    ctx().require("integrations:write", org_id)
    data = await body(SubIn)
    if data.event_type not in events.EVENT_TYPES:
        raise ValidationFailed("unknown event_type")
    if get_settings().is_production and data.target_url.scheme != "https":
        raise ValidationFailed("https required")
    async with session_scope() as s:
        sub = AutomationSubscription(organization_id=org_id, client_id=data.client_id, event_type=data.event_type,
                                     target_url=str(data.target_url), secret=secrets.token_hex(24))
        s.add(sub)
    return ok(sub.to_dict(), 201)


@bp.delete("/organizations/<org_id>/automations/<sub_id>")
@authenticated
async def delete_sub(org_id: str, sub_id: str):
    ctx().require("integrations:write", org_id)
    async with session_scope() as s:
        sub = await s.get(AutomationSubscription, sub_id)
        if sub is None or sub.organization_id != org_id:
            raise NotFound("subscription not found")
        await s.delete(sub)
    return ok({"deleted": True})


@bp.get("/organizations/<org_id>/automation-executions")
@authenticated
async def list_execs(org_id: str):
    ctx().require("integrations:read", org_id)
    limit, offset = page_args()
    async with session_scope() as s:
        rows = (await s.execute(select(AutomationExecution).where(AutomationExecution.organization_id == org_id)
                                .order_by(AutomationExecution.created_at.desc()).limit(limit).offset(offset))).scalars()
        return ok([r.to_dict() for r in rows])


class InboundIn(BaseModel):
    action: Literal["suppression.add", "compliance.flag"]
    client_id: str
    channel: Literal["email", "sms"] = "email"
    value: str = Field(min_length=3)
    note: str = ""


@bp.post("/webhooks/inbound/<org_id>")
async def inbound(org_id: str):
    """Incoming automation webhook (e.g. Zapier). HMAC-signed, idempotent via Idempotency-Key header."""
    secret = get_settings().webhook_signing_secret
    raw = await request.get_data(as_text=False)
    if not secret or not events.verify(secret, raw, request.headers.get("X-Spark-Signature", "")):
        raise Unauthorized("Invalid signature")
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise ValidationFailed("Idempotency-Key header required")
    try:
        data = InboundIn.model_validate_json(raw)
    except Exception as exc:
        raise ValidationFailed(str(exc)[:300]) from exc
    try:
        async with session_scope() as s:
            s.add(WebhookEvent(provider="inbound", event_key=f"{org_id}:{key}", payload=data.model_dump()))
    except IntegrityError:
        return ok({"duplicate": True})
    async with session_scope() as s:
        cl = await s.get(Client, data.client_id)
        if cl is None or cl.organization_id != org_id:
            raise NotFound("client not found")
        if data.action == "suppression.add":
            await add_suppression(s, org_id=org_id, client_id=data.client_id, channel=data.channel, value=data.value,
                                  reason="unsubscribe", source="inbound_webhook")
        else:
            s.add(ComplianceEvent(organization_id=org_id, client_id=data.client_id, kind="external_flag",
                                  channel=data.channel, subject_value=data.value, raw_text=data.note, status="needs_review"))
    return ok({"duplicate": False, "action": data.action}, 201)


@bp.post("/webhooks/asana")
async def asana_webhook():
    """Asana handshake (echo X-Hook-Secret) and signed event delivery; marks scheduled emails produced
    when their linked task is completed."""
    if "X-Hook-Secret" in request.headers:
        return "", 200, {"X-Hook-Secret": request.headers["X-Hook-Secret"]}
    secret = get_settings().asana_webhook_secret
    raw = await request.get_data(as_text=False)
    sig = request.headers.get("X-Hook-Signature", "")
    if not secret or not hmac.compare_digest(hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(), sig):
        raise Unauthorized("Invalid signature")
    payload = await request.get_json(force=True)
    handled = 0
    for ev in payload.get("events", []):
        res = ev.get("resource", {})
        key = f"{res.get('gid')}:{ev.get('action')}:{ev.get('created_at')}"
        try:
            async with session_scope() as s:
                s.add(WebhookEvent(provider="asana", event_key=key, payload=ev))
        except IntegrityError:
            continue
        if res.get("resource_type") == "task" and ev.get("change", {}).get("field") == "completed":
            async with session_scope() as s:
                se = (await s.execute(select(ScheduledEmail).where(ScheduledEmail.asana_task_gid == res.get("gid")))).scalar_one_or_none()
                if se and se.status != "produced":
                    se.status = "in_review"
                    handled += 1
    return ok({"handled": handled})


# ------------------------------------------------------------------ jobs
@bp.get("/organizations/<org_id>/jobs")
@authenticated
async def list_jobs(org_id: str):
    ctx().require("integrations:read", org_id)
    limit, offset = page_args()
    async with session_scope() as s:
        q = select(Job).where(Job.organization_id == org_id)
        if request.args.get("status"):
            q = q.where(Job.status == request.args["status"])
        rows = (await s.execute(q.order_by(Job.created_at.desc()).limit(limit).offset(offset))).scalars()
        return ok([r.to_dict() for r in rows])


@bp.post("/jobs/<job_id>/retry")
@authenticated
async def retry_job(job_id: str):
    async with session_scope() as s:
        j = await s.get(Job, job_id)
        if j is None or j.organization_id not in ctx().org_ids:
            raise NotFound("job not found")
        ctx().require("integrations:write", j.organization_id, j.client_id)
        if j.status != "failed":
            raise ValidationFailed("Only failed jobs can be retried")
        j.status, j.run_after, j.retry_count = "queued", datetime.now(UTC), 0
    return ok(j.to_dict())


@bp.post("/jobs/tick")
async def tick():
    """Cloud Scheduler target. Authenticated with a shared bearer token (or Cloud Run IAM/OIDC in prod)."""
    token = get_settings().scheduler_token
    if not token or not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {token}"):
        raise Unauthorized("Invalid scheduler token")
    scheduled = await handlers.schedule_periodic() if request.args.get("schedule", "1") == "1" else []
    return ok({"scheduled": scheduled, "ran": await run_pending()})


@bp.post("/organizations/<org_id>/jobs/run")
@authenticated
async def run_jobs_now(org_id: str):
    """Lets admins drain the queue on demand in environments without a worker."""
    ctx().require("integrations:write", org_id)
    return ok(await run_pending())


# ------------------------------------------------------------------ analytics
@bp.get("/organizations/<org_id>/analytics")
@authenticated
async def analytics(org_id: str):
    ids = await client_ids_for(org_id, "analytics:read")
    if request.args.get("client_id"):
        if request.args["client_id"] not in ids:
            raise NotFound("client not found")
        ids = [request.args["client_id"]]
    async with session_scope() as s:
        async def by_status(model):
            return dict((await s.execute(select(model.status, func.count()).where(model.client_id.in_(ids)).group_by(model.status))).all())

        jobs = await by_status(Job)
        done = jobs.get("succeeded", 0)
        total = done + jobs.get("failed", 0)
        agents = dict((await s.execute(select(AgentExecution.status, func.count()).where(
            AgentExecution.organization_id == org_id).group_by(AgentExecution.status))).all())
        executions = dict((await s.execute(select(AutomationExecution.status, func.count()).where(
            AutomationExecution.organization_id == org_id).group_by(AutomationExecution.status))).all())
        per_client = (await s.execute(select(ProductionRecord.client_id, func.count()).where(
            ProductionRecord.client_id.in_(ids), ProductionRecord.status == "handed_off").group_by(ProductionRecord.client_id))).all()
        names = dict((await s.execute(select(Client.id, Client.name).where(Client.id.in_(ids)))).all())
        lists = (await s.execute(select(func.count()).select_from(ContactList).where(ContactList.client_id.in_(ids)))).scalar_one()
        result = {
            "workflow_success_rate": round(done / total, 3) if total else None,
            "jobs": jobs, "agent_executions": agents, "webhook_deliveries": executions,
            "productions": await by_status(ProductionRecord),
            "scheduled_emails": await by_status(ScheduledEmail),
            "invoices": await by_status(Invoice),
            "compliance_events": await by_status(ComplianceEvent),
            "production_throughput": [{"client": names.get(c, c), "handed_off": n} for c, n in per_client],
            "contact_lists": lists,
        }
    return ok(result)
