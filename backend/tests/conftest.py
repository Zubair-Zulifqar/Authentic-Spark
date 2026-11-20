import os

os.environ.setdefault("AUTH_MODE", "dev")
os.environ["WEBHOOK_SIGNING_SECRET"] = "test-webhook-secret"
os.environ["SCHEDULER_TOKEN"] = "test-scheduler-token"
os.environ["QBO_WEBHOOK_VERIFIER_TOKEN"] = "test-qbo-verifier"
os.environ["ASANA_WEBHOOK_SECRET"] = "test-asana-secret"
os.environ["RATE_LIMIT_PER_MINUTE"] = "10000"
for k in ("OPENAI_API_KEY", "ZEROBOUNCE_API_KEY", "NGPVAN_API_KEY", "ASANA_ACCESS_TOKEN", "SLACK_BOT_TOKEN", "MIXPANEL_TOKEN"):
    os.environ.pop(k, None)

import pytest  # noqa: E402

from app.services.ai import providers  # noqa: E402
from app.services.integrations import registry  # noqa: E402


@pytest.fixture
async def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    from app.main import create_app

    registry.reset()
    providers.set_provider(None)
    a = create_app()
    async with a.test_app():
        yield a


@pytest.fixture
def client(app):
    return app.test_client()


def H(email: str) -> dict:
    return {"Authorization": f"Bearer dev:{email}"}


ADMIN = H("admin@agency.example.org")


@pytest.fixture
async def org(client):
    r = await client.post("/api/v1/organizations", json={"name": "Test Agency"}, headers=ADMIN)
    assert r.status_code == 201, await r.get_data()
    return (await r.get_json())["data"]


@pytest.fixture
async def two_clients(client, org):
    out = []
    for name in ("Alpha Nonprofit", "Beta Trust"):
        r = await client.post(f"/api/v1/organizations/{org['id']}/clients", json={
            "name": name, "settings": {"asana_project_gid": "123", "qbo_customer_id": "1",
                                       "google_ads_customer_id": "999", "slack_channels": {"approvals": "#a"}}}, headers=ADMIN)
        assert r.status_code == 201
        out.append((await r.get_json())["data"])
    return out


async def add_member(client, org_id, email, role, client_id=None, modules=None):
    r = await client.post(f"/api/v1/organizations/{org_id}/members",
                          json={"email": email, "role": role, "client_id": client_id, "modules": modules}, headers=ADMIN)
    assert r.status_code == 201, await r.get_data()
    return H(email)
