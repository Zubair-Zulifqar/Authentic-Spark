"""Domain events -> automation (Zapier-compatible outbound webhooks), Slack notifications, Mixpanel.

Outbound deliveries are signed: header X-Spark-Signature = "t=<unix>,v1=<hex hmac_sha256(secret, f'{t}.{body}')>".
Each (subscription, event) pair is unique, so re-emitting the same event never double-delivers.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from sqlalchemy import or_, select

from app.core.db import session_scope
from app.core.logging import log
from app.models import AutomationExecution, AutomationSubscription, Client, Job, uid
from app.services.integrations import registry

EVENT_TYPES = [
    "client.created", "campaign.created", "email_calendar.updated", "production.completed",
    "contact_list.uploaded", "list_validation.completed", "sms_campaign.provisioned", "invoice.approved",
    "payment.received", "compliance.issue_detected", "workflow.failed", "approval.requested",
]

# Which events produce Slack notifications, and the category used for per-client channel routing.
SLACK_EVENTS = {
    "approval.requested": "approvals", "workflow.failed": "alerts", "compliance.issue_detected": "alerts",
    "sms_campaign.provisioned": "campaigns", "production.completed": "campaigns", "invoice.approved": "finance",
    "payment.received": "finance",
}


def sign(secret: str, body: bytes, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify(secret: str, body: bytes, header: str, tolerance: int = 300) -> bool:
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs(time.time() - ts) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, body, ts), header)


async def emit(event_type: str, *, organization_id: str, client_id: str | None, data: dict[str, Any],
               actor_user_id: str | None = None, summary: str = "") -> str:
    event_id = uid()
    payload = {"id": event_id, "type": event_type, "organization_id": organization_id, "client_id": client_id,
               "occurred_at": int(time.time()), "data": data}
    async with session_scope() as s:
        subs = (await s.execute(select(AutomationSubscription).where(
            AutomationSubscription.organization_id == organization_id,
            AutomationSubscription.event_type == event_type, AutomationSubscription.active.is_(True),
            or_(AutomationSubscription.client_id.is_(None), AutomationSubscription.client_id == client_id),
        ))).scalars().all()
        for sub in subs:
            ex = AutomationExecution(organization_id=organization_id, subscription_id=sub.id, event_id=event_id,
                                     event_type=event_type, payload=payload)
            s.add(ex)
            await s.flush()
            s.add(Job(organization_id=organization_id, client_id=client_id, workflow_id="automation",
                      kind="deliver_webhook", payload={"execution_id": ex.id}, idempotency_key=f"deliver:{ex.id}"))
        if event_type in SLACK_EVENTS and client_id:
            client = await s.get(Client, client_id)
            channels = (client.settings or {}).get("slack_channels", {}) if client else {}
            channel = channels.get(SLACK_EVENTS[event_type])
            if channel:
                # Only a short, non-sensitive summary goes to Slack (no contact data).
                s.add(Job(organization_id=organization_id, client_id=client_id, workflow_id="notifications",
                          kind="slack_notify", idempotency_key=f"slack:{event_id}",
                          payload={"channel": channel, "text": f"[{client.name}] {summary or event_type}"}))
    try:
        await registry.get("mixpanel").track(event_type, actor_user_id or "system",
                                             {"organization_id": organization_id, "client_id": client_id})
    except Exception as exc:  # analytics must never break workflows
        log.warning("mixpanel track failed", extra={"ctx": {"error": str(exc)}})
    return event_id


async def deliver(execution_id: str, transport: Any = None) -> str:
    import httpx

    async with session_scope() as s:
        ex = await s.get(AutomationExecution, execution_id)
        if ex is None or ex.status == "delivered":
            return "skipped"
        sub = await s.get(AutomationSubscription, ex.subscription_id)
        body = json.dumps(ex.payload, separators=(",", ":")).encode()
        ex.attempts += 1
        try:
            async with httpx.AsyncClient(timeout=10, transport=transport) as c:
                r = await c.post(sub.target_url, content=body, headers={
                    "Content-Type": "application/json", "X-Spark-Event": ex.event_type,
                    "X-Spark-Delivery": ex.id, "X-Spark-Signature": sign(sub.secret, body)})
            ex.last_response = f"{r.status_code}"
            ex.status = "delivered" if r.status_code < 300 else "failed"
        except httpx.HTTPError as exc:
            ex.status, ex.last_response = "failed", str(exc)[:500]
        status = ex.status
    if status == "failed":
        raise RuntimeError(f"webhook delivery failed ({ex.last_response})")
    return status
