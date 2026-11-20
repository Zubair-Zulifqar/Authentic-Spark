"""Chooses live vs mock adapters. A live adapter is used only when its credentials are configured;
otherwise the explicitly-labelled mock (mode="mock") is returned and the UI shows a MOCK badge."""
from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.services.integrations import crm, google, productivity, sms, zerobounce

_overrides: dict[str, Any] = {}
_singletons: dict[str, Any] = {}


def override(name: str, adapter: Any) -> None:
    _overrides[name] = adapter


def reset() -> None:
    _overrides.clear()
    _singletons.clear()


def _single(name: str, factory: Any) -> Any:
    if name not in _singletons:
        _singletons[name] = factory()
    return _singletons[name]


def get(name: str) -> Any:
    if name in _overrides:
        return _overrides[name]
    s = get_settings()
    if name == "zerobounce":
        return zerobounce.ZeroBounceClient(s.zerobounce_api_key) if s.zerobounce_api_key else _single(name, zerobounce.MockZeroBounce)
    if name == "ngpvan":
        return crm.NgpVanClient(s.ngpvan_app_name, s.ngpvan_api_key) if (s.ngpvan_api_key and s.ngpvan_app_name) else _single(name, crm.MockNgpVan)
    if name == "asana":
        return productivity.AsanaClient(s.asana_token) if s.asana_token else _single(name, productivity.MockAsana)
    if name == "slack":
        return productivity.SlackClient(s.slack_bot_token) if s.slack_bot_token else _single(name, productivity.MockSlack)
    if name == "mixpanel":
        return productivity.MixpanelClient(s.mixpanel_token) if s.mixpanel_token else _single(name, productivity.NullMixpanel)
    if name == "scale_to_win":
        return _single(name, sms.MockScaleToWin)
    # Per-user OAuth providers (Google, QuickBooks) need stored tokens; until the OAuth flow has completed
    # for a tenant the mocks are used.
    if name == "google_workspace":
        return _single(name, google.MockGoogleWorkspace)
    if name == "google_ads":
        return _single(name, google.MockGoogleAds)
    if name == "quickbooks":
        from app.services.integrations import quickbooks

        return _single(name, quickbooks.MockQuickBooks)
    if name in ("action_network", "actionkit"):
        return _single(name, lambda: crm.MockEmailPlatform(name))
    raise KeyError(name)


PROVIDERS = ["google_workspace", "google_ads", "ngpvan", "action_network", "actionkit", "scale_to_win",
             "zerobounce", "quickbooks", "asana", "slack", "mixpanel", "zapier"]


def mode(name: str) -> str:
    if name == "zapier":
        return "live"  # first-party signed webhooks; no credentials needed
    return getattr(get(name), "mode", "live")
