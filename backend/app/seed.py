"""Seeds synthetic demo data. All names, emails and phone numbers are fictitious (example.org / 555 numbers)."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from sqlalchemy import select

from app.core import db
from app.core.config import get_settings
from app.models import (
    AdCreative,
    Campaign,
    Client,
    EmailCalendar,
    Invoice,
    Membership,
    Organization,
    ScheduledEmail,
    SendingDomain,
    User,
)

USERS = [
    ("admin@spark.example", "Avery Admin", "agency_admin", None),
    ("ops@spark.example", "Oli Ops", "operations_manager", None),
    ("email@spark.example", "Emery Email", "email_specialist", None),
    ("finance@spark.example", "Finn Finance", "finance_user", None),
    ("compliance@spark.example", "Casey Compliance", "compliance_reviewer", None),
]
CLIENTS = [
    ("Riverbend Food Bank", "nonprofit"), ("Coastal Wildlife Trust", "nonprofit"),
    ("Citizens for Clean Parks", "advocacy"), ("Northside Library Foundation", "nonprofit"),
]


async def seed() -> None:
    db.init_engine(get_settings().database_url)
    await db.create_all()
    async with db.session_scope() as s:
        if (await s.execute(select(Organization).where(Organization.slug == "spark-demo-agency"))).scalar_one_or_none():
            print("already seeded")
            return
        org = Organization(name="Spark Demo Agency", slug="spark-demo-agency")
        s.add(org)
        await s.flush()
        clients = []
        for name, typ in CLIENTS:
            c = Client(organization_id=org.id, name=name, slug=name.lower().replace(" ", "-"), client_type=typ,
                       pinned_modules=["email", "contacts", "sms"],
                       settings={"asana_project_gid": "1200000000000001", "qbo_customer_id": "58",
                                 "google_ads_customer_id": "1234567890", "brand_terms": [name.split()[0]],
                                 "banned_terms": ["guaranteed"], "slack_channels": {"approvals": "#ops-approvals"}})
            s.add(c)
            clients.append(c)
        await s.flush()
        for email, name, role, _ in USERS:
            u = User(email=email, firebase_uid=f"dev-{email}", display_name=name)
            s.add(u)
            await s.flush()
            s.add(Membership(user_id=u.id, organization_id=org.id, role=role))
        # Client-scoped account manager: sees only the first client.
        am = User(email="am@spark.example", firebase_uid="dev-am@spark.example", display_name="Alex Account")
        s.add(am)
        await s.flush()
        s.add(Membership(user_id=am.id, organization_id=org.id, client_id=clients[0].id, role="account_manager"))
        today = date.today()
        for i, c in enumerate(clients):
            camp = Campaign(organization_id=org.id, client_id=c.id, name=f"{c.name.split()[0]} Spring Drive",
                            objective="Volunteer recruitment and program updates", status="active",
                            start_date=today, end_date=today + timedelta(days=45))
            s.add(camp)
            await s.flush()
            cal = EmailCalendar(organization_id=org.id, client_id=c.id, campaign_id=camp.id, name="Spring calendar",
                                objectives="Keep supporters informed", start_date=today, end_date=today + timedelta(days=30))
            s.add(cal)
            await s.flush()
            for j, theme in enumerate(["Program update", "Volunteer spotlight", "Event invitation"]):
                s.add(ScheduledEmail(organization_id=org.id, client_id=c.id, calendar_id=cal.id,
                                     send_date=today + timedelta(days=3 + j * 4 + i), theme=theme,
                                     draft_deadline=today + timedelta(days=j * 4 + i), status=["planned", "drafting", "in_review"][j]))
            s.add(SendingDomain(organization_id=org.id, client_id=c.id, domain="example.org", dkim_selectors=["google"]))
            s.add(Invoice(organization_id=org.id, client_id=c.id, number=f"AS-{today.year}-{i + 1:05d}", issue_date=today,
                          due_date=today + timedelta(days=30), line_items=[{"description": "Monthly email operations retainer",
                          "quantity": 1, "unit_price_cents": 450000}], subtotal_cents=450000, total_cents=450000))
            s.add(AdCreative(organization_id=org.id, client_id=c.id, platform="google_ads", format="responsive_search",
                             name="Volunteer search ad", headlines=["Volunteer this spring", f"Join {c.name.split()[0]}"],
                             descriptions=["Find a shift that fits your schedule."], checks={"passed": True, "checks": []}))
    print("seeded: org 'Spark Demo Agency'; sign in locally with token dev:admin@spark.example")


if __name__ == "__main__":
    asyncio.run(seed())
