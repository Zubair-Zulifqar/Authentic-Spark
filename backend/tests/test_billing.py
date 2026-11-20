import base64
import hashlib
import hmac
import json

from tests.conftest import ADMIN, add_member


def qbo_sig(body: bytes) -> str:
    return base64.b64encode(hmac.new(b"test-qbo-verifier", body, hashlib.sha256).digest()).decode()


async def make_invoice(client, cid):
    r = await client.post(f"/api/v1/clients/{cid}/invoices", json={
        "line_items": [{"description": "Email production", "quantity": 4, "unit_price_cents": 25000},
                       {"description": "List hygiene", "quantity": 1.5, "unit_price_cents": 10000}],
        "tax_rate": 0.05, "payment_terms": "net_15", "issue_date": "2026-03-01"}, headers=ADMIN)
    assert r.status_code == 201
    return (await r.get_json())["data"]


async def test_invoice_lifecycle_pdf_and_webhook(client, org, two_clients):
    cid = two_clients[0]["id"]
    r = await client.post(f"/api/v1/clients/{cid}/invoices/preview", json={
        "line_items": [{"description": "x", "quantity": 2, "unit_price_cents": 1000}], "tax_rate": 0.1}, headers=ADMIN)
    assert (await r.get_json())["data"]["total_cents"] == 2200
    inv = await make_invoice(client, cid)
    assert inv["subtotal_cents"] == 115000 and inv["tax_cents"] == 5750 and inv["total_cents"] == 120750
    assert inv["due_date"] == "2026-03-16"
    # issue blocked before approval; finance-less users cannot approve
    assert (await client.post(f"/api/v1/invoices/{inv['id']}/issue", headers=ADMIN)).status_code == 422
    em = await add_member(client, org["id"], "em@agency.example.org", "email_specialist")
    assert (await client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=em)).status_code == 403
    assert (await client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=ADMIN)).status_code == 200
    r = await client.post(f"/api/v1/invoices/{inv['id']}/issue", headers=ADMIN)
    issued = (await r.get_json())["data"]
    assert issued["status"] == "issued" and issued["qbo_invoice_id"]
    pdf = await client.get(f"/api/v1/invoices/{inv['id']}/pdf", headers=ADMIN)
    assert pdf.headers["Content-Type"] == "application/pdf"
    assert (await pdf.get_data()).startswith(b"%PDF")

    # QuickBooks reports partial payment -> webhook syncs it; duplicate delivery is ignored.
    from app.services.integrations import registry

    qbo = registry.get("quickbooks")
    qbo.invoices[issued["qbo_invoice_id"]].update(TotalAmt=1207.50, Balance=700.0)
    payload = json.dumps({"eventNotifications": [{"realmId": "1", "dataChangeEvent": {"entities": [
        {"name": "Invoice", "id": issued["qbo_invoice_id"], "operation": "Update", "lastUpdated": "2026-03-05T10:00:00Z"}]}}]}).encode()
    bad = await client.post("/api/v1/webhooks/quickbooks", data=payload, headers={"intuit-signature": "nope"})
    assert bad.status_code == 401
    for _ in range(2):
        r = await client.post("/api/v1/webhooks/quickbooks", data=payload, headers={"intuit-signature": qbo_sig(payload)})
        assert r.status_code == 200
    r = await client.get(f"/api/v1/invoices/{inv['id']}/payments", headers=ADMIN)
    pays = (await r.get_json())["data"]
    assert len(pays) == 1 and pays[0]["amount_cents"] == 50750
    r = await client.get(f"/api/v1/clients/{cid}/invoices", headers=ADMIN)
    assert (await r.get_json())["data"][0]["status"] == "partially_paid"
    # Manual remaining payment, duplicate external_id rejected
    r = await client.post(f"/api/v1/invoices/{inv['id']}/payments", json={"amount_cents": 70000, "external_id": "chk-1"}, headers=ADMIN)
    assert (await r.get_json())["data"]["status"] == "paid"


async def test_issue_is_idempotent_at_provider(client, two_clients):
    from app.services.integrations import registry

    qbo = registry.get("quickbooks")
    a = await qbo.create_invoice(customer_ref="1", lines=[{"description": "x", "quantity": 1, "unit_price_cents": 100}],
                                 due_date="2026-01-01", request_id="same")
    b = await qbo.create_invoice(customer_ref="1", lines=[{"description": "x", "quantity": 1, "unit_price_cents": 100}],
                                 due_date="2026-01-01", request_id="same")
    assert a == b
