"""Google Doc -> email-safe HTML conversion and pre-send validation."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

TEMPLATES = {
    "standard": {"width": 600, "font": "Arial, Helvetica, sans-serif", "accent": "#1f4fd1"},
    "minimal": {"width": 560, "font": "Georgia, serif", "accent": "#222222"},
}


def blocks_from_google_doc(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a Google Docs API `documents.get` body into simple blocks.
    Handles paragraphs, HEADING_1..3 named styles, bullets, bold/italic runs and links."""
    blocks: list[dict[str, Any]] = []
    for el in doc.get("body", {}).get("content", []):
        para = el.get("paragraph")
        if not para:
            continue
        runs = []
        for pe in para.get("elements", []):
            tr = pe.get("textRun")
            if not tr:
                continue
            style = tr.get("textStyle", {})
            runs.append({
                "text": tr.get("content", "").replace("\n", ""),
                "bold": bool(style.get("bold")), "italic": bool(style.get("italic")),
                "link": (style.get("link") or {}).get("url"),
            })
        if not any(r["text"].strip() for r in runs):
            continue
        named = para.get("paragraphStyle", {}).get("namedStyleType", "NORMAL_TEXT")
        kind = {"HEADING_1": "h1", "TITLE": "h1", "HEADING_2": "h2", "HEADING_3": "h3"}.get(named, "p")
        if para.get("bullet"):
            kind = "li"
        blocks.append({"type": kind, "runs": runs})
    return blocks


_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+|\{\{[a-z_]+\}\})\)")


def blocks_from_text(text: str) -> list[dict[str, Any]]:
    """Plain text / light markdown (#, ##, -, **bold**, [text](url)) -> blocks."""
    blocks: list[dict[str, Any]] = []
    for raw in re.split(r"\n\s*\n|\n(?=[-*#] )", text.strip()):
        line = raw.strip()
        if not line:
            continue
        kind = "p"
        if line.startswith("### "):
            kind, line = "h3", line[4:]
        elif line.startswith("## "):
            kind, line = "h2", line[3:]
        elif line.startswith("# "):
            kind, line = "h1", line[2:]
        elif line[:2] in ("- ", "* "):
            kind, line = "li", line[2:]
        runs: list[dict[str, Any]] = []
        pos = 0
        for m in _LINK.finditer(line):
            runs += _bold_runs(line[pos:m.start()])
            runs.append({"text": m.group(1), "bold": False, "italic": False, "link": m.group(2)})
            pos = m.end()
        runs += _bold_runs(line[pos:])
        blocks.append({"type": kind, "runs": runs})
    return blocks


def _bold_runs(s: str) -> list[dict[str, Any]]:
    out = []
    for i, part in enumerate(re.split(r"\*\*", s)):
        if part:
            out.append({"text": part, "bold": i % 2 == 1, "italic": False, "link": None})
    return out


def _render_runs(runs: list[dict[str, Any]], accent: str) -> str:
    parts = []
    for r in runs:
        t = html.escape(r["text"])
        if r.get("bold"):
            t = f"<strong>{t}</strong>"
        if r.get("italic"):
            t = f"<em>{t}</em>"
        if r.get("link"):
            t = f'<a href="{html.escape(r["link"], quote=True)}" style="color:{accent};text-decoration:underline;">{t}</a>'
        parts.append(t)
    return "".join(parts)


def render_html(blocks: list[dict[str, Any]], *, subject: str, preheader: str, sender_name: str,
                sender_address: str, template: str = "standard") -> str:
    t = TEMPLATES.get(template, TEMPLATES["standard"])
    font, accent, width = t["font"], t["accent"], t["width"]
    body: list[str] = []
    in_list = False
    sizes = {"h1": 26, "h2": 21, "h3": 18}
    for b in blocks:
        if b["type"] == "li" and not in_list:
            body.append('<ul style="margin:0 0 16px 20px;padding:0;">')
            in_list = True
        if b["type"] != "li" and in_list:
            body.append("</ul>")
            in_list = False
        inner = _render_runs(b["runs"], accent)
        if b["type"] in sizes:
            body.append(f'<{b["type"]} style="font-family:{font};font-size:{sizes[b["type"]]}px;line-height:1.3;margin:0 0 12px;">{inner}</{b["type"]}>')
        elif b["type"] == "li":
            body.append(f'<li style="font-family:{font};font-size:16px;line-height:1.5;margin:0 0 6px;">{inner}</li>')
        else:
            body.append(f'<p style="font-family:{font};font-size:16px;line-height:1.5;margin:0 0 16px;">{inner}</p>')
    if in_list:
        body.append("</ul>")
    content = "\n".join(body)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(subject)}</title>
<style>@media only screen and (max-width:620px){{.container{{width:100% !important;}}}}</style>
</head>
<body style="margin:0;padding:0;background:#f4f5f7;">
<div style="display:none;max-height:0;overflow:hidden;">{html.escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f4f5f7;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" class="container" width="{width}" cellpadding="0" cellspacing="0" border="0" style="width:{width}px;max-width:100%;background:#ffffff;">
<tr><td style="padding:32px 28px;color:#1b1d21;">
{content}
</td></tr>
<tr><td style="padding:20px 28px;border-top:1px solid #e3e5e8;font-family:{font};font-size:12px;color:#5f6670;">
Sent by {html.escape(sender_name)} &lt;{html.escape(sender_address)}&gt;.<br>
<a href="{{{{unsubscribe_url}}}}" style="color:#5f6670;">Unsubscribe</a> &middot; {{{{mailing_address}}}}
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


class _Collector(HTMLParser):
    VOID = {"meta", "br", "img", "hr", "link", "input", "col", "area", "base", "source", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.images: list[dict[str, str | None]] = []
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.has_viewport = False
        self._link_text: list[str] | None = None
        self._href = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self._href, self._link_text = a.get("href") or "", []
        if tag == "img":
            self.images.append({"src": a.get("src"), "alt": a.get("alt")})
        if tag == "meta" and a.get("name") == "viewport":
            self.has_viewport = True
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag == "a" and self._link_text is not None:
            self.links.append((self._href, "".join(self._link_text).strip()))
            self._link_text = None
        if tag in self.VOID:
            return
        if tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.errors.append(f"unclosed <{self.stack.pop()}>")
            self.stack.pop()
        else:
            self.errors.append(f"stray </{tag}>")

    def handle_data(self, data):
        if self._link_text is not None:
            self._link_text.append(data)


MERGE_TAG = re.compile(r"^\{\{[a-z_]+\}\}$")


def validate_html(doc_html: str, *, subject: str, sender_address: str) -> dict[str, Any]:
    c = _Collector()
    c.feed(doc_html)
    c.close()
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str = "", severity: str = "error") -> None:
        checks.append({"check": name, "passed": passed, "detail": detail, "severity": severity})

    structural = c.errors + [f"unclosed <{t}>" for t in c.stack]
    add("html_structure", not structural, "; ".join(structural[:5]))
    bad_links = []
    for href, _ in c.links:
        if MERGE_TAG.match(href):
            continue
        p = urlparse(href)
        if p.scheme not in ("https", "mailto") or (p.scheme == "https" and not p.netloc):
            bad_links.append(href or "(empty)")
    add("links", not bad_links, ", ".join(bad_links[:5]) or f"{len(c.links)} links ok")
    vague = [t for _, t in c.links if t.lower() in ("click here", "here", "link")]
    add("link_text_accessibility", not vague, ", ".join(vague), severity="warning")
    missing_alt = [i["src"] for i in c.images if not (i.get("alt") or "").strip()]
    insecure = [i["src"] for i in c.images if not str(i.get("src") or "").startswith("https://")]
    add("image_alt_text", not missing_alt, ", ".join(map(str, missing_alt[:5])))
    add("image_https", not insecure, ", ".join(map(str, insecure[:5])))
    add("unsubscribe_link", any("unsubscribe" in (h + t).lower() for h, t in c.links), "Unsubscribe link required")
    add("mailing_address", "{{mailing_address}}" in doc_html or "mailing_address" in doc_html, "Physical address merge tag")
    add("sender_info", bool(re.match(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", sender_address or "", re.I)), sender_address)
    add("subject_present", bool(subject.strip()), "")
    add("subject_length", len(subject) <= 90, f"{len(subject)} chars", severity="warning")
    add("mobile_viewport", c.has_viewport, "meta viewport")
    widths = [int(w) for w in re.findall(r'width="(\d+)"', doc_html)]
    add("mobile_width", all(w <= 640 for w in widths), f"max table width {max(widths) if widths else 0}px")
    size_kb = len(doc_html.encode()) / 1024
    add("size_under_102kb", size_kb < 102, f"{size_kb:.1f} KB (Gmail clips above ~102KB)", severity="warning")
    passed = all(ch["passed"] for ch in checks if ch["severity"] == "error")
    return {"passed": passed, "checks": checks}
