"""SPF / DKIM / DMARC lookups via DNS (dnspython). Results are informational, not a compliance guarantee."""
from __future__ import annotations

from typing import Any

import dns.asyncresolver
import dns.exception
import dns.resolver


async def _txt(name: str) -> list[str]:
    try:
        ans = await dns.asyncresolver.resolve(name, "TXT", lifetime=5)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return []
    except dns.exception.Timeout:
        raise
    return [b"".join(r.strings).decode(errors="replace") for r in ans]


def evaluate(domain: str, spf: list[str], dmarc: list[str], dkim: dict[str, list[str]]) -> dict[str, Any]:
    spf_recs = [r for r in spf if r.lower().startswith("v=spf1")]
    dmarc_recs = [r for r in dmarc if r.lower().startswith("v=dmarc1")]
    out: dict[str, Any] = {"domain": domain}
    if len(spf_recs) == 1:
        rec = spf_recs[0]
        weak = rec.strip().endswith("+all") or rec.strip().endswith("?all")
        out["spf"] = {"status": "warn" if weak else "pass", "record": rec,
                      "detail": "Permissive 'all' mechanism" if weak else ""}
    else:
        out["spf"] = {"status": "fail", "record": None,
                      "detail": "Multiple SPF records" if spf_recs else "No SPF record"}
    if dmarc_recs:
        rec = dmarc_recs[0]
        tags = dict(t.strip().split("=", 1) for t in rec.split(";") if "=" in t)
        policy = tags.get("p", "none").lower()
        out["dmarc"] = {"status": "pass" if policy in ("quarantine", "reject") else "warn", "record": rec,
                        "policy": policy, "detail": "" if policy != "none" else "p=none only monitors"}
    else:
        out["dmarc"] = {"status": "fail", "record": None, "detail": "No DMARC record at _dmarc"}
    found = {sel: recs for sel, recs in dkim.items() if any("p=" in r for r in recs)}
    if not dkim:
        out["dkim"] = {"status": "unknown", "detail": "No DKIM selectors configured"}
    else:
        out["dkim"] = {"status": "pass" if found else "fail", "selectors_found": list(found),
                       "detail": "" if found else "No DKIM key at configured selectors"}
    statuses = [out[k]["status"] for k in ("spf", "dkim", "dmarc")]
    out["overall"] = "fail" if "fail" in statuses else ("warn" if "warn" in statuses or "unknown" in statuses else "pass")
    return out


async def check_domain(domain: str, selectors: list[str]) -> dict[str, Any]:
    spf = await _txt(domain)
    dmarc = await _txt(f"_dmarc.{domain}")
    dkim = {sel: await _txt(f"{sel}._domainkey.{domain}") for sel in selectors}
    return evaluate(domain, spf, dmarc, dkim)
