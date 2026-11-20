"use client";
import { use } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import * as Tabs from "@radix-ui/react-tabs";
import { useApi, useMe } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Client } from "@/lib/types";
import { cx, ErrorState, LoadingRows, PageHeader, Badge } from "@/components/ui";
import { OverviewTab } from "@/components/modules/overview";
import { CampaignsTab } from "@/components/modules/campaigns";
import { EmailTab } from "@/components/modules/email";
import { ContactsTab } from "@/components/modules/contacts";
import { SmsTab } from "@/components/modules/sms";
import { AdsTab } from "@/components/modules/ads";
import { BillingTab } from "@/components/modules/billing";
import { ComplianceTab } from "@/components/modules/compliance";

const TABS = [
  { key: "overview", label: "Overview", perm: "clients:read", C: OverviewTab },
  { key: "campaigns", label: "Campaigns", perm: "campaigns:read", C: CampaignsTab },
  { key: "email", label: "Email", perm: "email:read", C: EmailTab },
  { key: "contacts", label: "Contact lists", perm: "contacts:read", C: ContactsTab },
  { key: "sms", label: "SMS", perm: "sms:read", C: SmsTab },
  { key: "ads", label: "Advertising", perm: "ads:read", C: AdsTab },
  { key: "billing", label: "Billing", perm: "billing:read", C: BillingTab },
  { key: "compliance", label: "Compliance", perm: "compliance:read", C: ComplianceTab },
];

export default function ClientWorkspace({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const sp = useSearchParams();
  const router = useRouter();
  const me = useMe();
  const q = useApi<Client>(["client", id], `/clients/${id}`);
  if (q.isLoading) return <LoadingRows rows={6} />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const client = q.data!;
  const tabs = TABS.filter((t) => can(me.data, t.perm, client.organization_id, id));
  const active = tabs.find((t) => t.key === sp.get("tab"))?.key ?? "overview";
  return (
    <>
      <PageHeader title={client.name} subtitle={`Client workspace · ${client.client_type}`} actions={<Badge>{client.status}</Badge>} />
      <Tabs.Root value={active} onValueChange={(v) => router.replace(`/clients/${id}?tab=${v}`)}>
        <Tabs.List aria-label="Client modules" className="mb-4 flex gap-1 overflow-x-auto border-b border-border">
          {tabs.map((t) => (
            <Tabs.Trigger key={t.key} value={t.key}
              className={cx("whitespace-nowrap border-b-2 px-3 py-2 text-sm", active === t.key ? "border-accent font-medium text-accent" : "border-transparent text-muted hover:text-text")}>
              {t.label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        {tabs.map(({ key, C }) => <Tabs.Content key={key} value={key}><C client={client} /></Tabs.Content>)}
      </Tabs.Root>
    </>
  );
}
