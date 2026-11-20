"""Identity, organizations, memberships, teams, clients, campaigns, projects, dashboard, audit."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, EmailStr, Field
from quart import Blueprint, request
from sqlalchemy import func, select

from app.blueprints.common import client_ids_for, load_scoped
from app.core.audit import audit
from app.core.auth import authenticated, ctx, get_client_checked
from app.core.db import session_scope
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.http import body, ok, page_args
from app.core.rbac import MODULES, ROLE_PERMISSIONS, ROLES
from app.models import (
    AdCreative,
    AgentExecution,
    AuditLog,
    Campaign,
    Client,
    ComplianceEvent,
    ContactList,
    IntegrationConnection,
    Invoice,
    Job,
    Membership,
    Organization,
    ProductionRecord,
    Project,
    ScheduledEmail,
    SmsCampaign,
    Team,
    User,
)
from app.services import events
from app.services.integrations import registry

bp = Blueprint("core", __name__)


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80] or "item"


# ------------------------------------------------------------------ me / orgs
@bp.get("/me")
@authenticated
async def me():
    c = ctx()
    async with session_scope() as s:
        orgs = (await s.execute(select(Organization).where(Organization.id.in_(c.org_ids)))).scalars().all()
    perms: dict[str, list[str]] = {}
    for m in c.memberships:
        key = f"{m.organization_id}:{m.client_id or '*'}"
        ps = {p for p in ROLE_PERMISSIONS.get(m.role, set()) if m.modules is None or p.split(":")[0] in m.modules}
        perms[key] = sorted(set(perms.get(key, [])) | ps)
    await registry.get("mixpanel").track("login", c.user.id, {})
    return ok({"user": c.user.to_dict(), "organizations": [o.to_dict() for o in orgs],
               "memberships": [m.to_dict() for m in c.memberships], "permissions": perms})


class OrgIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)


@bp.post("/organizations")
@authenticated
async def create_org():
    data = await body(OrgIn)
    async with session_scope() as s:
        slug = slugify(data.name)
        if (await s.execute(select(Organization).where(Organization.slug == slug))).scalar_one_or_none():
            raise Conflict("Organization slug already exists")
        org = Organization(name=data.name, slug=slug)
        s.add(org)
        await s.flush()
        s.add(Membership(user_id=ctx().user.id, organization_id=org.id, role="agency_admin"))
        audit(s, action="organization.create", target_type="organization", target_id=org.id,
              organization_id=org.id, actor_user_id=ctx().user.id)
    return ok(org.to_dict(), 201)


@bp.get("/roles")
@authenticated
async def roles():
    return ok({"roles": {r: sorted(p) for r, p in ROLE_PERMISSIONS.items()}, "modules": list(MODULES)})


# ------------------------------------------------------------------ members & teams
class MemberIn(BaseModel):
    email: EmailStr
    role: str
    client_id: str | None = None
    modules: list[str] | None = None
    display_name: str = ""


@bp.get("/organizations/<org_id>/members")
@authenticated
async def list_members(org_id: str):
    ctx().require("admin:read", org_id)
    async with session_scope() as s:
        rows = (await s.execute(select(Membership, User).join(User, User.id == Membership.user_id)
                                .where(Membership.organization_id == org_id))).all()
    return ok([{**m.to_dict(), "email": u.email, "display_name": u.display_name} for m, u in rows])


@bp.post("/organizations/<org_id>/members")
@authenticated
async def add_member(org_id: str):
    ctx().require("admin:write", org_id)
    data = await body(MemberIn)
    if data.role not in ROLES:
        raise ValidationFailed(f"role must be one of {ROLES}")
    if data.modules and set(data.modules) - set(MODULES):
        raise ValidationFailed("unknown module")
    async with session_scope() as s:
        if data.client_id:
            cl = await s.get(Client, data.client_id)
            if cl is None or cl.organization_id != org_id:
                raise NotFound("Client not found")
        user = (await s.execute(select(User).where(User.email == data.email.lower()))).scalar_one_or_none()
        if user is None:
            user = User(email=data.email.lower(), firebase_uid=f"pending:{data.email.lower()}", display_name=data.display_name)
            s.add(user)
            await s.flush()
        dup = (await s.execute(select(Membership).where(
            Membership.user_id == user.id, Membership.organization_id == org_id,
            Membership.client_id.is_(None) if data.client_id is None else Membership.client_id == data.client_id))).scalar_one_or_none()
        if dup:
            raise Conflict("Membership already exists for this scope")
        m = Membership(user_id=user.id, organization_id=org_id, client_id=data.client_id, role=data.role, modules=data.modules)
        s.add(m)
        await s.flush()
        audit(s, action="membership.create", target_type="membership", target_id=m.id, organization_id=org_id,
              client_id=data.client_id, actor_user_id=ctx().user.id, details={"role": data.role})
    return ok(m.to_dict(), 201)


@bp.delete("/organizations/<org_id>/members/<membership_id>")
@authenticated
async def remove_member(org_id: str, membership_id: str):
    ctx().require("admin:write", org_id)
    async with session_scope() as s:
        m = await s.get(Membership, membership_id)
        if m is None or m.organization_id != org_id:
            raise NotFound("Membership not found")
        await s.delete(m)
        audit(s, action="membership.delete", target_type="membership", target_id=membership_id,
              organization_id=org_id, actor_user_id=ctx().user.id)
    return ok({"deleted": True})


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    member_ids: list[str] = []


@bp.get("/organizations/<org_id>/teams")
@authenticated
async def list_teams(org_id: str):
    ctx().require("clients:read", org_id)
    async with session_scope() as s:
        teams = (await s.execute(select(Team).where(Team.organization_id == org_id))).scalars().all()
    return ok([t.to_dict() for t in teams])


@bp.post("/organizations/<org_id>/teams")
@authenticated
async def create_team(org_id: str):
    ctx().require("admin:write", org_id)
    data = await body(TeamIn)
    async with session_scope() as s:
        t = Team(organization_id=org_id, name=data.name, member_ids=data.member_ids)
        s.add(t)
    return ok(t.to_dict(), 201)


# ------------------------------------------------------------------ clients
class ClientIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    client_type: Literal["nonprofit", "campaign", "pac", "advocacy", "business"] = "nonprofit"
    settings: dict = {}


class ClientPatch(BaseModel):
    name: str | None = None
    status: Literal["active", "paused", "archived"] | None = None
    settings: dict | None = None
    pinned_modules: list[str] | None = None


@bp.get("/organizations/<org_id>/clients")
@authenticated
async def list_clients(org_id: str):
    ids = await client_ids_for(org_id, "clients:read")
    q = request.args.get("q", "").lower()
    async with session_scope() as s:
        stmt = select(Client).where(Client.id.in_(ids)).order_by(Client.name)
        if q:
            stmt = stmt.where(func.lower(Client.name).contains(q))
        clients = (await s.execute(stmt)).scalars().all()
    return ok([c.to_dict() for c in clients])


@bp.post("/organizations/<org_id>/clients")
@authenticated
async def create_client(org_id: str):
    ctx().require("clients:write", org_id)
    data = await body(ClientIn)
    async with session_scope() as s:
        slug = slugify(data.name)
        if (await s.execute(select(Client).where(Client.organization_id == org_id, Client.slug == slug))).scalar_one_or_none():
            raise Conflict("A client with this name already exists")
        c = Client(organization_id=org_id, name=data.name, slug=slug, client_type=data.client_type,
                   settings=data.settings, pinned_modules=["email", "contacts", "sms"])
        s.add(c)
        await s.flush()
        audit(s, action="client.create", target_type="client", target_id=c.id, organization_id=org_id,
              client_id=c.id, actor_user_id=ctx().user.id)
    await events.emit("client.created", organization_id=org_id, client_id=c.id, data={"name": c.name},
                      actor_user_id=ctx().user.id)
    return ok(c.to_dict(), 201)


@bp.get("/clients/<client_id>")
@authenticated
async def get_client(client_id: str):
    c = await get_client_checked(client_id, "clients:read")
    return ok(c.to_dict())


@bp.patch("/clients/<client_id>")
@authenticated
async def patch_client(client_id: str):
    await get_client_checked(client_id, "clients:write")
    data = await body(ClientPatch)
    async with session_scope() as s:
        c = await s.get(Client, client_id)
        for k, v in data.model_dump(exclude_none=True).items():
            if k == "pinned_modules" and set(v) - set(MODULES):
                raise ValidationFailed("unknown module")
            setattr(c, k, v)
        audit(s, action="client.update", target_type="client", target_id=c.id, organization_id=c.organization_id,
              client_id=c.id, actor_user_id=ctx().user.id, details=data.model_dump(exclude_none=True))
    return ok(c.to_dict())


@bp.get("/clients/<client_id>/overview")
@authenticated
async def client_overview(client_id: str):
    c = await get_client_checked(client_id, "clients:read")
    org = c.organization_id
    vis = {m: ctx().has(f"{m}:read", org, client_id) for m in MODULES}
    async with session_scope() as s:
        async def count(model, *conds):
            return (await s.execute(select(func.count()).select_from(model).where(model.client_id == client_id, *conds))).scalar_one()

        data = {
            "client": c.to_dict(),
            "visible_modules": [m for m, v in vis.items() if v],
            "counts": {
                "campaigns": await count(Campaign, Campaign.status != "archived"),
                "scheduled_emails": await count(ScheduledEmail) if vis["email"] else None,
                "productions_pending": await count(ProductionRecord, ProductionRecord.status.in_(["draft", "validated"])) if vis["email"] else None,
                "contact_lists": await count(ContactList) if vis["contacts"] else None,
                "sms_campaigns": await count(SmsCampaign) if vis["sms"] else None,
                "ad_creatives": await count(AdCreative) if vis["ads"] else None,
                "open_invoices": await count(Invoice, Invoice.status.in_(["approved", "issued", "partially_paid"])) if vis["billing"] else None,
                "open_compliance": await count(ComplianceEvent, ComplianceEvent.status.in_(["open", "needs_review"])) if vis["compliance"] else None,
            },
            "pending_approvals": await _approvals(s, [client_id]),
            "upcoming": [e.to_dict() for e in (await s.execute(select(ScheduledEmail).where(
                ScheduledEmail.client_id == client_id, ScheduledEmail.send_date >= date.today())
                .order_by(ScheduledEmail.send_date).limit(8))).scalars()] if vis["email"] else [],
            "recent_activity": [a.to_dict() for a in (await s.execute(select(AuditLog).where(
                AuditLog.client_id == client_id).order_by(AuditLog.created_at.desc()).limit(15))).scalars()],
            "integrations": [i.to_dict() for i in (await s.execute(select(IntegrationConnection).where(
                IntegrationConnection.client_id == client_id))).scalars()],
        }
    return ok(data)


async def _approvals(s, client_ids: list[str]) -> list[dict]:
    out = []
    for model, label, st in [(ProductionRecord, "email_production", "validated"), (SmsCampaign, "sms_campaign", "pending_approval"),
                             (AdCreative, "ad_creative", "in_review"), (Invoice, "invoice", "draft")]:
        rows = (await s.execute(select(model).where(model.client_id.in_(client_ids), model.status == st).limit(20))).scalars()
        for r in rows:
            out.append({"type": label, "id": r.id, "client_id": r.client_id,
                        "title": getattr(r, "name", None) or getattr(r, "subject", None) or getattr(r, "number", ""),
                        "created_at": r.created_at.isoformat()})
    return out


# ------------------------------------------------------------------ campaigns & projects
class CampaignIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    objective: str = ""
    channel: Literal["email", "sms", "ads", "multi"] = "multi"
    start_date: date | None = None
    end_date: date | None = None
    budget_cents: int = Field(default=0, ge=0)


class CampaignPatch(BaseModel):
    name: str | None = None
    objective: str | None = None
    status: Literal["planning", "active", "paused", "completed", "archived"] | None = None
    start_date: date | None = None
    end_date: date | None = None


@bp.get("/clients/<client_id>/campaigns")
@authenticated
async def list_campaigns(client_id: str):
    await get_client_checked(client_id, "campaigns:read")
    async with session_scope() as s:
        rows = (await s.execute(select(Campaign).where(Campaign.client_id == client_id).order_by(Campaign.created_at.desc()))).scalars()
        return ok([r.to_dict() for r in rows])


@bp.post("/clients/<client_id>/campaigns")
@authenticated
async def create_campaign(client_id: str):
    c = await get_client_checked(client_id, "campaigns:write")
    data = await body(CampaignIn)
    if data.start_date and data.end_date and data.end_date < data.start_date:
        raise ValidationFailed("end_date before start_date")
    async with session_scope() as s:
        camp = Campaign(organization_id=c.organization_id, client_id=client_id, **data.model_dump())
        s.add(camp)
        await s.flush()
        audit(s, action="campaign.create", target_type="campaign", target_id=camp.id, organization_id=c.organization_id,
              client_id=client_id, actor_user_id=ctx().user.id)
    await events.emit("campaign.created", organization_id=c.organization_id, client_id=client_id,
                      data={"campaign_id": camp.id, "name": camp.name}, actor_user_id=ctx().user.id)
    return ok(camp.to_dict(), 201)


@bp.patch("/campaigns/<campaign_id>")
@authenticated
async def patch_campaign(campaign_id: str):
    camp = await load_scoped(Campaign, campaign_id, "campaigns:write")
    data = await body(CampaignPatch)
    async with session_scope() as s:
        camp = await s.get(Campaign, campaign_id)
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(camp, k, v)
        audit(s, action="campaign.update", target_type="campaign", target_id=camp.id, organization_id=camp.organization_id,
              client_id=camp.client_id, actor_user_id=ctx().user.id, details=data.model_dump(exclude_none=True, mode="json"))
    return ok(camp.to_dict())


class ProjectIn(BaseModel):
    name: str = Field(min_length=2)
    campaign_id: str | None = None
    due_date: date | None = None


@bp.get("/clients/<client_id>/projects")
@authenticated
async def list_projects(client_id: str):
    await get_client_checked(client_id, "campaigns:read")
    async with session_scope() as s:
        return ok([p.to_dict() for p in (await s.execute(select(Project).where(Project.client_id == client_id))).scalars()])


@bp.post("/clients/<client_id>/projects")
@authenticated
async def create_project(client_id: str):
    c = await get_client_checked(client_id, "campaigns:write")
    data = await body(ProjectIn)
    async with session_scope() as s:
        p = Project(organization_id=c.organization_id, client_id=client_id, **data.model_dump())
        s.add(p)
    return ok(p.to_dict(), 201)


# ------------------------------------------------------------------ agency dashboard & audit
@bp.get("/organizations/<org_id>/dashboard")
@authenticated
async def dashboard(org_id: str):
    ids = await client_ids_for(org_id, "clients:read")
    soon = date.today() + timedelta(days=14)
    async with session_scope() as s:
        def grouped(model):
            return select(model.status, func.count()).where(model.client_id.in_(ids)).group_by(model.status)

        async def status_counts(model, perm):
            allowed = await client_ids_for(org_id, perm)
            rows = (await s.execute(select(model.status, func.count()).where(model.client_id.in_(allowed)).group_by(model.status))).all()
            return {k: v for k, v in rows}

        clients = (await s.execute(select(Client).where(Client.id.in_(ids)).order_by(Client.name))).scalars().all()
        email_ids = await client_ids_for(org_id, "email:read")
        billing_ids = await client_ids_for(org_id, "billing:read")
        data = {
            "clients": [c.to_dict() for c in clients],
            "active_campaigns": (await s.execute(select(func.count()).select_from(Campaign).where(
                Campaign.client_id.in_(ids), Campaign.status == "active"))).scalar_one(),
            "email_production": await status_counts(ProductionRecord, "email:read"),
            "sms": await status_counts(SmsCampaign, "sms:read"),
            "ads": await status_counts(AdCreative, "ads:read"),
            "invoices": await status_counts(Invoice, "billing:read"),
            "outstanding_cents": (await s.execute(select(func.coalesce(func.sum(Invoice.total_cents - Invoice.paid_cents), 0)).where(
                Invoice.client_id.in_(billing_ids), Invoice.status.in_(["issued", "partially_paid"])))).scalar_one(),
            "pending_approvals": await _approvals(s, ids),
            "deadlines": [e.to_dict() for e in (await s.execute(select(ScheduledEmail).where(
                ScheduledEmail.client_id.in_(email_ids), ScheduledEmail.send_date.between(date.today(), soon),
                ScheduledEmail.status != "produced").order_by(ScheduledEmail.send_date).limit(20))).scalars()],
            "recent_activity": [a.to_dict() for a in (await s.execute(select(AuditLog).where(
                AuditLog.organization_id == org_id,
                (AuditLog.client_id.in_(ids)) | (AuditLog.client_id.is_(None))).order_by(AuditLog.created_at.desc()).limit(20))).scalars()],
            "integration_health": {p: registry.mode(p) for p in registry.PROVIDERS},
            "failed_jobs": (await s.execute(select(func.count()).select_from(Job).where(
                Job.organization_id == org_id, Job.status == "failed"))).scalar_one(),
            "agent_runs_7d": (await s.execute(select(func.count()).select_from(AgentExecution).where(
                AgentExecution.organization_id == org_id))).scalar_one(),
        }
        _ = grouped
    return ok(data)


@bp.get("/organizations/<org_id>/audit")
@authenticated
async def audit_log(org_id: str):
    ctx().require("compliance:read", org_id)
    limit, offset = page_args()
    ids = await client_ids_for(org_id, "compliance:read")
    async with session_scope() as s:
        q = select(AuditLog).where(AuditLog.organization_id == org_id,
                                   (AuditLog.client_id.in_(ids)) | (AuditLog.client_id.is_(None)))
        if request.args.get("client_id"):
            q = q.where(AuditLog.client_id == request.args["client_id"])
        rows = (await s.execute(q.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset))).scalars()
        return ok([r.to_dict() for r in rows])
