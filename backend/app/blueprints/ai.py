"""AI operations hub: list agents, run, history, usage, approvals."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel
from quart import Blueprint, request
from sqlalchemy import func, select

from app.blueprints.common import client_ids_for, load_scoped
from app.core.audit import audit
from app.core.auth import authenticated, ctx, get_client_checked
from app.core.db import session_scope
from app.core.errors import ValidationFailed
from app.core.http import body, ok, page_args
from app.models import AgentExecution, EmailCalendar, ScheduledEmail
from app.services import events
from app.services.ai.agents import AGENTS, run_agent

bp = Blueprint("ai", __name__)


@bp.get("/agents")
@authenticated
async def list_agents():
    return ok([a.describe() for a in AGENTS.values()])


class RunIn(BaseModel):
    organization_id: str
    client_id: str | None = None
    input: dict


@bp.post("/agents/<key>/run")
@authenticated
async def run(key: str):
    spec = AGENTS.get(key)
    if spec is None:
        raise ValidationFailed("Unknown agent")
    data = await body(RunIn)
    if data.client_id:
        c = await get_client_checked(data.client_id, spec.permission)
        if c.organization_id != data.organization_id:
            raise ValidationFailed("client does not belong to organization")
    else:
        ctx().require(spec.permission, data.organization_id)
    ex = await run_agent(key, data.input, organization_id=data.organization_id, client_id=data.client_id,
                         user_id=ctx().user.id)
    return ok(ex.to_dict(), 201 if ex.status != "failed" else 502)


@bp.get("/organizations/<org_id>/agent-executions")
@authenticated
async def executions(org_id: str):
    ids = await client_ids_for(org_id, "ai:read")
    limit, offset = page_args()
    async with session_scope() as s:
        q = select(AgentExecution).where(AgentExecution.organization_id == org_id,
                                         (AgentExecution.client_id.in_(ids)) | (AgentExecution.client_id.is_(None)))
        if request.args.get("agent"):
            q = q.where(AgentExecution.agent == request.args["agent"])
        rows = (await s.execute(q.order_by(AgentExecution.created_at.desc()).limit(limit).offset(offset))).scalars()
        usage = (await s.execute(select(AgentExecution.agent, func.count(), func.sum(AgentExecution.prompt_tokens),
                                        func.sum(AgentExecution.completion_tokens))
                                 .where(AgentExecution.organization_id == org_id).group_by(AgentExecution.agent))).all()
    return ok({"executions": [r.to_dict() for r in rows],
               "usage": [{"agent": a, "runs": n, "prompt_tokens": p or 0, "completion_tokens": c or 0} for a, n, p, c in usage]})


class ApproveIn(BaseModel):
    approve: bool


@bp.post("/agent-executions/<ex_id>/decision")
@authenticated
async def decide(ex_id: str):
    """Human approval gate. Approving a calendar plan materialises its slots as scheduled emails."""
    ex = await load_scoped(AgentExecution, ex_id, "ai:read")
    spec = AGENTS[ex.agent]
    ctx().require(spec.permission.split(":")[0] + ":write", ex.organization_id, ex.client_id)
    if ex.status != "awaiting_approval":
        raise ValidationFailed("Execution is not awaiting approval")
    data = await body(ApproveIn)
    created = 0
    async with session_scope() as s:
        x = await s.get(AgentExecution, ex_id)
        x.status, x.approved_by = ("approved" if data.approve else "rejected"), ctx().user.id
        if data.approve and x.agent == "email_calendar_planner":
            cal_id = x.input.get("calendar_id")
            cal = await s.get(EmailCalendar, cal_id) if cal_id else None
            if cal is None or cal.client_id != x.client_id:
                raise ValidationFailed("Plan has no valid calendar")
            for slot in x.output.get("slots", []):
                s.add(ScheduledEmail(organization_id=cal.organization_id, client_id=cal.client_id, calendar_id=cal.id,
                                     send_date=date.fromisoformat(slot["send_date"]), theme=slot["theme"],
                                     draft_deadline=date.fromisoformat(slot["draft_deadline"]),
                                     brief=slot.get("production_requirements", ""), owner_user_id=ctx().user.id))
                created += 1
        audit(s, action=f"agent.{x.status}", target_type="agent_execution", target_id=ex_id,
              organization_id=x.organization_id, client_id=x.client_id, actor_user_id=ctx().user.id)
    if created:
        await events.emit("email_calendar.updated", organization_id=ex.organization_id, client_id=ex.client_id,
                          data={"calendar_id": ex.input.get("calendar_id"), "created": created})
    return ok(x.to_dict() | {"created": created})
