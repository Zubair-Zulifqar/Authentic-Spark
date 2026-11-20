"use client";
import Link from "next/link";
import { use } from "react";
import { useApi, useMe, useOrgId } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Client } from "@/lib/types";
import { Card, Empty, ErrorState, LoadingRows, PageHeader } from "@/components/ui";

const TITLES: Record<string, [string, string, string]> = {
  campaigns: ["Campaigns", "campaigns:read", "Campaigns and projects per client"],
  email: ["Email operations", "email:read", "Calendars and the production pipeline"],
  contacts: ["Contact lists", "contacts:read", "Vendor list acquisition, validation and CRM handoff"],
  sms: ["SMS", "sms:read", "Consent-gated SMS campaign administration"],
  ads: ["Advertising", "ads:read", "Creative assets, review and Google Ads reporting"],
  billing: ["Invoicing", "billing:read", "Invoices, payments and QuickBooks sync"],
  compliance: ["Compliance", "compliance:read", "Deliverability, suppression and opt-out processing"],
};

export default function ModulePicker({ params }: { params: Promise<{ module: string }> }) {
  const { module } = use(params);
  const orgId = useOrgId();
  const me = useMe();
  const q = useApi<Client[]>(["clients", orgId], orgId ? `/organizations/${orgId}/clients` : null);
  const [title, perm, subtitle] = TITLES[module] ?? ["Module", "clients:read", ""];
  if (q.isLoading) return <LoadingRows />;
  if (q.error) return <ErrorState error={q.error} />;
  const clients = (q.data ?? []).filter((c) => can(me.data, perm, orgId, c.id));
  return (
    <>
      <PageHeader title={title} subtitle={`${subtitle} — choose a client workspace`} />
      {clients.length === 0 ? <Empty title="No clients available for this module" /> : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {clients.map((c) => (
            <Link key={c.id} href={`/clients/${c.id}?tab=${module}`}>
              <Card className="h-full transition hover:border-accent"><p className="font-medium">{c.name}</p><p className="text-xs text-muted">{c.client_type}</p></Card>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
