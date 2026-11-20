"""Shared HTTP plumbing for third-party adapters: timeouts, retry with backoff on 429/5xx,
Retry-After support and normalized IntegrationError."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.errors import IntegrationError

RETRY_STATUSES = {429, 500, 502, 503, 504}


class HttpAdapter:
    provider = "base"
    mode = "live"
    base_url = ""
    max_retries = 3

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    def headers(self) -> dict[str, str]:
        return {}

    async def request(self, method: str, path: str, **kw: Any) -> Any:
        url = path if path.startswith("http") else self.base_url + path
        headers = {**self.headers(), **kw.pop("headers", {})}
        last: str = ""
        async with httpx.AsyncClient(timeout=20, transport=self._transport) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await client.request(method, url, headers=headers, **kw)
                except httpx.TransportError as exc:
                    last = f"transport error: {exc}"
                else:
                    if resp.status_code < 400:
                        return resp.json() if resp.content and "json" in resp.headers.get("content-type", "") else resp.content
                    last = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    if resp.status_code not in RETRY_STATUSES:
                        raise IntegrationError(f"{self.provider} request failed", details=last)
                    ra = resp.headers.get("Retry-After")
                    if ra and ra.isdigit() and attempt < self.max_retries:
                        await asyncio.sleep(min(int(ra), 10))
                        continue
                if attempt < self.max_retries:
                    await asyncio.sleep(min(0.2 * 2**attempt, 5))
        raise IntegrationError(f"{self.provider} unavailable after retries", details=last)
