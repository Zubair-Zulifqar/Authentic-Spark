"use client";
import Link from "next/link";
import { useOrgId, useApi } from "@/lib/hooks";
import { money, fmtDate } from "@/lib/api";
import { Badge, Card, DataTable, Empty, ErrorState, LoadingRows, PageHeader, Stat } from "@/components/ui";

type Dash = {
  clients: { id: string; name: string; status: string; client_type: string }[];
  active_campaigns: number; email_production: Record<string, number>; sms: Record<string, number>; ads: Record<string, number>;
  invoices: Record<string, number>; outstanding_cents: number; failed_jobs: number; agent_runs_7d: number;
  pending_approvals: { type: string; id: string; client_id: string; title: string; created_at: string }[];
  deadlines: { id: string; client_id: string; send_date: string; theme: string; status: string; draft_deadline: string }[];
  recent_activity: { id: string; action: string; target_type: string; created_at: string; client_id: string | null }[];
  integration_health: Record<string, string>;
};

const sum = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0);

export default function Dashboard() {
  const orgId = useOrgId();
  const q = useApi<Dash>(["dashboard", orgId], orgId ? `/organizations/${orgId}/dashboard` : null, { refetchInterval: 60_000 });
  if (q.isLoading) return <LoadingRows rows={8} />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data!;
  const name = (id: string | null) => d.clients.find((c) => c.id === id)?.name ?? "Agency";
  return (
    <>
      <PageHeader title="Agency overview" subtitle={`${d.clients.length} clients you can access`} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat label="Clients" value={d.clients.length} />
        <Stat label="Active campaigns" value={d.active_campaigns} />
        <Stat label="Emails in production" value={sum(d.email_production) - (d.email_production.handed_off ?? 0)} />
        <Stat label="SMS campaigns" value={sum(d.sms)} hint={`${d.sms.pending_approval ?? 0} awaiting approval`} />
        <Stat label="Outstanding" value={money(d.outstanding_cents)} />
        <Stat label="Failed jobs" value={d.failed_jobs} hint={`${d.agent_runs_7d} AI runs`} />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card title="Pending approvals" className="lg:col-span-2">
          <DataTable rows={d.pending_approvals} searchKeys={["title"]} filterKey="type"
            empty={<Empty title="Nothing awaiting approval" />}
            columns={[
              { key: "type", header: "Type", render: (r) => <Badge tone="warn">{r.type}</Badge> },
              { key: "title", header: "Item", render: (r) => <Link className="text-accent hover:underline" href={`/clients/${r.client_id}?tab=${tabFor(r.type)}`}>{r.title || r.id.slice(0, 8)}</Link> },
              { key: "client_id", header: "Client", render: (r) => name(r.client_id) },
              { key: "created_at", header: "Created", render: (r) => fmtDate(r.created_at), sortable: true },
            ]} />
        </Card>
        <Card title="Integration health">
          <ul className="space-y-1.5 text-sm">
            {Object.entries(d.integration_health).map(([k, v]) => (
              <li key={k} className="flex justify-between"><span>{k.replace(/_/g, " ")}</span><Badge>{v}</Badge></li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">“mock” = no credentials configured; a labelled development adapter is active.</p>
        </Card>
        <Card title="Upcoming deadlines (14 days)" className="lg:col-span-2">
          <DataTable rows={d.deadlines} columns={[
            { key: "send_date", header: "Send", render: (r) => fmtDate(r.send_date), sortable: true },
            { key: "theme", header: "Email", render: (r) => <Link className="text-accent hover:underline" href={`/clients/${r.client_id}?tab=email`}>{r.theme}</Link> },
            { key: "client_id", header: "Client", render: (r) => name(r.client_id) },
            { key: "draft_deadline", header: "Draft due", render: (r) => fmtDate(r.draft_deadline) },
            { key: "status", header: "Status", render: (r) => <Badge>{r.status}</Badge> },
          ]} empty={<Empty title="No upcoming deadlines" />} />
        </Card>
        <Card title="Recent activity">
          <ul className="space-y-2 text-sm">
            {d.recent_activity.slice(0, 12).map((a) => (
              <li key={a.id}><span className="font-medium">{a.action}</span> <span className="text-muted">· {name(a.client_id)} · {fmtDate(a.created_at)}</span></li>
            ))}
            {!d.recent_activity.length && <li className="text-muted">No activity yet.</li>}
          </ul>
        </Card>
        <Card title="Invoices" className="lg:col-span-3">
          <div className="flex flex-wrap gap-2">{Object.entries(d.invoices).map(([k, v]) => <Badge key={k}>{`${k}: ${v}`}</Badge>)}</div>
        </Card>
      </div>
    </>
  );
}

function tabFor(t: string) {
  return { email_production: "email", sms_campaign: "sms", ad_creative: "ads", invoice: "billing" }[t] ?? "overview";
}
