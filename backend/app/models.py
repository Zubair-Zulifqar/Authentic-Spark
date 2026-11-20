"""Relational data model. Every tenant-scoped table carries organization_id and (where relevant) client_id,
and every query in the service layer filters on them (see app/core/rbac.py)."""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def uid() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(UTC)


class Timestamped:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for col in self.__table__.columns:  # type: ignore[attr-defined]
            v = getattr(self, col.name)
            if isinstance(v, (datetime, date)):
                v = v.isoformat()
            out[col.name] = v
        return out


# ---------------------------------------------------------------- identity & tenancy
class Organization(Timestamped, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)


class User(Timestamped, Base):
    __tablename__ = "users"
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(Timestamped, Base):
    """Grants a role to a user. client_id NULL => agency-wide. modules NULL => all modules the role allows."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", "client_id", name="uq_membership_scope"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), nullable=True)
    role: Mapped[str] = mapped_column(String(40))
    modules: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class Team(Timestamped, Base):
    __tablename__ = "teams"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    member_ids: Mapped[list[str]] = mapped_column(JSON, default=list)


class Client(Timestamped, Base):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("organization_id", "slug"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))
    client_type: Mapped[str] = mapped_column(String(40), default="nonprofit")  # nonprofit|campaign|pac|agency
    status: Mapped[str] = mapped_column(String(20), default="active")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    pinned_modules: Mapped[list[str]] = mapped_column(JSON, default=list)


class Campaign(Timestamped, Base):
    __tablename__ = "campaigns"
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text, default="")
    channel: Mapped[str] = mapped_column(String(20), default="multi")
    status: Mapped[str] = mapped_column(String(20), default="planning")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    budget_cents: Mapped[int] = mapped_column(Integer, default=0)


class Project(Timestamped, Base):
    __tablename__ = "projects"
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="open")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)


# ---------------------------------------------------------------- email
class EmailCalendar(Timestamped, Base):
    __tablename__ = "email_calendars"
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    objectives: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    google_doc_id: Mapped[str | None] = mapped_column(String(200), nullable=True)


class ScheduledEmail(Timestamped, Base):
    __tablename__ = "scheduled_emails"
    __table_args__ = (Index("ix_sched_client_date", "client_id", "send_date"),)
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str] = mapped_column(String(32), index=True)
    calendar_id: Mapped[str] = mapped_column(ForeignKey("email_calendars.id", ondelete="CASCADE"), index=True)
    send_date: Mapped[date] = mapped_column(Date)
    theme: Mapped[str] = mapped_column(String(200))
    brief: Mapped[str] = mapped_column(Text, default="")
    owner_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewer_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    draft_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned|drafting|in_review|approved|produced
    source_doc_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content_author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    asana_task_gid: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ProductionRecord(Timestamped, Base):
    __tablename__ = "production_records"
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str] = mapped_column(String(32), index=True)
    scheduled_email_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    source_doc_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subject: Mapped[str] = mapped_column(String(300), default="")
    preheader: Mapped[str] = mapped_column(String(300), default="")
    source_text: Mapped[str] = mapped_column(Text, default="")
    html: Mapped[str] = mapped_column(Text, default="")
    template: Mapped[str] = mapped_column(String(40), default="standard")
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|validated|approved|test_prepared|handed_off
    approved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    crm_platform: Mapped[str | None] = mapped_column(String(40), nullable=True)
    crm_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    history: Mapped[list[dict]] = mapped_column(JSON, default=list)


# ---------------------------------------------------------------- contacts
class ContactList(Timestamped, Base):
    __tablename__ = "contact_lists"
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(200))
    source_vendor: Mapped[str] = mapped_column(String(200))
    usage_permission: Mapped[str] = mapped_column(String(40))  # opt_in|transactional|vendor_attested_opt_in
    consent_evidence: Mapped[str] = mapped_column(Text, default="")
    filename: Mapped[str] = mapped_column(String(300), default="")
    column_mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    crm_import_status: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Contact(Timestamped, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("list_id", "email_normalized", name="uq_contact_list_email"),
        Index("ix_contact_client_email", "client_id", "email_normalized"),
    )
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str] = mapped_column(String(32), index=True)
    list_id: Mapped[str] = mapped_column(ForeignKey("contact_lists.id", ondelete="CASCADE"), index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_normalized: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    first_name: Mapped[str] = mapped_column(String(120), default="")
    last_name: Mapped[str] = mapped_column(String(120), default="")
    postal_code: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|valid|invalid|suppressed|risky
    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    sms_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    source_row: Mapped[int] = mapped_column(Integer, default=0)


class ImportIssue(Timestamped, Base):
    __tablename__ = "import_issues"
    list_id: Mapped[str] = mapped_column(ForeignKey("contact_lists.id", ondelete="CASCADE"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200))


class Suppression(Timestamped, Base):
    """client_id NULL => global (org-wide) suppression."""

    __tablename__ = "suppressions"
    __table_args__ = (UniqueConstraint("organization_id", "client_id", "channel", "value", name="uq_suppression"),)
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(10))  # email|sms
    value: Mapped[str] = mapped_column(String(320), index=True)
    reason: Mapped[str] = mapped_column(String(40))  # unsubscribe|stop_keyword|bounce|complaint|manual
    source: Mapped[str] = mapped_column(String(80), default="")


# ---------------------------------------------------------------- sms
class SmsCampaign(Timestamped, Base):
    __tablename__ = "sms_campaigns"
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str] = mapped_column(String(32), index=True)
    campaign_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    message_body: Mapped[str] = mapped_column(Text)
    message_author: Mapped[str] = mapped_column(String(200))
    sender_id: Mapped[str] = mapped_column(String(40), default="")
    contact_list_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    daily_send_limit: Mapped[int] = mapped_column(Integer, default=1000)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    compliance: Mapped[dict] = mapped_column(JSON, default=dict)
    eligible_recipients: Mapped[int] = mapped_column(Integer, default=0)
    approved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), default="scale_to_win")
    provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    delivery_stats: Mapped[dict] = mapped_column(JSON, default=dict)
    errors: Mapped[list] = mapped_column(JSON, default=list)


# ---------------------------------------------------------------- advertising
class AdCreative(Timestamped, Base):
    __tablename__ = "ad_creatives"
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str] = mapped_column(String(32), index=True)
    campaign_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    platform: Mapped[str] = mapped_column(String(20))  # meta|google_ads
    format: Mapped[str] = mapped_column(String(40))  # e.g. responsive_search, single_image
    name: Mapped[str] = mapped_column(String(200))
    headlines: Mapped[list[str]] = mapped_column(JSON, default=list)
    descriptions: Mapped[list[str]] = mapped_column(JSON, default=list)
    primary_text: Mapped[str] = mapped_column(Text, default="")
    disclaimer: Mapped[str] = mapped_column(String(300), default="")
    is_political: Mapped[bool] = mapped_column(Boolean, default=False)
    asset_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|in_review|approved|rejected
    checks: Mapped[dict] = mapped_column(JSON, default=dict)
    external_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)


class AdCreativeVersion(Timestamped, Base):
    __tablename__ = "ad_creative_versions"
    creative_id: Mapped[str] = mapped_column(ForeignKey("ad_creatives.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    changed_by: Mapped[str] = mapped_column(String(32))


# ---------------------------------------------------------------- billing
class Invoice(Timestamped, Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("organization_id", "number"),)
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str] = mapped_column(String(32), index=True)
    number: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|issued|partially_paid|paid|void
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    payment_terms: Mapped[str] = mapped_column(String(20), default="net_30")
    tax_rate: Mapped[float] = mapped_column(Float, default=0.0)
    line_items: Mapped[list[dict]] = mapped_column(JSON, default=list)
    subtotal_cents: Mapped[int] = mapped_column(Integer, default=0)
    tax_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cents: Mapped[int] = mapped_column(Integer, default=0)
    paid_cents: Mapped[int] = mapped_column(Integer, default=0)
    memo: Mapped[str] = mapped_column(Text, default="")
    approved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    qbo_invoice_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class Payment(Timestamped, Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("source", "external_id"),)
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str] = mapped_column(String(32), index=True)
    invoice_id: Mapped[str] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    external_id: Mapped[str] = mapped_column(String(120), default=uid)


# ---------------------------------------------------------------- compliance
class SendingDomain(Timestamped, Base):
    __tablename__ = "sending_domains"
    __table_args__ = (UniqueConstraint("client_id", "domain"),)
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str] = mapped_column(String(32), index=True)
    domain: Mapped[str] = mapped_column(String(253))
    dkim_selectors: Mapped[list[str]] = mapped_column(JSON, default=list)
    last_check: Mapped[dict] = mapped_column(JSON, default=dict)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ComplianceEvent(Timestamped, Base):
    __tablename__ = "compliance_events"
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40))  # unsubscribe_request|bounce|complaint|dns_issue|sms_stop
    channel: Mapped[str] = mapped_column(String(10), default="email")
    subject_value: Mapped[str] = mapped_column(String(320), default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    classification: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|needs_review|suppressed|dismissed
    resolved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


# ---------------------------------------------------------------- integrations / automation
class IntegrationConnection(Timestamped, Base):
    __tablename__ = "integration_connections"
    __table_args__ = (UniqueConstraint("organization_id", "client_id", "provider"),)
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="disconnected")  # connected|error|disconnected|mock
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # non-secret settings (channel ids, project gids)
    secret_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)  # Secret Manager resource name
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthState(Timestamped, Base):
    __tablename__ = "oauth_states"
    state: Mapped[str] = mapped_column(String(64), unique=True)
    provider: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[str] = mapped_column(String(32))
    organization_id: Mapped[str] = mapped_column(String(32))
    client_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class ExternalMapping(Timestamped, Base):
    """Maps internal records to external IDs; doubles as the idempotency ledger for outbound creates."""

    __tablename__ = "external_mappings"
    __table_args__ = (UniqueConstraint("provider", "idempotency_key"),)
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    internal_type: Mapped[str] = mapped_column(String(40))
    internal_id: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(200))


class WebhookEvent(Timestamped, Base):
    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_key"),)
    provider: Mapped[str] = mapped_column(String(40))
    event_key: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="received")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AutomationSubscription(Timestamped, Base):
    __tablename__ = "automation_subscriptions"
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    target_url: Mapped[str] = mapped_column(String(500))
    secret: Mapped[str] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AutomationExecution(Timestamped, Base):
    __tablename__ = "automation_executions"
    __table_args__ = (UniqueConstraint("subscription_id", "event_id"),)
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    subscription_id: Mapped[str] = mapped_column(ForeignKey("automation_subscriptions.id", ondelete="CASCADE"))
    event_id: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_response: Mapped[str | None] = mapped_column(Text, nullable=True)


class Job(Timestamped, Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("idempotency_key"),)
    organization_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    client_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    workflow_id: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(200), default=uid)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued|running|succeeded|failed
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    logs: Mapped[list[str]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentExecution(Timestamped, Base):
    __tablename__ = "agent_executions"
    organization_id: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    agent: Mapped[str] = mapped_column(String(60), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    input: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|succeeded|failed|awaiting_approval|approved|rejected
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(60))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AuditLog(Timestamped, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_org_client_created", "organization_id", "client_id", "created_at"),)
    organization_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
