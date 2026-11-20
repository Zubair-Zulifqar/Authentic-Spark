"""CSV parsing, column mapping, validation, de-duplication and suppression matching."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 200_000
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
FIELDS = ("email", "phone", "first_name", "last_name", "postal_code", "sms_consent")
SYNONYMS = {
    "email": ["email", "e-mail", "email_address", "emailaddress"],
    "phone": ["phone", "mobile", "cell", "phone_number", "mobile_phone"],
    "first_name": ["first_name", "firstname", "first", "fname", "given_name"],
    "last_name": ["last_name", "lastname", "last", "lname", "surname"],
    "postal_code": ["zip", "zipcode", "zip_code", "postal_code", "postcode"],
    "sms_consent": ["sms_consent", "sms_opt_in", "text_opt_in"],
}


class CsvError(ValueError):
    pass


def decode_csv(data: bytes, filename: str) -> tuple[list[str], list[dict[str, str]]]:
    if not filename.lower().endswith(".csv"):
        raise CsvError("Only .csv files are accepted")
    if len(data) > MAX_BYTES:
        raise CsvError("File exceeds 20MB limit")
    if b"\x00" in data[:4096]:
        raise CsvError("File appears to be binary, not CSV")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CsvError("CSV has no header row")
    rows = []
    for i, row in enumerate(reader):
        if i >= MAX_ROWS:
            raise CsvError(f"CSV exceeds {MAX_ROWS} rows")
        rows.append({k: (v or "").strip() for k, v in row.items() if k is not None})
    return [h.strip() for h in reader.fieldnames], rows


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    norm = {re.sub(r"[\s-]+", "_", h.strip().lower()): h for h in headers}
    out: dict[str, str] = {}
    for f, syns in SYNONYMS.items():
        for s in syns:
            if s in norm:
                out[f] = norm[s]
                break
    return out


def normalize_email(e: str) -> str:
    return e.strip().lower()


def normalize_phone(p: str) -> str | None:
    digits = re.sub(r"\D", "", p)
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return None


TRUTHY = {"1", "y", "yes", "true", "t", "opt_in", "opted_in"}


@dataclass
class ProcessResult:
    contacts: list[dict[str, Any]] = field(default_factory=list)
    issues: list[tuple[int, str]] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def process_rows(rows: list[dict[str, str]], mapping: dict[str, str], *,
                 suppressed_emails: set[str], suppressed_phones: set[str]) -> ProcessResult:
    if "email" not in mapping and "phone" not in mapping:
        raise CsvError("Mapping must include an email or phone column")
    res = ProcessResult()
    seen_e: set[str] = set()
    seen_p: set[str] = set()
    st = dict(total=len(rows), accepted=0, invalid=0, duplicates=0, suppressed=0)
    for idx, row in enumerate(rows, start=2):  # row 1 is header
        get = lambda f, row=row: row.get(mapping[f], "") if f in mapping else ""  # noqa: E731
        raw_email, raw_phone = get("email"), get("phone")
        email = normalize_email(raw_email) if raw_email else None
        phone = normalize_phone(raw_phone) if raw_phone else None
        if email and not EMAIL_RE.match(email):
            res.issues.append((idx, f"invalid email: {raw_email[:60]}"))
            st["invalid"] += 1
            continue
        if raw_phone and not phone:
            res.issues.append((idx, "invalid phone number"))
            if not email:
                st["invalid"] += 1
                continue
        if not email and not phone:
            res.issues.append((idx, "no email or phone"))
            st["invalid"] += 1
            continue
        if (email and email in seen_e) or (phone and not email and phone in seen_p):
            res.issues.append((idx, "duplicate within file"))
            st["duplicates"] += 1
            continue
        status = "pending"
        if (email and email in suppressed_emails) or (phone and phone in suppressed_phones):
            status = "suppressed"
            st["suppressed"] += 1
        if email:
            seen_e.add(email)
        if phone:
            seen_p.add(phone)
        res.contacts.append({
            "email": email, "email_normalized": email, "phone": phone,
            "first_name": get("first_name")[:120], "last_name": get("last_name")[:120],
            "postal_code": get("postal_code")[:20],
            "sms_consent": get("sms_consent").lower() in TRUTHY, "status": status, "source_row": idx,
        })
        st["accepted"] += 1
    res.stats = st
    return res
