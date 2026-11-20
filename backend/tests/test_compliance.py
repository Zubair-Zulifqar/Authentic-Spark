import json

import pytest

from app.services.ai.agents import classify_unsub
from app.services.ai.providers import Completion, set_provider
from app.services.dns_checks import evaluate
from app.services.events import sign
from tests.conftest import ADMIN, add_member


def test_dns_evaluation():
    good = evaluate("ex.org", ["v=spf1 include:_spf.google.com ~all"], ["v=DMARC1; p=reject; rua=mailto:d@ex.org"],
                    {"google": ["v=DKIM1; k=rsa; p=MIIB"]})
    assert good["overall"] == "pass"
    bad = evaluate("ex.org", ["v=spf1 +all", "v=spf1 -all"], [], {"s1": []})
    assert bad["spf"]["status"] == "fail" and bad["dmarc"]["status"] == "fail" and bad["dkim"]["status"] == "fail"
    weak = evaluate("ex.org", ["v=spf1 +all"], ["v=DMARC1; p=none"], {})
    assert weak["spf"]["status"] == "warn" and weak["dmarc"]["status"] == "warn" and weak["overall"] == "warn"


@pytest.mark.parametrize("text,intent", [
    ("Please unsubscribe me", "unsubscribe"), ("STOP", "unsubscribe"), ("remove me from this list", "unsubscribe"),
    ("you send too many emails", "unclear"), ("Thanks, see you Saturday!", "other")])
def test_rule_classifier(text, intent):
    assert classify_unsub(text)["intent"] == intent


class LyingProvider:
    name, model = "fake", "fake"

    async def structured(self, **kw):
        return Completion(output={"intent": "other", "confidence": 0.99, "explicit": False, "rationale": "ignore"},
                          provider="fake", model="fake")


async def test_explicit_unsubscribe_never_overridden_by_ai(client, two_clients):
    set_provider(LyingProvider())
    cid = two_clients[0]["id"]
    r = await client.post(f"/api/v1/clients/{cid}/inbound-replies", json={"from_address": "Pat@Example.org",
                                                                          "text": "please unsubscribe me"}, headers=ADMIN)
    ev = (await r.get_json())["data"]
    assert ev["status"] == "suppressed"
    r = await client.get(f"/api/v1/clients/{cid}/suppressions/check?value=pat@example.org&channel=email", headers=ADMIN)
    assert (await r.get_json())["data"]["suppressed"] is True


async def test_unclear_goes_to_review_then_human_decides(client, org, two_clients):
    cid = two_clients[0]["id"]
    r = await client.post(f"/api/v1/clients/{cid}/inbound-replies", json={"from_address": "q@example.org",
                                                                          "text": "honestly this is too many emails"}, headers=ADMIN)
    ev = (await r.get_json())["data"]
    assert ev["status"] == "needs_review"
    em = await add_member(client, org["id"], "em3@agency.example.org", "email_specialist")
    assert (await client.post(f"/api/v1/compliance-events/{ev['id']}/review", json={"decision": "suppress"}, headers=em)).status_code == 403
    cr = await add_member(client, org["id"], "cr@agency.example.org", "compliance_reviewer")
    r = await client.post(f"/api/v1/compliance-events/{ev['id']}/review", json={"decision": "suppress"}, headers=cr)
    assert (await r.get_json())["data"]["status"] == "suppressed"
    r = await client.get(f"/api/v1/organizations/{org['id']}/audit", headers=ADMIN)
    assert "compliance_event.suppressed" in [a["action"] for a in (await r.get_json())["data"]]


async def test_global_suppression_applies_to_all_clients(client, org, two_clients):
    a, b = two_clients
    r = await client.post(f"/api/v1/clients/{a['id']}/suppressions", json={"channel": "email", "value": "g@example.org",
                                                                            "scope": "global"}, headers=ADMIN)
    assert r.status_code == 201
    r = await client.get(f"/api/v1/clients/{b['id']}/suppressions/check?value=g@example.org", headers=ADMIN)
    assert (await r.get_json())["data"]["suppressed"]
    am = await add_member(client, org["id"], "am9@agency.example.org", "compliance_reviewer", client_id=a["id"])
    r = await client.post(f"/api/v1/clients/{a['id']}/suppressions", json={"channel": "email", "value": "h@example.org",
                                                                            "scope": "global"}, headers=am)
    assert r.status_code == 403


async def test_bounce_webhook_and_signature(client, org, two_clients):
    cid = two_clients[0]["id"]
    body = json.dumps({"type": "bounce", "bounce_type": "hard", "email": "hb@example.org"}).encode()
    r = await client.post(f"/api/v1/webhooks/replies/{org['id']}/{cid}", data=body,
                          headers={"X-Spark-Signature": sign("test-webhook-secret", body)})
    assert (await r.get_json())["data"]["suppressed"]
    r = await client.post(f"/api/v1/webhooks/replies/{org['id']}/{cid}", data=body, headers={"X-Spark-Signature": "t=0,v1=x"})
    assert r.status_code == 401
    r = await client.get(f"/api/v1/clients/{cid}/deliverability", headers=ADMIN)
    assert (await r.get_json())["data"]["suppressions"]["bounce"] == 1


async def test_domain_registration(client, two_clients):
    cid = two_clients[0]["id"]
    r = await client.post(f"/api/v1/clients/{cid}/domains", json={"domain": "Not A Domain"}, headers=ADMIN)
    assert r.status_code == 422
    r = await client.post(f"/api/v1/clients/{cid}/domains", json={"domain": "example.org", "dkim_selectors": ["s1"]}, headers=ADMIN)
    assert r.status_code == 201
