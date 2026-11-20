"use client";
import { useState } from "react";
import { useApi, useOrgId } from "@/lib/hooks";
import type { Client } from "@/lib/types";
import { Card, ErrorState, LoadingRows, PageHeader, Select, Stat } from "@/components/ui";

type A = { workflow_success_rate: number | null; contact_lists: number; production_throughput: { client: string; handed_off: number }[] } & Record<string, Record<string, number>>;

function Bars({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data ?? {});
  const max = Math.max(1, ...entries.map(([, v]) => v));
  if (!entries.length) return <p className="text-sm text-muted">No data yet.</p>;
  return (
    <ul className="space-y-1.5">
      {entries.map(([k, v]) => (
        <li key={k} className="grid grid-cols-[120px_1fr_40px] items-center gap-2 text-sm">
          <span className="truncate text-muted">{k.replace(/_/g, " ")}</span>
          <span className="h-2.5 rounded-sm bg-accent" style={{ width: `${(v / max) * 100}%` }} />
          <span className="text-right tabular-nums">{v}</span>
        </li>
      ))}
    </ul>
  );
}

export default function Analytics() {
  const orgId = useOrgId();
  const [cid, setCid] = useState("");
  const clients = useApi<Client[]>(["clients", orgId], orgId ? `/organizations/${orgId}/clients` : null);
  const q = useApi<A>(["analytics", orgId, cid], orgId ? `/organizations/${orgId}/analytics${cid ? `?client_id=${cid}` : ""}` : null);
  return (
    <>
      <PageHeader title="Analytics" subtitle="Operational metrics. No political or personal attributes are used for segmentation."
        actions={<Select aria-label="Client filter" value={cid} onChange={(e) => setCid(e.target.value)} className="w-56"><option value="">All accessible clients</option>{(clients.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>} />
      {q.isLoading ? <LoadingRows /> : q.error ? <ErrorState error={q.error} /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Workflow success rate" value={q.data!.workflow_success_rate === null ? "—" : `${Math.round(q.data!.workflow_success_rate * 100)}%`} />
            <Stat label="Contact lists" value={q.data!.contact_lists} />
            <Stat label="Emails handed off" value={q.data!.productions?.handed_off ?? 0} />
            <Stat label="Open compliance events" value={(q.data!.compliance_events?.open ?? 0) + (q.data!.compliance_events?.needs_review ?? 0)} />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {(["productions", "scheduled_emails", "invoices", "compliance_events", "jobs", "agent_executions", "webhook_deliveries"] as const).map((k) => (
              <Card key={k} title={k.replace(/_/g, " ")}><Bars data={q.data![k]} /></Card>
            ))}
            <Card title="Production throughput by client"><Bars data={Object.fromEntries(q.data!.production_throughput.map((p) => [p.client, p.handed_off]))} /></Card>
          </div>
        </div>
      )}
    </>
  );
}
