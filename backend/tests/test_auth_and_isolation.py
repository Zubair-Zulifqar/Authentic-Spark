from tests.conftest import ADMIN, H, add_member


async def test_health(client):
    assert (await client.get("/healthz")).status_code == 200
    assert (await client.get("/readyz")).status_code == 200


async def test_missing_and_invalid_tokens(client):
    assert (await client.get("/api/v1/me")).status_code == 401
    r = await client.get("/api/v1/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
    assert (await r.get_json())["error"]["code"] == "unauthorized"


async def test_login_creates_user_and_me(client, org):
    r = await client.get("/api/v1/me", headers=ADMIN)
    d = (await r.get_json())["data"]
    assert d["user"]["email"] == "admin@agency.example.org"
    assert d["organizations"][0]["id"] == org["id"]
    assert "billing:approve" in d["permissions"][f"{org['id']}:*"]


async def test_firebase_mode_rejects_dev_tokens(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "firebase")
    import app.core.auth as auth

    def boom(_t):
        from app.core.errors import Unauthorized
        raise Unauthorized("Invalid or expired token")

    monkeypatch.setattr(auth, "_verify_firebase", boom)
    r = await client.get("/api/v1/me", headers=ADMIN)
    assert r.status_code == 401


async def test_client_isolation(client, org, two_clients):
    alpha, beta = two_clients
    am = await add_member(client, org["id"], "am@agency.example.org", "account_manager", client_id=alpha["id"])
    r = await client.get(f"/api/v1/organizations/{org['id']}/clients", headers=am)
    names = [c["name"] for c in (await r.get_json())["data"]]
    assert names == ["Alpha Nonprofit"]
    # Cannot read or modify the other client: 404, not 403, to avoid leaking existence.
    assert (await client.get(f"/api/v1/clients/{beta['id']}", headers=am)).status_code == 404
    assert (await client.patch(f"/api/v1/clients/{beta['id']}", json={"name": "x"}, headers=am)).status_code == 404
    assert (await client.get(f"/api/v1/clients/{beta['id']}/campaigns", headers=am)).status_code == 404
    # Outsider from another org sees nothing.
    outsider = H("outsider@else.example.org")
    assert (await client.get(f"/api/v1/clients/{alpha['id']}", headers=outsider)).status_code == 404
    assert (await client.get(f"/api/v1/organizations/{org['id']}/dashboard", headers=outsider)).status_code == 404


async def test_client_scoped_user_cannot_create_clients(client, org, two_clients):
    am = await add_member(client, org["id"], "am2@agency.example.org", "account_manager", client_id=two_clients[0]["id"])
    r = await client.post(f"/api/v1/organizations/{org['id']}/clients", json={"name": "Sneaky"}, headers=am)
    assert r.status_code == 403


async def test_module_restriction(client, org, two_clients):
    alpha = two_clients[0]
    u = await add_member(client, org["id"], "narrow@agency.example.org", "operations_manager", modules=["clients", "email"])
    assert (await client.get(f"/api/v1/clients/{alpha['id']}/productions", headers=u)).status_code == 200
    assert (await client.get(f"/api/v1/clients/{alpha['id']}/invoices", headers=u)).status_code == 403
    r = await client.get(f"/api/v1/clients/{alpha['id']}/overview", headers=u)
    vis = (await r.get_json())["data"]["visible_modules"]
    assert "billing" not in vis and "email" in vis


async def test_read_only_cannot_write(client, org, two_clients):
    ro = await add_member(client, org["id"], "ro@agency.example.org", "read_only")
    r = await client.post(f"/api/v1/clients/{two_clients[0]['id']}/campaigns", json={"name": "Nope"}, headers=ro)
    assert r.status_code == 403


async def test_campaign_association_and_validation(client, two_clients):
    cid = two_clients[0]["id"]
    r = await client.post(f"/api/v1/clients/{cid}/campaigns", json={"name": "Spring", "start_date": "2026-05-01",
                                                                    "end_date": "2026-04-01"}, headers=ADMIN)
    assert r.status_code == 422
    r = await client.post(f"/api/v1/clients/{cid}/campaigns", json={"name": "Spring"}, headers=ADMIN)
    camp = (await r.get_json())["data"]
    assert camp["client_id"] == cid
    r = await client.patch(f"/api/v1/campaigns/{camp['id']}", json={"status": "active"}, headers=ADMIN)
    assert (await r.get_json())["data"]["status"] == "active"


async def test_dashboard_and_audit(client, org, two_clients):
    r = await client.get(f"/api/v1/organizations/{org['id']}/dashboard", headers=ADMIN)
    d = (await r.get_json())["data"]
    assert len(d["clients"]) == 2
    assert d["integration_health"]["zerobounce"] == "mock"
    r = await client.get(f"/api/v1/organizations/{org['id']}/audit", headers=ADMIN)
    actions = [a["action"] for a in (await r.get_json())["data"]]
    assert "client.create" in actions


async def test_validation_error_shape(client, org):
    r = await client.post(f"/api/v1/organizations/{org['id']}/clients", json={"name": ""}, headers=ADMIN)
    assert r.status_code == 422
    assert (await r.get_json())["error"]["details"][0]["loc"] == ["name"]


async def test_openapi(client):
    spec = (await (await client.get("/api/v1/openapi.json")).get_json())
    assert spec["openapi"].startswith("3.1")
    assert "/api/v1/clients/{client_id}/campaigns" in spec["paths"]
