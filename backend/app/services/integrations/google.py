"""Google Workspace (Docs, Drive, Sheets) and Google Ads REST adapters using OAuth2 user tokens.

Scopes are requested per feature (least privilege):
  docs:   https://www.googleapis.com/auth/documents   (create/read docs the user selects)
  drive:  https://www.googleapis.com/auth/drive.file  (only files the app created or the user opened)
  sheets: https://www.googleapis.com/auth/spreadsheets
  ads:    https://www.googleapis.com/auth/adwords
Google Ads calls additionally need a developer-token header and, for manager access, login-customer-id.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

from app.services.integrations.base import HttpAdapter

SCOPES = {
    "google_docs": ["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive.file"],
    "google_sheets": ["https://www.googleapis.com/auth/spreadsheets"],
    "google_ads": ["https://www.googleapis.com/auth/adwords"],
}
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def authorization_url(provider: str, client_id: str, redirect_uri: str, state: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES[provider]), "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "state": state,
    })


class GoogleWorkspaceClient(HttpAdapter):
    provider = "google_workspace"

    def __init__(self, access_token: str, **kw: Any):
        super().__init__(**kw)
        self.token = access_token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def get_document(self, doc_id: str) -> dict[str, Any]:
        return await self.request("GET", f"https://docs.googleapis.com/v1/documents/{doc_id}")

    async def create_document(self, title: str, text: str) -> str:
        doc = await self.request("POST", "https://docs.googleapis.com/v1/documents", json={"title": title})
        await self.request("POST", f"https://docs.googleapis.com/v1/documents/{doc['documentId']}:batchUpdate",
                           json={"requests": [{"insertText": {"location": {"index": 1}, "text": text}}]})
        return doc["documentId"]

    async def list_files(self, folder_id: str | None = None) -> list[dict[str, Any]]:
        q = f"'{folder_id}' in parents and trashed = false" if folder_id else "trashed = false"
        d = await self.request("GET", "https://www.googleapis.com/drive/v3/files",
                               params={"q": q, "fields": "files(id,name,mimeType,modifiedTime)", "pageSize": 100})
        return d.get("files", [])

    async def read_sheet(self, spreadsheet_id: str, a1_range: str) -> list[list[str]]:
        d = await self.request("GET", f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{a1_range}")
        return d.get("values", [])

    async def write_sheet(self, spreadsheet_id: str, a1_range: str, rows: list[list[Any]]) -> None:
        await self.request("PUT", f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{a1_range}",
                           params={"valueInputOption": "RAW"}, json={"values": rows})


class MockGoogleWorkspace:
    """Development substitute holding docs in memory; seeded with a synthetic approved draft."""

    provider, mode = "google_workspace", "mock"
    docs: dict[str, dict[str, Any]] = {
        "mock-doc-spring-update": {
            "documentId": "mock-doc-spring-update", "title": "Spring Volunteer Update (approved)",
            "body": {"content": [
                {"paragraph": {"paragraphStyle": {"namedStyleType": "HEADING_1"},
                               "elements": [{"textRun": {"content": "Spring volunteer update\n"}}]}},
                {"paragraph": {"elements": [{"textRun": {"content": "Thanks to 120 volunteers, the community garden opened on schedule. "}},
                                             {"textRun": {"content": "See the photos", "textStyle": {"link": {"url": "https://example.org/garden"}}}},
                                             {"textRun": {"content": ".\n"}}]}},
                {"paragraph": {"bullet": {}, "elements": [{"textRun": {"content": "Saturday cleanup, 9am\n", "textStyle": {"bold": True}}}]}},
                {"paragraph": {"bullet": {}, "elements": [{"textRun": {"content": "Seed swap, April 20\n"}}]}},
            ]},
        }
    }

    async def get_document(self, doc_id: str) -> dict[str, Any]:
        from app.core.errors import NotFound

        if doc_id not in self.docs:
            raise NotFound("Document not found")
        return self.docs[doc_id]

    async def create_document(self, title: str, text: str) -> str:
        did = f"mock-doc-{len(self.docs) + 1}"
        self.docs[did] = {"documentId": did, "title": title, "body": {"content": [
            {"paragraph": {"elements": [{"textRun": {"content": line + "\n"}}]}} for line in text.splitlines()]}}
        return did

    async def list_files(self, folder_id: str | None = None) -> list[dict[str, Any]]:
        return [{"id": k, "name": v["title"], "mimeType": "application/vnd.google-apps.document"} for k, v in self.docs.items()]

    async def read_sheet(self, spreadsheet_id: str, a1_range: str) -> list[list[str]]:
        return [["email", "first_name"], ["sam@example.org", "Sam"]]

    async def write_sheet(self, spreadsheet_id: str, a1_range: str, rows: list[list[Any]]) -> None:
        return None


class GoogleAdsClient(HttpAdapter):
    """Google Ads REST (https://developers.google.com/google-ads/api/rest/overview). Read operations only;
    mutations are deliberately not implemented here — activation/spend happens in Google Ads by a human."""

    provider = "google_ads"

    def __init__(self, access_token: str, developer_token: str, login_customer_id: str | None = None, **kw: Any):
        super().__init__(**kw)
        version = os.environ.get("GOOGLE_ADS_API_VERSION", "v21")
        self.base_url = f"https://googleads.googleapis.com/{version}"
        self.token, self.dev, self.login = access_token, developer_token, login_customer_id

    def headers(self) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.token}", "developer-token": self.dev}
        if self.login:
            h["login-customer-id"] = self.login
        return h

    async def accessible_customers(self) -> list[str]:
        d = await self.request("GET", "/customers:listAccessibleCustomers")
        return d.get("resourceNames", [])

    async def campaigns(self, customer_id: str) -> list[dict[str, Any]]:
        q = ("SELECT campaign.id, campaign.name, campaign.status, metrics.impressions, metrics.clicks, "
             "metrics.cost_micros FROM campaign WHERE segments.date DURING LAST_30_DAYS")
        d = await self.request("POST", f"/customers/{customer_id}/googleAds:search", json={"query": q})
        return [{"id": r["campaign"]["id"], "name": r["campaign"]["name"], "status": r["campaign"]["status"],
                 "impressions": int(r.get("metrics", {}).get("impressions", 0)),
                 "clicks": int(r.get("metrics", {}).get("clicks", 0)),
                 "cost": int(r.get("metrics", {}).get("costMicros", 0)) / 1e6} for r in d.get("results", [])]


class MockGoogleAds:
    provider, mode = "google_ads", "mock"

    async def accessible_customers(self) -> list[str]:
        return ["customers/1234567890"]

    async def campaigns(self, customer_id: str) -> list[dict[str, Any]]:
        return [{"id": "111", "name": "Spring Awareness (synthetic)", "status": "PAUSED", "impressions": 0, "clicks": 0, "cost": 0.0}]
