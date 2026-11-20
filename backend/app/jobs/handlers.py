"""Job handlers: webhook delivery, Slack notifications, list verification, DNS checks, invoice reminders,
NGP VAN import status polling, retention."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select

from app.core.db import session_scope
from app.jobs.runner import enqueue, handler
from app.models import (
    AuditLog,
    ComplianceEvent,
    Contact,
    ContactList,
    Invoice,
    Job,
    SendingDomain,
)
from app.services import events
from app.services.dns_checks import check_domain
from app.services.integrations import registry

AUDIT_RETENTION_DAYS = 365 * 3
JOB_RETENTION_DAYS = 90


@handler("deliver_webhook")
async def deliver_webhook(job: Job) -> dict[str, Any]:
    return {"status": await events.deliver(job.payload["execution_id"])}


@handler("slack_notify")
async def slack_notify(job: Job) -> dict[str, Any]:
    ts = await registry.get("slack").post(job.payload["channel"], job.payload["text"])
    return {"ts": ts}


@handler("verify_contact_list")
async def verify_contact_list(job: Job) -> dict[str, Any]:
    list_id = job.payload["list_id"]
    zb = registry.get("zerobounce")
    async with session_scope() as s:
        cl = await s.get(ContactList, list_id)
        contacts = (await s.execute(select(Contact).where(
            Contact.list_id == list_id, Contact.status == "pending", Contact.email_normalized.is_not(None)))).scalars().all()
        results = await zb.validate_batch([c.email_normalized for c in contacts]) if contacts else []
        by_email = {r["email"]: r for r in results}
        counts = {"valid": 0, "invalid": 0, "risky": 0}
        for c in contacts:
            r = by_email.get(c.email_normalized)
            if r:
                c.status = r["status"]
                c.verification = {k: v for k, v in r.items() if k != "email"}
                counts[r["status"]] = counts.get(r["status"], 0) + 1
        cl.status = "verified"
        cl.stats = {**(cl.stats or {}), "verification": counts, "verification_mode": zb.mode,
                    "api_calls": (len(contacts) + 199) // 200}
        org, client = cl.organization_id, cl.client_id
    await events.emit("list_validation.completed", organization_id=org, client_id=client,
                      data={"list_id": list_id, **counts}, summary=f"List verification complete: {counts}")
    return counts


@handler("dns_check")
async def dns_check(job: Job) -> dict[str, Any]:
    async with session_scope() as s:
        d = await s.get(SendingDomain, job.payload["domain_id"])
        result = await check_domain(d.domain, d.dkim_selectors)
        d.last_check, d.last_checked_at = result, datetime.now(UTC)
        if result["overall"] == "fail":
            s.add(ComplianceEvent(organization_id=d.organization_id, client_id=d.client_id, kind="dns_issue",
                                  subject_value=d.domain, classification=result, status="open"))
        org, client = d.organization_id, d.client_id
    if result["overall"] == "fail":
        await events.emit("compliance.issue_detected", organization_id=org, client_id=client,
                          data={"domain": result["domain"]}, summary=f"DNS authentication failing for {result['domain']}")
    return result


@handler("invoice_reminders")
async def invoice_reminders(job: Job) -> dict[str, Any]:
    async with session_scope() as s:
        overdue = (await s.execute(select(Invoice).where(
            Invoice.status.in_(["issued", "partially_paid"]), Invoice.due_date < date.today()))).scalars().all()
        found = [(i.organization_id, i.client_id, i.number) for i in overdue]
    for org, client, number in found:
        await events.emit("approval.requested", organization_id=org, client_id=client,
                          data={"invoice": number, "reason": "overdue"}, summary=f"Invoice {number} is overdue — review reminder")
    return {"overdue": len(found)}


@handler("ngpvan_import_status")
async def ngpvan_import_status(job: Job) -> dict[str, Any]:
    status = await registry.get("ngpvan").import_status(job.payload["job_id"])
    async with session_scope() as s:
        cl = await s.get(ContactList, job.payload["list_id"])
        cl.crm_import_status = str(status.get("status"))
    return status


@handler("retention")
async def retention(job: Job) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with session_scope() as s:
        a = await s.execute(delete(AuditLog).where(AuditLog.created_at < now - timedelta(days=AUDIT_RETENTION_DAYS)))
        j = await s.execute(delete(Job).where(Job.status.in_(["succeeded"]), Job.created_at < now - timedelta(days=JOB_RETENTION_DAYS)))
    return {"audit_deleted": a.rowcount, "jobs_deleted": j.rowcount}


async def schedule_periodic() -> list[str]:
    """Enqueue daily jobs; idempotency keys include the date so repeated ticks are harmless."""
    today = date.today().isoformat()
    keys = []
    async with session_scope() as s:
        domains = (await s.execute(select(SendingDomain))).scalars().all()
        dom = [(d.id, d.organization_id, d.client_id) for d in domains]
    for did, org, client in dom:
        j = await enqueue("dns_check", payload={"domain_id": did}, idempotency_key=f"dns:{did}:{today}",
                          organization_id=org, client_id=client, workflow_id="deliverability")
        keys.append(j.idempotency_key)
    for kind in ("invoice_reminders", "retention"):
        j = await enqueue(kind, payload={}, idempotency_key=f"{kind}:{today}", workflow_id="scheduled")
        keys.append(j.idempotency_key)
    return keys
