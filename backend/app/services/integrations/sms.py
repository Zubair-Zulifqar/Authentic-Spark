"""Scale to Win adapter.

Scale to Win's API is provided to customers under agreement; its endpoints are not publicly documented,
so this module defines the *interface* the platform needs and ships only the explicit mock. A live
implementation should be written against the API reference supplied with your account (see
docs/scale-to-win-integration.md). The platform never sends: it provisions an approved campaign and
humans launch it in the provider console.
"""
from __future__ import annotations

import uuid
from typing import Any, Protocol


class SmsProvider(Protocol):
    provider: str
    mode: str

    async def provision_campaign(self, *, name: str, body: str, sender_id: str, recipients: int) -> dict[str, Any]: ...
    async def campaign_status(self, reference: str) -> dict[str, Any]: ...


class MockScaleToWin:
    provider, mode = "scale_to_win", "mock"
    _store: dict[str, dict[str, Any]] = {}

    async def provision_campaign(self, *, name: str, body: str, sender_id: str, recipients: int) -> dict[str, Any]:
        ref = f"stw-mock-{uuid.uuid4().hex[:10]}"
        self._store[ref] = {"reference": ref, "status": "provisioned_awaiting_launch", "recipients": recipients,
                            "delivered": 0, "failed": 0, "opt_outs": 0}
        return self._store[ref]

    async def campaign_status(self, reference: str) -> dict[str, Any]:
        return self._store.get(reference, {"reference": reference, "status": "unknown"})
