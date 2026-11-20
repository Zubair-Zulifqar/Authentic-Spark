"""Asana, Slack and Mixpanel adapters.

Asana: https://developers.asana.com/reference — POST /tasks, PUT /tasks/{gid}, POST /tasks/{gid}/stories.
Webhooks use the X-Hook-Secret handshake and X-Hook-Signature (HMAC-SHA256 hex of body).
Slack: https://api.slack.com/methods/chat.postMessage (bot token, chat:write scope).
Mixpanel: https://developer.mixpanel.com/reference/track-event (POST /track, project token).
"""
from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any

from app.services.integrations.base import HttpAdapter


class AsanaClient(HttpAdapter):
    provider = "asana"
    base_url = "https://app.asana.com/api/1.0"

    def __init__(self, token: str, **kw: Any):
        super().__init__(**kw)
        self.token = token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    async def create_task(self, *, project_gid: str, name: str, notes: str, due_on: str | None,
                          assignee: str | None = None) -> str:
        data: dict[str, Any] = {"name": name, "notes": notes, "projects": [project_gid]}
        if due_on:
            data["due_on"] = due_on
        if assignee:
            data["assignee"] = assignee
        resp = await self.request("POST", "/tasks", json={"data": data})
        return resp["data"]["gid"]

    async def update_task(self, gid: str, **fields: Any) -> None:
        await self.request("PUT", f"/tasks/{gid}", json={"data": fields})

    async def comment(self, gid: str, text: str) -> None:
        await self.request("POST", f"/tasks/{gid}/stories", json={"data": {"text": text}})


class MockAsana:
    provider, mode = "asana", "mock"
    tasks: dict[str, dict[str, Any]] = {}

    async def create_task(self, *, project_gid: str, name: str, notes: str, due_on: str | None, assignee=None) -> str:
        gid = str(uuid.uuid4().int % 10**15)
        self.tasks[gid] = {"name": name, "notes": notes, "due_on": due_on, "project": project_gid, "completed": False}
        return gid

    async def update_task(self, gid: str, **fields: Any) -> None:
        self.tasks.setdefault(gid, {}).update(fields)

    async def comment(self, gid: str, text: str) -> None:
        self.tasks.setdefault(gid, {}).setdefault("comments", []).append(text)


class SlackClient(HttpAdapter):
    provider = "slack"
    base_url = "https://slack.com/api"

    def __init__(self, token: str, **kw: Any):
        super().__init__(**kw)
        self.token = token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json; charset=utf-8"}

    async def post(self, channel: str, text: str) -> str:
        d = await self.request("POST", "/chat.postMessage", json={"channel": channel, "text": text})
        if not d.get("ok"):
            from app.core.errors import IntegrationError

            raise IntegrationError("Slack error", details=d.get("error"))
        return d.get("ts", "")


class MockSlack:
    provider, mode = "slack", "mock"
    sent: list[dict[str, str]] = []

    async def post(self, channel: str, text: str) -> str:
        self.sent.append({"channel": channel, "text": text})
        return str(time.time())


class MixpanelClient(HttpAdapter):
    provider = "mixpanel"
    base_url = "https://api.mixpanel.com"
    max_retries = 1

    def __init__(self, token: str, **kw: Any):
        super().__init__(**kw)
        self.token = token

    async def track(self, event: str, distinct_id: str, props: dict[str, Any]) -> None:
        payload = [{"event": event, "properties": {"token": self.token, "distinct_id": distinct_id,
                                                    "time": int(time.time()), "$insert_id": uuid.uuid4().hex, **props}}]
        data = base64.b64encode(json.dumps(payload).encode()).decode()
        await self.request("POST", "/track", data={"data": data}, headers={"Accept": "text/plain"})


class NullMixpanel:
    provider, mode = "mixpanel", "disabled"
    events: list[dict[str, Any]] = []

    async def track(self, event: str, distinct_id: str, props: dict[str, Any]) -> None:
        self.events.append({"event": event, "distinct_id": distinct_id, **props})
