import io
import json

from quart.datastructures import FileStorage

from app.services.events import sign
from tests.conftest import ADMIN

CSV = (b"Email,First Name,Zip,Mobile,SMS Opt In\n"
       b"ana@example.org,Ana,10001,555-201-0001,yes\n"
       b"ANA@example.org,Ana dup,10001,,\n"
       b"not-an-email,Bad,,,\n"
       b"bounce@example.org,Bo,,555-201-0002,yes\n"
       b"cy@example.org,Cy,,555-201-0003,no\n"
       b"supp@example.org,Sup,,,\n")


def form(**extra):
    base = {"name": "Vendor A June", "source_vendor": "Synthetic Vendor LLC", "usage_permission": "vendor_attested_opt_in",
            "consent_evidence": "Vendor attests double opt-in via petition form, records retained."}
    base.update(extra)
    return base


async def upload(client, cid, data=CSV, filename="list.csv", **extra):
    files = {"file": FileStorage(io.BytesIO(data), filename=filename, content_type="text/csv")}
    return await client.post(f"/api/v1/clients/{cid}/contact-lists", form=form(**extra), files=files, headers=ADMIN)


async def test_preview_mapping(client, two_clients):
    files = {"file": FileStorage(io.BytesIO(CSV), filename="l.csv")}
    r = await client.post(f"/api/v1/clients/{two_clients[0]['id']}/contact-lists/preview", files=files, headers=ADMIN)
    d = (await r.get_json())["data"]
    assert d["suggested_mapping"]["email"] == "Email" and d["suggested_mapping"]["first_name"] == "First Name"
    assert d["suggested_mapping"]["phone"] == "Mobile" and d["row_count"] == 6


async def test_upload_validate_dedupe_suppress_verify(client, two_clients):
    cid = two_clients[0]["id"]
    await client.post(f"/api/v1/clients/{cid}/suppressions", json={"channel": "email", "value": "supp@example.org"}, headers=ADMIN)
    r = await upload(client, cid)
    assert r.status_code == 201, await r.get_data()
    cl = (await r.get_json())["data"]
    st = cl["stats"]
    assert st == {"total": 6, "accepted": 4, "invalid": 1, "duplicates": 1, "suppressed": 1, "cross_list_duplicates": 0}
    r = await client.post(f"/api/v1/contact-lists/{cl['id']}/verify", headers=ADMIN)
    assert r.status_code == 202
    # duplicate verify request -> same job (idempotent)
    r2 = await client.post(f"/api/v1/contact-lists/{cl['id']}/verify", headers=ADMIN)
    assert (await r.get_json())["data"]["job_id"] == (await r2.get_json())["data"]["job_id"]
    ran = await client.post(f"/api/v1/organizations/{cl['organization_id']}/jobs/run", headers=ADMIN)
    assert (await ran.get_json())["data"]["succeeded"] >= 1
    r = await client.get(f"/api/v1/contact-lists/{cl['id']}", headers=ADMIN)
    d = (await r.get_json())["data"]
    assert d["status"] == "verified"
    assert d["status_counts"] == {"valid": 2, "invalid": 1, "suppressed": 1}
    assert any("invalid email" in i["reason"] for i in d["issues"])
    csv_out = await (await client.get(f"/api/v1/contact-lists/{cl['id']}/export.csv", headers=ADMIN)).get_data()
    assert b"ana@example.org" in csv_out and b"bounce@" not in csv_out and b"supp@" not in csv_out
    r = await client.post(f"/api/v1/contact-lists/{cl['id']}/crm-import", json={"file_url": "https://storage.example/signed"}, headers=ADMIN)
    assert (await r.get_json())["data"]["mode"] == "mock"
    # Re-upload: cross-list duplicates detected
    r = await upload(client, cid, name="Vendor A again")
    assert (await r.get_json())["data"]["stats"]["cross_list_duplicates"] >= 3


async def test_import_failures(client, two_clients):
    cid = two_clients[0]["id"]
    assert (await upload(client, cid, filename="x.xlsx")).status_code == 422
    assert (await upload(client, cid, data=b"\x00\x01binary")).status_code == 422
    assert (await upload(client, cid, consent_evidence="")).status_code == 422
    assert (await upload(client, cid, source_vendor="")).status_code == 422
    assert (await upload(client, cid, data=b"foo,bar\n1,2\n")).status_code == 422  # no email/phone column
    assert (await upload(client, cid, mapping=json.dumps({"email": "Nope"}))).status_code == 422


async def _sms_setup(client, cid):
    r = await upload(client, cid)
    cl = (await r.get_json())["data"]
    return cl


async def test_sms_consent_approval_flow(client, org, two_clients):
    cid = two_clients[0]["id"]
    cl = await _sms_setup(client, cid)
    body = {"name": "Event reminder", "message_author": "Jo Organizer", "sender_id": "AlphaNP",
            "message_body": "AlphaNP: Garden cleanup Sat 9am. Reply STOP to opt out.", "contact_list_id": cl["id"]}
    r = await client.post(f"/api/v1/clients/{cid}/sms-campaigns", json=body, headers=ADMIN)
    sms = (await r.get_json())["data"]
    # Only ana (consent yes) and bounce (consent yes) qualify; cy said no.
    assert sms["eligible_recipients"] == 2
    assert sms["compliance"]["passed"]
    # Cannot provision before approval
    assert (await client.post(f"/api/v1/sms-campaigns/{sms['id']}/provision", headers=ADMIN)).status_code == 422
    r = await client.post(f"/api/v1/sms-campaigns/{sms['id']}/submit", headers=ADMIN)
    assert (await r.get_json())["data"]["status"] == "pending_approval"
    r = await client.post(f"/api/v1/sms-campaigns/{sms['id']}/decision", json={"approve": True}, headers=ADMIN)
    assert (await r.get_json())["data"]["status"] == "approved"
    # STOP from Ana via signed inbound webhook removes consent immediately.
    payload = json.dumps({"from": "555-201-0001", "body": "STOP"}).encode()
    r = await client.post(f"/api/v1/webhooks/sms/inbound/{org['id']}/{cid}", data=payload,
                          headers={"X-Spark-Signature": sign("test-webhook-secret", payload), "Content-Type": "application/json"})
    assert (await r.get_json())["data"]["suppressed"] is True
    r = await client.post(f"/api/v1/sms-campaigns/{sms['id']}/provision", headers=ADMIN)
    d = (await r.get_json())["data"]
    assert d["status"] == "provisioned" and d["eligible_recipients"] == 1
    r = await client.post(f"/api/v1/sms-campaigns/{sms['id']}/refresh-status", headers=ADMIN)
    assert (await r.get_json())["data"]["provider_status"] == "provisioned_awaiting_launch"


async def test_sms_compliance_blocks_submit(client, two_clients):
    cid = two_clients[0]["id"]
    r = await client.post(f"/api/v1/clients/{cid}/sms-campaigns", json={
        "name": "Bad", "message_author": "Jo", "sender_id": "AlphaNP", "message_body": "Come to our event!"}, headers=ADMIN)
    sms = (await r.get_json())["data"]
    assert not sms["compliance"]["passed"]
    r = await client.post(f"/api/v1/sms-campaigns/{sms['id']}/submit", headers=ADMIN)
    assert r.status_code == 422


async def test_sms_webhook_rejects_bad_signature(client, org, two_clients):
    r = await client.post(f"/api/v1/webhooks/sms/inbound/{org['id']}/{two_clients[0]['id']}", json={"from": "5552010001", "body": "STOP"},
                          headers={"X-Spark-Signature": "t=1,v1=bad"})
    assert r.status_code == 401


async def test_sms_list_from_other_client_rejected(client, two_clients):
    cl = await _sms_setup(client, two_clients[1]["id"])
    r = await client.post(f"/api/v1/clients/{two_clients[0]['id']}/sms-campaigns", json={
        "name": "x", "message_author": "Jo", "sender_id": "AB", "message_body": "AB: hi. Reply STOP to opt out.",
        "contact_list_id": cl["id"]}, headers=ADMIN)
    assert r.status_code == 422
