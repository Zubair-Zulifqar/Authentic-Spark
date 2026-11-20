"use client";
import { useState } from "react";
import { api, fmtDate } from "@/lib/api";
import { useAction, useApi, useMe } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Client } from "@/lib/types";
import { Badge, Button, Card, ErrorState, LoadingRows, Stat } from "@/components/ui";

type Overview = {
  visible_modules: string[]; counts: Record<string, number | null>;
  pending_approvals: { type: string; id: string; title: string }[];
  upcoming: { id: string; send_date: string; theme: string; status: string }[];
  recent_activity: { id: string; action: string; created_at: string }[];
  integrations: { provider: string; status: string }[];
};
const ALL_MODULES = ["email", "contacts", "sms", "ads", "billing", "compliance", "campaigns", "analytics"];

export function OverviewTab({ client }: { client: Client }) {
  const me = useMe();
  const q = useApi<Overview>(["overview", client.id], `/clients/${client.id}/overview`);
  const [pins, setPins] = useState<string[] | null>(null);
  const save = useAction((p: string[]) => api(`/clients/${client.id}`, { method: "PATCH", json: { pinned_modules: p } }), {
    success: "Pinned modules saved", invalidate: [["client", client.id]], onSuccess: () => setPins(null),
  });
  if (q.isLoading) return <LoadingRows />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data!;
  const pinned = pins ?? client.pinned_modules ?? [];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {Object.entries(d.counts).filter(([, v]) => v !== null).map(([k, v]) => <Stat key={k} label={k.replace(/_/g, " ")} value={v} />)}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Pending approvals">
          {d.pending_approvals.length ? <ul className="space-y-1.5 text-sm">{d.pending_approvals.map((a) => <li key={a.id} className="flex justify-between gap-2"><span className="truncate">{a.title || a.id.slice(0, 8)}</span><Badge tone="warn">{a.type}</Badge></li>)}</ul> : <p className="text-sm text-muted">None</p>}
        </Card>
        <Card title="Upcoming sends">
          {d.upcoming.length ? <ul className="space-y-1.5 text-sm">{d.upcoming.map((u) => <li key={u.id} className="flex justify-between gap-2"><span>{fmtDate(u.send_date)} · {u.theme}</span><Badge>{u.status}</Badge></li>)}</ul> : <p className="text-sm text-muted">None scheduled</p>}
        </Card>
        <Card title="Pinned modules" actions={can(me.data, "clients:write", client.organization_id, client.id) && pins && <Button size="sm" loading={save.isPending} onClick={() => save.mutate(pinned)}>Save</Button>}>
          <div className="flex flex-wrap gap-2">
            {ALL_MODULES.map((m) => (
              <label key={m} className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={pinned.includes(m)} disabled={!can(me.data, "clients:write", client.organization_id, client.id)}
                  onChange={(e) => setPins(e.target.checked ? [...pinned, m] : pinned.filter((x) => x !== m))} />{m}
              </label>
            ))}
          </div>
        </Card>
        <Card title="Recent activity" className="lg:col-span-2">
          <ul className="space-y-1.5 text-sm">{d.recent_activity.map((a) => <li key={a.id}><span className="font-medium">{a.action}</span> <span className="text-muted">· {fmtDate(a.created_at)}</span></li>)}</ul>
          {!d.recent_activity.length && <p className="text-sm text-muted">No activity yet.</p>}
        </Card>
        <Card title="Client integrations">
          {d.integrations.length ? d.integrations.map((i) => <div key={i.provider} className="flex justify-between text-sm"><span>{i.provider}</span><Badge>{i.status}</Badge></div>) : <p className="text-sm text-muted">Using agency-level integrations.</p>}
        </Card>
      </div>
    </div>
  );
}
