"""QuickBooks Online adapter (https://developer.intuit.com/app/developer/qbo/docs/).

OAuth2: authorize at appcenter.intuit.com/connect/oauth2, tokens at
oauth.platform.intuit.com/oauth2/v1/tokens/bearer (access ~1h, refresh rotates).
Invoices: POST /v3/company/{realmId}/invoice ; PDF: GET /v3/company/{realmId}/invoice/{id}/pdf.
Webhooks: header `intuit-signature` = base64(HMAC-SHA256(verifier_token, raw_body)).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from typing import Any
from urllib.parse import urlencode

from app.services.integrations.base import HttpAdapter

AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
SCOPE = "com.intuit.quickbooks.accounting"


def authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    return AUTH_URL + "?" + urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
                                       "scope": SCOPE, "state": state})


def verify_webhook(verifier_token: str, raw_body: bytes, signature: str) -> bool:
    expected = base64.b64encode(hmac.new(verifier_token.encode(), raw_body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, signature or "")


class TokenSet:
    def __init__(self, access_token: str, refresh_token: str, expires_at: float):
        self.access_token, self.refresh_token, self.expires_at = access_token, refresh_token, expires_at

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at - 60


class QuickBooksClient(HttpAdapter):
    provider = "quickbooks"

    def __init__(self, client_id: str, client_secret: str, realm_id: str, tokens: TokenSet,
                 environment: str = "sandbox", **kw: Any):
        super().__init__(**kw)
        self.client_id, self.client_secret, self.realm_id, self.tokens = client_id, client_secret, realm_id, tokens
        host = "sandbox-quickbooks.api.intuit.com" if environment == "sandbox" else "quickbooks.api.intuit.com"
        self.base_url = f"https://{host}/v3/company/{realm_id}"

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens.access_token}", "Accept": "application/json"}

    async def refresh(self) -> TokenSet:
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        d = await self.request("POST", TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": self.tokens.refresh_token},
                               headers={"Authorization": f"Basic {basic}", "Accept": "application/json"})
        self.tokens = TokenSet(d["access_token"], d["refresh_token"], time.time() + int(d.get("expires_in", 3600)))
        return self.tokens

    async def _ensure(self) -> None:
        if self.tokens.expired:
            await self.refresh()

    async def create_invoice(self, *, customer_ref: str, lines: list[dict[str, Any]], due_date: str, request_id: str) -> str:
        await self._ensure()
        body = {"CustomerRef": {"value": customer_ref}, "DueDate": due_date, "Line": [
            {"DetailType": "SalesItemLineDetail", "Amount": round(li["quantity"] * li["unit_price_cents"] / 100, 2),
             "Description": li["description"], "SalesItemLineDetail": {"Qty": li["quantity"],
                                                                       "UnitPrice": li["unit_price_cents"] / 100}}
            for li in lines]}
        # requestid makes the create idempotent on Intuit's side.
        d = await self.request("POST", "/invoice", params={"requestid": request_id, "minorversion": "75"}, json=body)
        return d["Invoice"]["Id"]

    async def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        await self._ensure()
        return (await self.request("GET", f"/invoice/{invoice_id}"))["Invoice"]


class MockQuickBooks:
    provider, mode = "quickbooks", "mock"
    invoices: dict[str, dict[str, Any]] = {}
    by_request: dict[str, str] = {}

    async def create_invoice(self, *, customer_ref: str, lines: list[dict[str, Any]], due_date: str, request_id: str) -> str:
        if request_id in self.by_request:
            return self.by_request[request_id]
        iid = str(uuid.uuid4().int % 10**6)
        total = sum(li["quantity"] * li["unit_price_cents"] for li in lines) / 100
        self.invoices[iid] = {"Id": iid, "TotalAmt": total, "Balance": total}
        self.by_request[request_id] = iid
        return iid

    async def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        return self.invoices.get(invoice_id, {"Id": invoice_id, "TotalAmt": 0, "Balance": 0})
