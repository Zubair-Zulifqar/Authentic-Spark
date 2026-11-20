"""Invoicing with QuickBooks Online sync. Draft -> approve (finance) -> issue (creates QBO invoice)."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from quart import Blueprint, request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.blueprints.common import load_scoped
from app.core.audit import audit
from app.core.auth import authenticated, ctx, get_client_checked
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import Conflict, Unauthorized, ValidationFailed
from app.core.http import body, ok
from app.models import Client, Invoice, Organization, Payment, WebhookEvent
from app.services import events
from app.services.integrations import quickbooks, registry
from app.services.invoice_pdf import render_invoice_pdf

bp = Blueprint("billing", __name__)
TERMS = {"due_on_receipt": 0, "net_15": 15, "net_30": 30, "net_45": 45, "net_60": 60}


class LineItem(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    quantity: float = Field(gt=0)
    unit_price_cents: int = Field(ge=0)


class InvoiceIn(BaseModel):
    line_items: list[LineItem] = Field(min_length=1)
    payment_terms: Literal["due_on_receipt", "net_15", "net_30", "net_45", "net_60"] = "net_30"
    tax_rate: float = Field(default=0.0, ge=0, le=0.25)
    issue_date: date | None = None
    memo: str = ""


def compute(items: list[LineItem], tax_rate: float) -> tuple[int, int, int]:
    sub = sum(round(li.quantity * li.unit_price_cents) for li in items)
    tax = round(sub * tax_rate)
    return sub, tax, sub + tax


@bp.get("/clients/<client_id>/invoices")
@authenticated
async def list_invoices(client_id: str):
    await get_client_checked(client_id, "billing:read")
    async with session_scope() as s:
        return ok([i.to_dict() for i in (await s.execute(select(Invoice).where(Invoice.client_id == client_id)
                                                          .order_by(Invoice.issue_date.desc()))).scalars()])


@bp.post("/clients/<client_id>/invoices/preview")
@authenticated
async def preview(client_id: str):
    await get_client_checked(client_id, "billing:write")
    data = await body(InvoiceIn)
    sub, tax, total = compute(data.line_items, data.tax_rate)
    issue = data.issue_date or date.today()
    return ok({"subtotal_cents": sub, "tax_cents": tax, "total_cents": total, "issue_date": issue.isoformat(),
               "due_date": (issue + timedelta(days=TERMS[data.payment_terms])).isoformat()})


@bp.post("/clients/<client_id>/invoices")
@authenticated
async def create_invoice(client_id: str):
    c = await get_client_checked(client_id, "billing:write")
    data = await body(InvoiceIn)
    sub, tax, total = compute(data.line_items, data.tax_rate)
    issue = data.issue_date or date.today()
    async with session_scope() as s:
        n = (await s.execute(select(func.count()).select_from(Invoice).where(Invoice.organization_id == c.organization_id))).scalar_one()
        inv = Invoice(organization_id=c.organization_id, client_id=client_id, number=f"AS-{issue.year}-{n + 1:05d}",
                      issue_date=issue, due_date=issue + timedelta(days=TERMS[data.payment_terms]),
                      payment_terms=data.payment_terms, tax_rate=data.tax_rate,
                      line_items=[li.model_dump() for li in data.line_items], subtotal_cents=sub, tax_cents=tax,
                      total_cents=total, memo=data.memo)
        s.add(inv)
        await s.flush()
        audit(s, action="invoice.create", target_type="invoice", target_id=inv.id, organization_id=c.organization_id,
              client_id=client_id, actor_user_id=ctx().user.id, details={"total_cents": total})
    await registry.get("mixpanel").track("invoice_created", ctx().user.id, {"client_id": client_id})
    return ok(inv.to_dict(), 201)


@bp.post("/invoices/<inv_id>/approve")
@authenticated
async def approve(inv_id: str):
    inv = await load_scoped(Invoice, inv_id, "billing:approve")
    if inv.status != "draft":
        raise ValidationFailed("Only drafts can be approved")
    async with session_scope() as s:
        x = await s.get(Invoice, inv_id)
        x.status, x.approved_by = "approved", ctx().user.id
        audit(s, action="invoice.approve", target_type="invoice", target_id=inv_id, organization_id=x.organization_id,
              client_id=x.client_id, actor_user_id=ctx().user.id)
    await events.emit("invoice.approved", organization_id=inv.organization_id, client_id=inv.client_id,
                      data={"invoice_id": inv_id, "number": inv.number}, summary=f"Invoice {inv.number} approved")
    return ok(x.to_dict())


@bp.post("/invoices/<inv_id>/issue")
@authenticated
async def issue(inv_id: str):
    """Creates the invoice in QuickBooks (idempotent via requestid=invoice id). Does not email it."""
    inv = await load_scoped(Invoice, inv_id, "billing:approve")
    if inv.status != "approved":
        raise ValidationFailed("Invoice must be approved before issuing")
    async with session_scope() as s:
        client = await s.get(Client, inv.client_id)
    customer_ref = (client.settings or {}).get("qbo_customer_id")
    if not customer_ref:
        raise ValidationFailed("Client has no qbo_customer_id configured")
    qbo = registry.get("quickbooks")
    qbo_id = await qbo.create_invoice(customer_ref=customer_ref, lines=inv.line_items, due_date=inv.due_date.isoformat(),
                                      request_id=inv.id)
    async with session_scope() as s:
        x = await s.get(Invoice, inv_id)
        x.status, x.qbo_invoice_id = "issued", qbo_id
        audit(s, action="invoice.issue", target_type="invoice", target_id=inv_id, organization_id=x.organization_id,
              client_id=x.client_id, actor_user_id=ctx().user.id, details={"qbo_id": qbo_id, "mode": qbo.mode})
    return ok(x.to_dict() | {"mode": qbo.mode})


@bp.get("/invoices/<inv_id>/pdf")
@authenticated
async def pdf(inv_id: str):
    inv = await load_scoped(Invoice, inv_id, "billing:read")
    async with session_scope() as s:
        client = await s.get(Client, inv.client_id)
        org = await s.get(Organization, inv.organization_id)
    data = render_invoice_pdf(inv, client.name, org.name)
    return data, 200, {"Content-Type": "application/pdf", "Content-Disposition": f'inline; filename="{inv.number}.pdf"'}


class PaymentIn(BaseModel):
    amount_cents: int = Field(gt=0)
    external_id: str | None = None


async def apply_payment(inv_id: str, amount: int, source: str, external_id: str) -> tuple[Invoice, bool]:
    async with session_scope() as s:
        inv = await s.get(Invoice, inv_id)
        dup = (await s.execute(select(Payment).where(Payment.source == source, Payment.external_id == external_id))).scalar_one_or_none()
        if dup:
            return inv, False
        s.add(Payment(organization_id=inv.organization_id, client_id=inv.client_id, invoice_id=inv.id,
                      amount_cents=amount, source=source, external_id=external_id))
        inv.paid_cents = min(inv.total_cents, inv.paid_cents + amount)
        inv.status = "paid" if inv.paid_cents >= inv.total_cents else "partially_paid"
    await events.emit("payment.received", organization_id=inv.organization_id, client_id=inv.client_id,
                      data={"invoice_id": inv.id, "amount_cents": amount}, summary=f"Payment received on {inv.number}")
    return inv, True


@bp.post("/invoices/<inv_id>/payments")
@authenticated
async def record_payment(inv_id: str):
    inv = await load_scoped(Invoice, inv_id, "billing:write")
    if inv.status not in ("issued", "partially_paid"):
        raise ValidationFailed("Payments can only be recorded on issued invoices")
    data = await body(PaymentIn)
    from app.models import uid

    inv, created = await apply_payment(inv_id, data.amount_cents, "manual", data.external_id or uid())
    if not created:
        raise Conflict("Duplicate payment")
    return ok(inv.to_dict(), 201)


@bp.get("/invoices/<inv_id>/payments")
@authenticated
async def payments(inv_id: str):
    await load_scoped(Invoice, inv_id, "billing:read")
    async with session_scope() as s:
        return ok([p.to_dict() for p in (await s.execute(select(Payment).where(Payment.invoice_id == inv_id))).scalars()])


@bp.post("/webhooks/quickbooks")
async def qbo_webhook():
    """Verifies intuit-signature, de-duplicates events, then syncs referenced invoices' balances from QBO."""
    verifier = get_settings().qbo_webhook_verifier
    raw = await request.get_data(as_text=False)
    if not verifier or not quickbooks.verify_webhook(verifier, raw, request.headers.get("intuit-signature", "")):
        raise Unauthorized("Invalid signature")
    payload = json.loads(raw or b"{}")
    processed = 0
    qbo = registry.get("quickbooks")
    for note in payload.get("eventNotifications", []):
        for ent in note.get("dataChangeEvent", {}).get("entities", []):
            key = f"{note.get('realmId')}:{ent.get('name')}:{ent.get('id')}:{ent.get('lastUpdated')}"
            try:
                async with session_scope() as s:
                    s.add(WebhookEvent(provider="quickbooks", event_key=key, payload=ent))
            except IntegrityError:
                continue  # duplicate delivery
            if ent.get("name") != "Invoice":
                continue
            async with session_scope() as s:
                inv = (await s.execute(select(Invoice).where(Invoice.qbo_invoice_id == str(ent.get("id"))))).scalar_one_or_none()
            if inv is None:
                continue
            remote = await qbo.get_invoice(inv.qbo_invoice_id)
            paid = round((float(remote.get("TotalAmt", 0)) - float(remote.get("Balance", 0))) * 100)
            delta = paid - inv.paid_cents
            if delta > 0:
                await apply_payment(inv.id, delta, "quickbooks", f"{inv.qbo_invoice_id}:{ent.get('lastUpdated')}")
            processed += 1
    return ok({"processed": processed, "received_at": datetime.now(UTC).isoformat()})
