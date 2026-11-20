import hashlib
import hmac
import json

import httpx
import pytest

from app.core.errors import IntegrationError
from app.jobs.runner import enqueue, handler, run_pending
from app.services.events import sign, verify
from app.services.integrations.base import HttpAdapter
from app.services.integrations.zerobounce import ZeroBounceClient
from tests.conftest import ADMIN, H


class Flaky(HttpAdapter):
    provider, base_url, max_retries = "flaky", "https://api.test", 2


async def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _nosleep)
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"ok": True})

    assert await Flaky(transport=httpx.MockTransport(h)).request("GET", "/x") == {"ok": True}
    assert calls["n"] == 3


async def _nosleep(*_a, **_k):
    return None


async def test_rate_limit_retry_after_and_error(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _nosleep)
    t = httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "1"}, text="slow down"))
    with pytest.raises(IntegrationError) as e:
        await Flaky(transport=t).request("GET", "/x")
    assert "429" in str(e.value.details)
    t = httpx.MockTransport(lambda r: httpx.Response(401, text="bad key"))
    with pytest.raises(IntegrationError):
        await Flaky(transport=t).request("GET", "/x")


async def test_zerobounce_client_maps_statuses():
    def h(req):
        if "validatebatch" in str(req.url):
            body = json.loads(req.content)
            assert len(body["email_batch"]) <= 200
            return httpx.Response(200, json={"email_batch": [{"address": e["email_address"], "status": "catch-all", "sub_status": ""}
                                                             for e in body["email_batch"]]})
        return httpx.Response(200, json={"status": "valid", "sub_status": ""})

    zb = ZeroBounceClient("k", transport=httpx.MockTransport(h))
    assert (await zb.validate("a@example.org"))["status"] == "valid"
    res = await zb.validate_batch([f"u{i}@example.org" for i in range(250)])
    assert len(res) == 250 and res[0]["status"] == "risky"


def test_signatures():
    body = b'{"a":1}'
    assert verify("s", body, sign("s", body))
    assert not verify("s", body, sign("other", body))
    assert not verify("s", body, sign("s", body, ts=1))  # stale


async def test_inbound_webhook_idempotent(client, org, two_clients):
    body = json.dumps({"action": "suppression.add", "client_id": two_clients[0]["id"], "value": "z@example.org"}).encode()
    hdr = {"X-Spark-Signature": sign("test-webhook-secret", body), "Idempotency-Key": "evt-1"}
    r1 = await client.post(f"/api/v1/webhooks/inbound/{org['id']}", data=body, headers=hdr)
    r2 = await client.post(f"/api/v1/webhooks/inbound/{org['id']}", data=body, headers=hdr)
    assert (await r1.get_json())["data"]["duplicate"] is False
    assert (await r2.get_json())["data"]["duplicate"] is True


async def test_outbound_automation_delivery_and_retry(client, org, two_clients, monkeypatch):
    r = await client.post(f"/api/v1/organizations/{org['id']}/automations", json={
        "event_type": "campaign.created", "target_url": "https://hooks.example.test/catch"}, headers=ADMIN)
    sub = (await r.get_json())["data"]
    received = []

    def h(req):
        received.append(req)
        return httpx.Response(500) if len(received) == 1 else httpx.Response(200)

    import app.services.events as ev

    orig = ev.deliver
    monkeypatch.setattr("app.jobs.handlers.events.deliver", lambda eid: orig(eid, transport=httpx.MockTransport(h)))
    await client.post(f"/api/v1/clients/{two_clients[0]['id']}/campaigns", json={"name": "Hook test"}, headers=ADMIN)
    first = await run_pending()
    assert first["retrying"] == 1
    # Fast-forward the backoff and run again.
    from sqlalchemy import update

    from app.core.db import session_scope
    from app.models import Job

    async with session_scope() as s:
        await s.execute(update(Job).where(Job.status == "queued").values(run_after=Job.created_at))
    second = await run_pending()
    assert second["succeeded"] >= 1
    req = received[-1]
    assert verify(sub["secret"], req.content, req.headers["X-Spark-Signature"])
    r = await client.get(f"/api/v1/organizations/{org['id']}/automation-executions", headers=ADMIN)
    ex = (await r.get_json())["data"][0]
    assert ex["status"] == "delivered" and ex["attempts"] == 2


async def test_job_idempotency_and_failure():
    calls = {"n": 0}

    @handler("always_fails")
    async def _f(job):
        calls["n"] += 1
        raise RuntimeError("nope")

    j1 = await enqueue("always_fails", payload={}, idempotency_key="k1")
    j2 = await enqueue("always_fails", payload={}, idempotency_key="k1")
    assert j1.id == j2.id
    from sqlalchemy import update

    from app.core.db import session_scope
    from app.models import Job

    async with session_scope() as s:
        await s.execute(update(Job).where(Job.id == j1.id).values(max_retries=0))
    res = await run_pending()
    assert res["failed"] == 1 and calls["n"] == 1


async def test_scheduler_tick_requires_token(client):
    assert (await client.post("/api/v1/jobs/tick")).status_code == 401
    r = await client.post("/api/v1/jobs/tick?schedule=0", headers={"Authorization": "Bearer test-scheduler-token"})
    assert r.status_code == 200


async def test_asana_webhook_handshake_and_signature(client):
    r = await client.post("/api/v1/webhooks/asana", headers={"X-Hook-Secret": "abc"})
    assert r.headers["X-Hook-Secret"] == "abc"
    body = json.dumps({"events": []}).encode()
    bad = await client.post("/api/v1/webhooks/asana", data=body, headers={"X-Hook-Signature": "x"})
    assert bad.status_code == 401
    sig = hmac.new(b"test-asana-secret", body, hashlib.sha256).hexdigest()
    assert (await client.post("/api/v1/webhooks/asana", data=body, headers={"X-Hook-Signature": sig})).status_code == 200


async def test_oauth_state_validation(client, org, monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid.apps.googleusercontent.com")
    r = await client.get(f"/api/v1/oauth/google_docs/start?organization_id={org['id']}", headers=ADMIN)
    url = (await r.get_json())["data"]["authorization_url"]
    assert "drive.file" in url and "state=" in url
    state = url.split("state=")[1].split("&")[0]
    assert (await client.get("/api/v1/oauth/google_docs/callback?state=forged&code=x")).status_code == 401
    ok = await client.get(f"/api/v1/oauth/google_docs/callback?state={state}&code=x")
    assert ok.status_code == 302
    # single use
    assert (await client.get(f"/api/v1/oauth/google_docs/callback?state={state}&code=x")).status_code == 401


async def test_integration_config_rejects_secrets(client, org):
    r = await client.post(f"/api/v1/organizations/{org['id']}/integrations", json={"provider": "slack", "config": {"token": "xoxb"}}, headers=ADMIN)
    assert r.status_code == 422
    r = await client.post(f"/api/v1/organizations/{org['id']}/integrations", json={
        "provider": "slack", "config": {"channel_ids": ["C1"]}, "secret_ref": "projects/p/secrets/slack-bot"}, headers=ADMIN)
    assert r.status_code == 201
    r = await client.post(f"/api/v1/organizations/{org['id']}/integrations/zerobounce/test", headers=ADMIN)
    assert (await r.get_json())["data"]["credits"] == 10000


async def test_slack_notification_routed_per_client(client, two_clients):
    from app.services.integrations import registry

    slack = registry.get("slack")
    slack.sent.clear()
    cid = two_clients[0]["id"]
    r = await client.post(f"/api/v1/clients/{cid}/sms-campaigns", json={
        "name": "Notify test", "message_author": "Jo", "sender_id": "AB", "message_body": "AB: hi. Reply STOP to opt out."}, headers=ADMIN)
    assert r.status_code == 201
    from app.services import events

    await events.emit("approval.requested", organization_id=two_clients[0]["organization_id"], client_id=cid, data={},
                      summary="Needs approval")
    await run_pending()
    assert slack.sent and slack.sent[-1]["channel"] == "#a" and "@" not in slack.sent[-1]["text"]


async def test_rate_limiting(app, monkeypatch):
    from app.core.ratelimit import RateLimiter

    rl = RateLimiter(2)
    assert rl.allow("k") and rl.allow("k") and not rl.allow("k")
    _ = H


async def test_ads_and_ai_hub(client, org, two_clients):
    cid = two_clients[0]["id"]
    r = await client.post(f"/api/v1/clients/{cid}/ad-creatives", json={
        "platform": "google_ads", "format": "responsive_search", "name": "Search",
        "headlines": ["This headline is definitely far too long for google"], "descriptions": ["ok"],
        "is_political": True}, headers=ADMIN)
    cr = (await r.get_json())["data"]
    failed = {c["check"] for c in cr["checks"]["checks"] if not c["passed"]}
    assert {"character_limits", "paid_for_by_disclosure"} <= failed
    assert (await client.post(f"/api/v1/ad-creatives/{cr['id']}/submit", headers=ADMIN)).status_code == 422
    r = await client.patch(f"/api/v1/ad-creatives/{cr['id']}", json={"headlines": ["Volunteer this spring"],
                                                                     "disclaimer": "Paid for by Alpha Nonprofit"}, headers=ADMIN)
    cr = (await r.get_json())["data"]
    assert cr["checks"]["passed"] and cr["version"] == 2
    assert (await client.post(f"/api/v1/ad-creatives/{cr['id']}/submit", headers=ADMIN)).status_code == 200
    r = await client.post(f"/api/v1/ad-creatives/{cr['id']}/decision", json={"approve": True}, headers=ADMIN)
    assert (await r.get_json())["data"]["status"] == "approved"
    assert (await client.patch(f"/api/v1/ad-creatives/{cr['id']}", json={"name": "x"}, headers=ADMIN)).status_code == 409
    r = await client.get(f"/api/v1/ad-creatives/{cr['id']}/versions", headers=ADMIN)
    assert len((await r.get_json())["data"]) == 2
    r = await client.get(f"/api/v1/clients/{cid}/google-ads/campaigns", headers=ADMIN)
    assert (await r.get_json())["data"]["mode"] == "mock"

    r = await client.get("/api/v1/agents", headers=ADMIN)
    assert {a["key"] for a in (await r.get_json())["data"]} >= {"proofreader", "unsubscribe_classifier", "task_extractor"}
    r = await client.post("/api/v1/agents/proofreader/run", json={"organization_id": org["id"], "client_id": cid,
                                                                  "input": {"text": "We will recieve the the donations ."}}, headers=ADMIN)
    out = (await r.get_json())["data"]
    kinds = {i["kind"] for i in out["output"]["issues"]}
    assert {"spelling", "repeated_word", "punctuation"} <= kinds and out["provider"] == "rule_based"
    r = await client.post("/api/v1/agents/task_extractor/run", json={"organization_id": org["id"],
                          "input": {"text": "- Send brief to design 2026-04-02\n- Confirm list vendor"}}, headers=ADMIN)
    assert len((await r.get_json())["data"]["output"]["tasks"]) == 2
    r = await client.post("/api/v1/agents/proofreader/run", json={"organization_id": org["id"], "input": {}}, headers=ADMIN)
    assert r.status_code == 422
    r = await client.get(f"/api/v1/organizations/{org['id']}/agent-executions", headers=ADMIN)
    assert (await r.get_json())["data"]["usage"]
    r = await client.get(f"/api/v1/organizations/{org['id']}/analytics", headers=ADMIN)
    assert "workflow_success_rate" in (await r.get_json())["data"]


async def test_agent_provider_failure_recorded(client, org):
    from app.services.ai.providers import set_provider

    class Down:
        name, model = "openai", "x"

        async def structured(self, **kw):
            raise TimeoutError("upstream timeout")

    set_provider(Down())
    r = await client.post("/api/v1/agents/summarizer/run", json={"organization_id": org["id"], "input": {"text": "Hello."}}, headers=ADMIN)
    assert r.status_code == 502
    assert (await r.get_json())["data"]["status"] == "failed"
