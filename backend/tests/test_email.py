from app.services.email_production import blocks_from_text, render_html, validate_html
from tests.conftest import ADMIN, add_member


def test_html_conversion_and_validation_pass():
    blocks = blocks_from_text("# Hello\n\nWe opened the **garden**. [See photos](https://example.org/x)\n\n- One\n- Two")
    html = render_html(blocks, subject="Update", preheader="p", sender_name="Org", sender_address="news@example.org")
    assert "<strong>garden</strong>" in html and "<ul" in html and "unsubscribe_url" in html
    v = validate_html(html, subject="Update", sender_address="news@example.org")
    assert v["passed"], v


def test_validation_catches_problems():
    bad = '<html><body><a href="http://insecure.test">click here</a><img src="http://x/y.png"><div></body></html>'
    v = validate_html(bad, subject="", sender_address="nope")
    failed = {c["check"] for c in v["checks"] if not c["passed"]}
    assert {"links", "image_alt_text", "image_https", "unsubscribe_link", "sender_info", "subject_present",
            "mobile_viewport", "html_structure"} <= failed
    assert not v["passed"]


async def test_calendar_plan_approve_flow(client, two_clients):
    cid = two_clients[0]["id"]
    r = await client.post(f"/api/v1/clients/{cid}/email-calendars", json={
        "name": "June", "start_date": "2026-06-01", "end_date": "2026-06-14"}, headers=ADMIN)
    cal = (await r.get_json())["data"]
    r = await client.post(f"/api/v1/email-calendars/{cal['id']}/plan", json={
        "sends_per_week": 2, "themes": ["Program update", "Volunteer spotlight"], "blackout_dates": ["2026-06-02"]}, headers=ADMIN)
    ex = (await r.get_json())["data"]
    assert ex["status"] == "awaiting_approval"
    slots = ex["output"]["slots"]
    assert "2026-06-02" not in [s["send_date"] for s in slots]
    # Nothing created until approval.
    r = await client.get(f"/api/v1/email-calendars/{cal['id']}", headers=ADMIN)
    assert (await r.get_json())["data"]["emails"] == []
    r = await client.post(f"/api/v1/agent-executions/{ex['id']}/decision", json={"approve": True}, headers=ADMIN)
    assert (await r.get_json())["data"]["created"] == len(slots)
    r = await client.get(f"/api/v1/email-calendars/{cal['id']}?from=2026-06-01&to=2026-06-07", headers=ADMIN)
    emails = (await r.get_json())["data"]["emails"]
    assert emails and all(e["owner_user_id"] for e in emails)
    # Approval requires human author
    r = await client.patch(f"/api/v1/scheduled-emails/{emails[0]['id']}", json={"status": "approved"}, headers=ADMIN)
    assert r.status_code == 422
    r = await client.patch(f"/api/v1/scheduled-emails/{emails[0]['id']}", json={"status": "approved", "content_author": "Jo Writer"}, headers=ADMIN)
    assert r.status_code == 200
    # Asana handoff is idempotent
    r1 = await client.post(f"/api/v1/scheduled-emails/{emails[0]['id']}/asana-handoff", headers=ADMIN)
    r2 = await client.post(f"/api/v1/scheduled-emails/{emails[0]['id']}/asana-handoff", headers=ADMIN)
    g1, g2 = (await r1.get_json())["data"], (await r2.get_json())["data"]
    assert g1["asana_task_gid"] == g2["asana_task_gid"] and g2["duplicate"] is True
    r = await client.post(f"/api/v1/email-calendars/{cal['id']}/export-doc", headers=ADMIN)
    assert (await r.get_json())["data"]["google_doc_id"].startswith("mock-doc")


async def test_production_pipeline(client, org, two_clients):
    cid = two_clients[0]["id"]
    r = await client.post(f"/api/v1/clients/{cid}/productions", json={
        "subject": "Spring update", "google_doc_id": "mock-doc-spring-update", "sender_name": "Alpha",
        "sender_address": "news@example.org"}, headers=ADMIN)
    assert r.status_code == 201, await r.get_data()
    rec = (await r.get_json())["data"]
    assert rec["status"] == "validated", rec["validation"]
    assert "Spring volunteer update" in rec["html"]
    prev = await client.get(f"/api/v1/productions/{rec['id']}/preview", headers=ADMIN)
    assert prev.headers["Content-Type"].startswith("text/html")
    # Handoff blocked before approval
    r = await client.post(f"/api/v1/productions/{rec['id']}/handoff", json={"platform": "action_network"}, headers=ADMIN)
    assert r.status_code == 422
    # Email specialist without approve? has email:approve; read_only cannot approve
    ro = await add_member(client, org["id"], "ro2@agency.example.org", "read_only")
    assert (await client.post(f"/api/v1/productions/{rec['id']}/approve", headers=ro)).status_code == 403
    r = await client.post(f"/api/v1/productions/{rec['id']}/approve", headers=ADMIN)
    assert (await r.get_json())["data"]["status"] == "approved"
    # Immutable after approval
    assert (await client.patch(f"/api/v1/productions/{rec['id']}", json={"subject": "x"}, headers=ADMIN)).status_code == 409
    r = await client.post(f"/api/v1/productions/{rec['id']}/prepare-test", json={"recipients": ["qa@example.org"]}, headers=ADMIN)
    assert (await r.get_json())["data"]["status"] == "test_prepared"
    r = await client.post(f"/api/v1/productions/{rec['id']}/handoff", json={"platform": "action_network"}, headers=ADMIN)
    d = (await r.get_json())["data"]
    assert d["status"] == "handed_off" and d["mode"] == "mock"


async def test_production_failing_validation_stays_draft(client, two_clients):
    cid = two_clients[0]["id"]
    r = await client.post(f"/api/v1/clients/{cid}/productions", json={
        "subject": "Bad", "text": "Visit [here](http://insecure.example)", "sender_name": "A", "sender_address": "a@example.org"}, headers=ADMIN)
    rec = (await r.get_json())["data"]
    assert rec["status"] == "draft"
    assert (await client.post(f"/api/v1/productions/{rec['id']}/approve", headers=ADMIN)).status_code == 422
    r = await client.post(f"/api/v1/clients/{cid}/productions", json={"subject": "x", "sender_name": "A",
                                                                      "sender_address": "a@example.org"}, headers=ADMIN)
    assert r.status_code == 422
