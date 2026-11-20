"""Contact-list acquisition ("List Buys"): upload, map, import, verify, CRM handoff."""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field
from quart import Blueprint, request
from sqlalchemy import func, select

from app.blueprints.common import load_scoped
from app.core.audit import audit
from app.core.auth import authenticated, ctx, get_client_checked
from app.core.db import session_scope
from app.core.errors import ValidationFailed
from app.core.http import ok, page_args
from app.jobs.runner import enqueue
from app.models import Contact, ContactList, ImportIssue
from app.services import events
from app.services.contacts import FIELDS, CsvError, decode_csv, process_rows, suggest_mapping
from app.services.integrations import registry
from app.services.suppression import suppressed_values

bp = Blueprint("contacts", __name__)

PERMISSIONS = ("opt_in", "vendor_attested_opt_in", "transactional")


@bp.get("/clients/<client_id>/contact-lists")
@authenticated
async def list_lists(client_id: str):
    await get_client_checked(client_id, "contacts:read")
    async with session_scope() as s:
        rows = (await s.execute(select(ContactList).where(ContactList.client_id == client_id)
                                .order_by(ContactList.created_at.desc()))).scalars()
        return ok([r.to_dict() for r in rows])


@bp.post("/clients/<client_id>/contact-lists/preview")
@authenticated
async def preview(client_id: str):
    await get_client_checked(client_id, "contacts:write")
    f = (await request.files).get("file")
    if f is None:
        raise ValidationFailed("file is required (multipart/form-data)")
    try:
        headers, rows = decode_csv(f.read(), f.filename or "")
    except CsvError as e:
        raise ValidationFailed(str(e)) from e
    return ok({"headers": headers, "row_count": len(rows), "sample": rows[:5], "suggested_mapping": suggest_mapping(headers),
               "fields": list(FIELDS)})


@bp.post("/clients/<client_id>/contact-lists")
@authenticated
async def import_list(client_id: str):
    """multipart: file, name, source_vendor, usage_permission, consent_evidence, mapping (json), follow_up_date"""
    import json

    c = await get_client_checked(client_id, "contacts:write")
    form = await request.form
    f = (await request.files).get("file")
    if f is None:
        raise ValidationFailed("file is required")
    name, vendor = form.get("name", "").strip(), form.get("source_vendor", "").strip()
    permission, evidence = form.get("usage_permission", ""), form.get("consent_evidence", "").strip()
    if not name or not vendor:
        raise ValidationFailed("name and source_vendor are required (auditable source)")
    if permission not in PERMISSIONS:
        raise ValidationFailed(f"usage_permission must be one of {PERMISSIONS}")
    if permission != "transactional" and len(evidence) < 10:
        raise ValidationFailed("consent_evidence describing how opt-in was obtained is required")
    try:
        headers, rows = decode_csv(f.read(), f.filename or "")
        mapping = json.loads(form.get("mapping") or "null") or suggest_mapping(headers)
        if set(mapping.values()) - set(headers):
            raise ValidationFailed("mapping references unknown columns")
        async with session_scope() as s:
            sup_e = await suppressed_values(s, c.organization_id, client_id, "email")
            sup_p = await suppressed_values(s, c.organization_id, client_id, "sms")
        result = process_rows(rows, mapping, suppressed_emails=sup_e, suppressed_phones=sup_p)
    except CsvError as e:
        raise ValidationFailed(str(e)) from e
    fud = form.get("follow_up_date")
    async with session_scope() as s:
        # Cross-list duplicates within the same client.
        existing = set((await s.execute(select(Contact.email_normalized).where(
            Contact.client_id == client_id, Contact.email_normalized.is_not(None)))).scalars())
        cross = 0
        cl = ContactList(organization_id=c.organization_id, client_id=client_id, name=name, source_vendor=vendor,
                         usage_permission=permission, consent_evidence=evidence, filename=f.filename or "",
                         column_mapping=mapping, status="imported",
                         follow_up_date=date.fromisoformat(fud) if fud else None)
        s.add(cl)
        await s.flush()
        for ct in result.contacts:
            if ct["email_normalized"] and ct["email_normalized"] in existing:
                cross += 1
                s.add(ImportIssue(list_id=cl.id, row_number=ct["source_row"], reason="already exists in another list for this client"))
                continue
            s.add(Contact(organization_id=c.organization_id, client_id=client_id, list_id=cl.id, **ct))
        for row_no, reason in result.issues[:5000]:
            s.add(ImportIssue(list_id=cl.id, row_number=row_no, reason=reason))
        cl.stats = {**result.stats, "cross_list_duplicates": cross, "accepted": result.stats["accepted"] - cross}
        audit(s, action="contact_list.import", target_type="contact_list", target_id=cl.id,
              organization_id=c.organization_id, client_id=client_id, actor_user_id=ctx().user.id,
              details={"vendor": vendor, "permission": permission, **cl.stats})
    await events.emit("contact_list.uploaded", organization_id=c.organization_id, client_id=client_id,
                      data={"list_id": cl.id, **cl.stats}, actor_user_id=ctx().user.id)
    return ok(cl.to_dict(), 201)


@bp.get("/contact-lists/<list_id>")
@authenticated
async def get_list(list_id: str):
    cl = await load_scoped(ContactList, list_id, "contacts:read")
    limit, offset = page_args()
    status = request.args.get("status")
    async with session_scope() as s:
        q = select(Contact).where(Contact.list_id == list_id)
        if status:
            q = q.where(Contact.status == status)
        contacts = (await s.execute(q.order_by(Contact.source_row).limit(limit).offset(offset))).scalars().all()
        issues = (await s.execute(select(ImportIssue).where(ImportIssue.list_id == list_id).order_by(ImportIssue.row_number).limit(200))).scalars().all()
        by_status = dict((await s.execute(select(Contact.status, func.count()).where(Contact.list_id == list_id).group_by(Contact.status))).all())
    return ok({**cl.to_dict(), "contacts": [x.to_dict() for x in contacts], "issues": [i.to_dict() for i in issues],
               "status_counts": by_status})


@bp.post("/contact-lists/<list_id>/verify")
@authenticated
async def verify(list_id: str):
    cl = await load_scoped(ContactList, list_id, "contacts:write")
    job = await enqueue("verify_contact_list", payload={"list_id": list_id}, idempotency_key=f"verify:{list_id}",
                        organization_id=cl.organization_id, client_id=cl.client_id, workflow_id="list_validation")
    async with session_scope() as s:
        x = await s.get(ContactList, list_id)
        if x.status == "imported":
            x.status = "verifying"
    return ok({"job_id": job.id, "status": job.status}, 202)


@bp.get("/contact-lists/<list_id>/export.csv")
@authenticated
async def export_csv(list_id: str):
    """CRM upload file: only valid (verified, non-suppressed) contacts."""
    await load_scoped(ContactList, list_id, "contacts:write")
    async with session_scope() as s:
        rows = (await s.execute(select(Contact).where(Contact.list_id == list_id, Contact.status == "valid"))).scalars().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Email", "FirstName", "LastName", "Phone", "PostalCode"])
    for r in rows:
        w.writerow([r.email or "", r.first_name, r.last_name, r.phone or "", r.postal_code])
    return buf.getvalue(), 200, {"Content-Type": "text/csv", "Content-Disposition": f'attachment; filename="list-{list_id[:8]}.csv"'}


class CrmIn(BaseModel):
    target: Literal["ngpvan"] = "ngpvan"
    file_url: str = Field(min_length=8, description="Signed URL of the exported CSV (e.g. Cloud Storage V4 signed URL)")


@bp.post("/contact-lists/<list_id>/crm-import")
@authenticated
async def crm_import(list_id: str):
    from app.core.http import body

    cl = await load_scoped(ContactList, list_id, "contacts:write")
    if cl.status != "verified":
        raise ValidationFailed("List must be verified before CRM import")
    if cl.usage_permission == "transactional":
        raise ValidationFailed("Transactional-only lists cannot be imported for marketing")
    data = await body(CrmIn)
    van = registry.get("ngpvan")
    job_id = await van.create_bulk_import(file_url=data.file_url, file_name=f"list-{list_id[:8]}.csv",
                                          columns=["Email", "FirstName", "LastName", "Phone", "PostalCode"])
    async with session_scope() as s:
        x = await s.get(ContactList, list_id)
        x.crm_import_status = "submitted"
        x.stats = {**x.stats, "ngpvan_job_id": job_id}
        audit(s, action="contact_list.crm_import", target_type="contact_list", target_id=list_id,
              organization_id=cl.organization_id, client_id=cl.client_id, actor_user_id=ctx().user.id,
              details={"job_id": job_id, "mode": van.mode})
    await enqueue("ngpvan_import_status", payload={"job_id": job_id, "list_id": list_id},
                  idempotency_key=f"vanstatus:{job_id}", organization_id=cl.organization_id, client_id=cl.client_id,
                  workflow_id="list_validation")
    return ok({"job_id": job_id, "mode": van.mode}, 202)
