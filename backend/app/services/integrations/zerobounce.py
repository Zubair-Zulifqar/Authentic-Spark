"""ZeroBounce email validation (https://www.zerobounce.net/docs/email-validation-api-quickstart/).
Uses GET /v2/validate, GET /v2/getcredits and POST bulkapi /v2/validatebatch (<=200 emails per call).
A valid status means deliverable, NOT permission to send marketing email."""
from __future__ import annotations

import hashlib
from typing import Any

from app.services.integrations.base import HttpAdapter

STATUS_MAP = {"valid": "valid", "invalid": "invalid", "spamtrap": "invalid", "abuse": "risky",
              "do_not_mail": "invalid", "catch-all": "risky", "unknown": "risky"}


class ZeroBounceClient(HttpAdapter):
    provider = "zerobounce"
    base_url = "https://api.zerobounce.net/v2"
    bulk_url = "https://bulkapi.zerobounce.net/v2"

    def __init__(self, api_key: str, **kw: Any):
        super().__init__(**kw)
        self.api_key = api_key

    async def credits(self) -> int:
        data = await self.request("GET", "/getcredits", params={"api_key": self.api_key})
        return int(data.get("Credits", 0))

    async def validate(self, email: str) -> dict[str, Any]:
        d = await self.request("GET", "/validate", params={"api_key": self.api_key, "email": email, "ip_address": ""})
        return {"email": email, "provider_status": d.get("status"), "sub_status": d.get("sub_status"),
                "status": STATUS_MAP.get(d.get("status", "unknown"), "risky")}

    async def validate_batch(self, emails: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i in range(0, len(emails), 200):
            chunk = emails[i:i + 200]
            d = await self.request("POST", f"{self.bulk_url}/validatebatch", json={
                "api_key": self.api_key, "email_batch": [{"email_address": e, "ip_address": None} for e in chunk]})
            for r in d.get("email_batch", []):
                out.append({"email": r.get("address"), "provider_status": r.get("status"),
                            "sub_status": r.get("sub_status"), "status": STATUS_MAP.get(r.get("status", "unknown"), "risky")})
        return out


class MockZeroBounce:
    """Development substitute. Deterministic: addresses at example.invalid / containing 'bounce' are invalid,
    'catchall' are risky, everything else valid."""

    provider, mode = "zerobounce", "mock"

    async def credits(self) -> int:
        return 10_000

    async def validate(self, email: str) -> dict[str, Any]:
        return (await self.validate_batch([email]))[0]

    async def validate_batch(self, emails: list[str]) -> list[dict[str, Any]]:
        out = []
        for e in emails:
            s = "invalid" if ("bounce" in e or e.endswith(".invalid")) else "catch-all" if "catchall" in e else "valid"
            out.append({"email": e, "provider_status": s, "sub_status": "mock",
                        "status": STATUS_MAP[s], "mock_hash": hashlib.sha1(e.encode()).hexdigest()[:8]})
        return out
