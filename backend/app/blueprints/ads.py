"""Advertising creative management (Meta + Google Ads). Read-only Google Ads reporting; no activation/spend."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from quart import Blueprint
from sqlalchemy import select

from app.blueprints.common import load_scoped
from app.core.audit import audit
from app.core.auth import authenticated, ctx, get_client_checked
from app.core.db import session_scope
from app.core.errors import Conflict, ValidationFailed
from app.core.http import body, ok
from app.models import AdCreative, AdCreativeVersion
from app.services.integrations import registry
from app.services.text_checks import proofread

bp = Blueprint("ads", __name__)

# Published platform limits (characters).
LIMITS = {
    ("google_ads", "responsive_search"): {"headlines": 30, "descriptions": 90, "max_headlines": 15, "max_descriptions": 4},
    ("google_ads", "responsive_display"): {"headlines": 30, "descriptions": 90, "max_headlines": 5, "max_descriptions": 5},
    ("meta", "single_image"): {"headlines": 40, "descriptions": 30, "primary_text": 125, "max_headlines": 5, "max_descriptions": 5},
    ("meta", "video"): {"headlines": 40, "descriptions": 30, "primary_text": 125, "max_headlines": 5, "max_descriptions": 5},
}


def run_checks(c: AdCreative, brand_terms: list[str], banned_terms: list[str]) -> dict:
    lim = LIMITS.get((c.platform, c.format))
    checks = []
    if lim is None:
        checks.append({"check": "format", "passed": False, "detail": f"Unknown format {c.platform}/{c.format}"})
    else:
        over = [h for h in c.headlines if len(h) > lim["headlines"]] + [d for d in c.descriptions if len(d) > lim["descriptions"]]
        if "primary_text" in lim and len(c.primary_text) > lim["primary_text"]:
            over.append("primary_text")
        checks.append({"check": "character_limits", "passed": not over, "detail": ", ".join(o[:30] for o in over)})
        checks.append({"check": "asset_counts", "passed": 1 <= len(c.headlines) <= lim["max_headlines"]
                       and len(c.descriptions) <= lim["max_descriptions"], "detail": f"{len(c.headlines)} headlines"})
    text = " ".join([*c.headlines, *c.descriptions, c.primary_text])
    issues = proofread(text)
    checks.append({"check": "proofreading", "passed": not [i for i in issues if i["kind"] in ("spelling", "repeated_word")],
                   "detail": issues[:10]})
    if c.is_political:
        checks.append({"check": "paid_for_by_disclosure", "passed": "paid for by" in c.disclaimer.lower(),
                       "detail": "Political ads require a 'Paid for by' disclaimer"})
    hits = [t for t in banned_terms if t.lower() in text.lower()]
    checks.append({"check": "brand_banned_terms", "passed": not hits, "detail": ", ".join(hits)})
    if brand_terms:
        miss = [t for t in brand_terms if t not in text and t.lower() in text.lower()]
        checks.append({"check": "brand_capitalization", "passed": not miss, "detail": ", ".join(miss)})
    checks.append({"check": "asset_description", "passed": not c.asset_uri or bool(c.tags), "detail": "Visual assets need tags/alt description"})
    return {"passed": all(x["passed"] for x in checks), "checks": checks}


class CreativeIn(BaseModel):
    platform: Literal["meta", "google_ads"]
    format: str
    name: str = Field(min_length=2)
    campaign_id: str | None = None
    headlines: list[str] = Field(min_length=1)
    descriptions: list[str] = []
    primary_text: str = ""
    disclaimer: str = ""
    is_political: bool = False
    asset_uri: str | None = None
    tags: list[str] = []


class CreativePatch(BaseModel):
    name: str | None = None
    headlines: list[str] | None = None
    descriptions: list[str] | None = None
    primary_text: str | None = None
    disclaimer: str | None = None
    asset_uri: str | None = None
    tags: list[str] | None = None


async def _brand(client_id: str) -> tuple[list[str], list[str]]:
    from app.models import Client

    async with session_scope() as s:
        cl = await s.get(Client, client_id)
    st = cl.settings or {}
    return st.get("brand_terms", []), st.get("banned_terms", [])


@bp.get("/clients/<client_id>/ad-creatives")
@authenticated
async def list_creatives(client_id: str):
    await get_client_checked(client_id, "ads:read")
    async with session_scope() as s:
        return ok([r.to_dict() for r in (await s.execute(select(AdCreative).where(AdCreative.client_id == client_id)
                                                          .order_by(AdCreative.updated_at.desc()))).scalars()])


@bp.post("/clients/<client_id>/ad-creatives")
@authenticated
async def create_creative(client_id: str):
    c = await get_client_checked(client_id, "ads:write")
    data = await body(CreativeIn)
    bt, bn = await _brand(client_id)
    async with session_scope() as s:
        cr = AdCreative(organization_id=c.organization_id, client_id=client_id, **data.model_dump())
        cr.checks = run_checks(cr, bt, bn)
        s.add(cr)
        await s.flush()
        s.add(AdCreativeVersion(creative_id=cr.id, version=1, snapshot=data.model_dump(), changed_by=ctx().user.id))
        audit(s, action="ad_creative.create", target_type="ad_creative", target_id=cr.id, organization_id=c.organization_id,
              client_id=client_id, actor_user_id=ctx().user.id)
    return ok(cr.to_dict(), 201)


@bp.patch("/ad-creatives/<cr_id>")
@authenticated
async def patch_creative(cr_id: str):
    cr = await load_scoped(AdCreative, cr_id, "ads:write")
    if cr.status == "approved":
        raise Conflict("Approved creatives are locked; duplicate to revise")
    data = await body(CreativePatch)
    bt, bn = await _brand(cr.client_id)
    async with session_scope() as s:
        x = await s.get(AdCreative, cr_id)
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(x, k, v)
        x.version += 1
        x.status = "draft"
        x.checks = run_checks(x, bt, bn)
        s.add(AdCreativeVersion(creative_id=x.id, version=x.version, changed_by=ctx().user.id, snapshot={
            k: getattr(x, k) for k in ("name", "headlines", "descriptions", "primary_text", "disclaimer", "asset_uri", "tags")}))
    return ok(x.to_dict())


@bp.get("/ad-creatives/<cr_id>/versions")
@authenticated
async def versions(cr_id: str):
    await load_scoped(AdCreative, cr_id, "ads:read")
    async with session_scope() as s:
        return ok([v.to_dict() for v in (await s.execute(select(AdCreativeVersion).where(
            AdCreativeVersion.creative_id == cr_id).order_by(AdCreativeVersion.version.desc()))).scalars()])


@bp.post("/ad-creatives/<cr_id>/submit")
@authenticated
async def submit(cr_id: str):
    cr = await load_scoped(AdCreative, cr_id, "ads:write")
    if not cr.checks.get("passed"):
        raise ValidationFailed("Creative must pass checks before review", details=cr.checks)
    async with session_scope() as s:
        x = await s.get(AdCreative, cr_id)
        x.status = "in_review"
    return ok(x.to_dict())


class DecisionIn(BaseModel):
    approve: bool
    note: str = ""


@bp.post("/ad-creatives/<cr_id>/decision")
@authenticated
async def decide(cr_id: str):
    cr = await load_scoped(AdCreative, cr_id, "ads:read")
    perm_ok = ctx().has("ads:approve", cr.organization_id, cr.client_id) or (
        cr.is_political and ctx().has("compliance:approve", cr.organization_id, cr.client_id))
    if not perm_ok:
        from app.core.errors import Forbidden

        raise Forbidden("Missing permission ads:approve")
    if cr.status != "in_review":
        raise ValidationFailed("Creative is not in review")
    data = await body(DecisionIn)
    async with session_scope() as s:
        x = await s.get(AdCreative, cr_id)
        x.status = "approved" if data.approve else "rejected"
        audit(s, action=f"ad_creative.{x.status}", target_type="ad_creative", target_id=cr_id, organization_id=x.organization_id,
              client_id=x.client_id, actor_user_id=ctx().user.id, details={"note": data.note})
    return ok(x.to_dict())


@bp.get("/clients/<client_id>/google-ads/campaigns")
@authenticated
async def google_ads_campaigns(client_id: str):
    c = await get_client_checked(client_id, "ads:read")
    customer = (c.settings or {}).get("google_ads_customer_id")
    if not customer:
        raise ValidationFailed("Client has no google_ads_customer_id configured")
    ga = registry.get("google_ads")
    return ok({"mode": ga.mode, "campaigns": await ga.campaigns(customer)})
