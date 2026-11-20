"""CRM adapters: NGP VAN, Action Network, ActionKit.

NGP VAN: https://docs.ngpvan.com/ — HTTP Basic auth with username = application name and
password = "<apiKey>|<dbMode>" (0 = VoterFile, 1 = MyCampaign). Used endpoints: GET /v4/echoes/{msg}
(auth check), POST /v4/bulkImportJobs and GET /v4/bulkImportJobs/{jobId}. Bulk import requires a file
reachable by URL (we hand off a signed Cloud Storage URL) and a resource/mapping configured with VAN.

Action Network: https://actionnetwork.org/docs — OSDI-API-Token header, POST /api/v2/people.
ActionKit: https://docs.actionkit.com/ — instance-specific REST at https://<instance>/rest/v1/.

Email *content* handoff to these platforms is via authorized API where documented (Action Network
messages are created as drafts; sends remain a manual human action in the platform UI).
"""
from __future__ import annotations

import base64
import uuid
from typing import Any

from app.services.integrations.base import HttpAdapter


class NgpVanClient(HttpAdapter):
    provider = "ngpvan"
    base_url = "https://api.securevan.com/v4"

    def __init__(self, app_name: str, api_key: str, db_mode: int = 1, **kw: Any):
        super().__init__(**kw)
        token = base64.b64encode(f"{app_name}:{api_key}|{db_mode}".encode()).decode()
        self._auth = f"Basic {token}"

    def headers(self) -> dict[str, str]:
        return {"Authorization": self._auth, "Content-Type": "application/json"}

    async def check_auth(self) -> bool:
        await self.request("POST", "/echoes", json={"message": "authentic-spark"})
        return True

    async def create_bulk_import(self, *, file_url: str, file_name: str, columns: list[str],
                                 resource_type: str = "Contacts", mapping_types: list[dict] | None = None) -> str:
        payload = {
            "file": {"fileName": file_name, "hasHeader": True, "sourceUrl": file_url,
                     "columnDelimiter": "Csv", "columns": [{"name": c} for c in columns]},
            "description": "Authentic Spark import",
            "actions": [{"resultFileSizeKbLimit": 5000, "resourceType": resource_type,
                         "actionType": "loadMappedFile", "mappingTypes": mapping_types or []}],
        }
        data = await self.request("POST", "/bulkImportJobs", json=payload)
        return str(data.get("jobId"))

    async def import_status(self, job_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/bulkImportJobs/{job_id}")


class MockNgpVan:
    provider, mode = "ngpvan", "mock"
    jobs: dict[str, dict[str, Any]] = {}

    async def check_auth(self) -> bool:
        return True

    async def create_bulk_import(self, *, file_url: str, file_name: str, columns: list[str], **_: Any) -> str:
        jid = str(uuid.uuid4().int % 10**8)
        self.jobs[jid] = {"id": jid, "status": "Completed", "resultFiles": [], "errors": []}
        return jid

    async def import_status(self, job_id: str) -> dict[str, Any]:
        return self.jobs.get(job_id, {"id": job_id, "status": "Unknown"})


class ActionNetworkClient(HttpAdapter):
    provider = "action_network"
    base_url = "https://actionnetwork.org/api/v2"

    def __init__(self, api_token: str, **kw: Any):
        super().__init__(**kw)
        self.token = api_token

    def headers(self) -> dict[str, str]:
        return {"OSDI-API-Token": self.token, "Content-Type": "application/json"}

    async def create_message_draft(self, *, subject: str, body_html: str, from_name: str, reply_to: str) -> str:
        data = await self.request("POST", "/messages", json={
            "subject": subject, "body": body_html, "from": from_name, "reply_to": reply_to})
        return data.get("identifiers", ["unknown"])[0]


class ActionKitClient(HttpAdapter):
    provider = "actionkit"

    def __init__(self, instance: str, username: str, password: str, **kw: Any):
        super().__init__(**kw)
        self.base_url = f"https://{instance}/rest/v1"
        self._auth = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()

    def headers(self) -> dict[str, str]:
        return {"Authorization": self._auth, "Content-Type": "application/json"}

    async def create_mailing_draft(self, *, subject: str, html: str, from_line: str) -> str:
        await self.request("POST", "/mailer/", json={"subjects": [{"text": subject}], "html": html, "fromline": from_line})
        return "created"


class MockEmailPlatform:
    """Development substitute for Action Network / ActionKit draft creation. Never sends."""

    mode = "mock"

    def __init__(self, provider: str):
        self.provider = provider

    async def create_message_draft(self, **_: Any) -> str:
        return f"mock-{self.provider}-{uuid.uuid4().hex[:10]}"

    create_mailing_draft = create_message_draft
