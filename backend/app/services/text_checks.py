"""Mechanical copy checks (no generation)."""
from __future__ import annotations

import re

COMMON_MISSPELLINGS = {
    "recieve": "receive", "seperate": "separate", "occured": "occurred", "definately": "definitely",
    "accomodate": "accommodate", "untill": "until", "wich": "which", "thier": "their", "teh": "the",
    "goverment": "government", "commitee": "committee", "donte": "donate", "neccessary": "necessary",
}


def proofread(text: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for m in re.finditer(r"\b(\w+)\s+\1\b", text, re.I):
        issues.append({"kind": "repeated_word", "excerpt": m.group(0), "suggestion": m.group(1)})
    for word in re.findall(r"[A-Za-z']+", text):
        fix = COMMON_MISSPELLINGS.get(word.lower())
        if fix:
            issues.append({"kind": "spelling", "excerpt": word, "suggestion": fix})
    if re.search(r" {2,}", text):
        issues.append({"kind": "spacing", "excerpt": "double space", "suggestion": "single space"})
    if re.search(r"\s+[,.!?]", text):
        issues.append({"kind": "punctuation", "excerpt": "space before punctuation", "suggestion": "remove space"})
    if re.search(r"click here", text, re.I):
        issues.append({"kind": "accessibility", "excerpt": "click here", "suggestion": "use descriptive link text"})
    if re.search(r"[A-Z]{12,}", text):
        issues.append({"kind": "accessibility", "excerpt": "long all-caps run", "suggestion": "use sentence case"})
    return issues
