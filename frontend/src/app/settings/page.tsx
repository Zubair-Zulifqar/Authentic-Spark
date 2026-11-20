"use client";
import { useState } from "react";
import { UserPlus, Webhook, Play, Trash2 } from "lucide-react";
import { api, fmtDate } from "@/lib/api";
import { useAction, useApi, useMe, useOrgId } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Client, Row } from "@/lib/types";
import { Badge, Button, Card, DataTable, Dialog, Field, Input, LoadingRows, PageHeader, Select } from "@/components/ui";
import { toast } from "@/components/ui/toast";

export default function Settings() {
  const orgId = useOrgId();
  const me = useMe();
  const admin = can(me.data, "admin:read", orgId);
  const integ = can(me.data, "integrations:read", orgId);
  return (
    <>
      <PageHeader title="Settings" subtitle={`Signed in as ${me.data?.user.email}`} />
      <div className="space-y-4">
        <Card title="Your access">
          <ul className="space-y-1 text-sm">{me.data?.memberships.map((m, i) => <li key={i}><Badge tone="info">{m.role}</Badge> <span className="text-muted">{m.client_id ? `client ${m.client_id.slice(0, 8)}` : "agency-wide"}{m.modules ? ` · modules: ${m.modules.join(", ")}` : ""}</span></li>)}</ul>
        </Card>
        {admin && <Members orgId={orgId!} />}
        {integ && <Automations orgId={orgId!} />}
        {integ && <Jobs orgId={orgId!} />}
        {can(me.data, "compliance:read", orgId) && <Audit orgId={orgId!} />}
      </div>
    </>
  );
}

function Members({ orgId }: { orgId: string }) {
  const q = useApi<Row[]>(["members", orgId], `/organizations/${orgId}/members`);
  const roles = useApi<{ roles: Record<string, string[]>; modules: string[] }>(["roles"], "/roles");
  const clients = useApi<Client[]>(["clients", orgId], `/organizations/${orgId}/clients`);
  const [f, setF] = useState({ open: false, email: "", role: "read_only", client_id: "", modules: [] as string[] });
  const add = useAction(() => api(`/organizations/${orgId}/members`, { method: "POST", json: { email: f.email, role: f.role, client_id: f.client_id || null, modules: f.modules.length ? f.modules : null } }),
    { success: "Member added", invalidate: [["members", orgId]], onSuccess: () => setF({ ...f, open: false, email: "" }) });
  const del = useAction((id: string) => api(`/organizations/${orgId}/members/${id}`, { method: "DELETE" }), { success: "Membership removed", invalidate: [["members", orgId]] });
  const cname = (id: unknown) => clients.data?.find((c) => c.id === id)?.name ?? "Agency-wide";
  return (
    <Card title="Users & permissions" actions={<Button size="sm" onClick={() => setF({ ...f, open: true })}><UserPlus className="size-4" />Add member</Button>}>
      {q.isLoading ? <LoadingRows /> : <DataTable rows={q.data ?? []} searchKeys={["email"]} filterKey="role" columns={[
        { key: "email", header: "User" }, { key: "role", header: "Role", render: (r) => <Badge tone="info">{String(r.role)}</Badge> },
        { key: "client_id", header: "Scope", render: (r) => cname(r.client_id) },
        { key: "modules", header: "Modules", render: (r) => (r.modules as string[] | null)?.join(", ") ?? "all for role" },
        { key: "x", header: "", render: (r) => <Button size="sm" variant="ghost" aria-label="Remove" onClick={() => del.mutate(r.id)}><Trash2 className="size-4" /></Button> },
      ]} />}
      <Dialog open={f.open} onOpenChange={(o) => setF({ ...f, open: o })} title="Add member" description="The user signs in with this email via Firebase; permissions apply immediately.">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); add.mutate(undefined); }}>
          <Field label="Email"><Input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
          <Field label="Role"><Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>{Object.keys(roles.data?.roles ?? {}).map((r) => <option key={r}>{r}</option>)}</Select></Field>
          <Field label="Scope"><Select value={f.client_id} onChange={(e) => setF({ ...f, client_id: e.target.value })}><option value="">Agency-wide</option>{(clients.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
          <fieldset><legend className="text-sm font-medium">Restrict to modules (optional)</legend><div className="mt-1 flex flex-wrap gap-2">{(roles.data?.modules ?? []).map((m) => <label key={m} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={f.modules.includes(m)} onChange={(e) => setF({ ...f, modules: e.target.checked ? [...f.modules, m] : f.modules.filter((x) => x !== m) })} />{m}</label>)}</div></fieldset>
          <Button type="submit" loading={add.isPending}>Add</Button>
        </form>
      </Dialog>
    </Card>
  );
}

function Automations({ orgId }: { orgId: string }) {
  const subs = useApi<Row[]>(["subs", orgId], `/organizations/${orgId}/automations`);
  const types = useApi<string[]>(["etypes"], "/automation/event-types");
  const execs = useApi<Row[]>(["aexecs", orgId], `/organizations/${orgId}/automation-executions`);
  const [f, setF] = useState({ open: false, event_type: "client.created", target_url: "" });
  const add = useAction(() => api<Row>(`/organizations/${orgId}/automations`, { method: "POST", json: { event_type: f.event_type, target_url: f.target_url } }),
    { invalidate: [["subs", orgId]], onSuccess: (r) => { setF({ ...f, open: false }); toast.ok("Webhook subscribed", `Signing secret (shown once): ${String(r.secret)}`); } });
  const del = useAction((id: string) => api(`/organizations/${orgId}/automations/${id}`, { method: "DELETE" }), { success: "Subscription removed", invalidate: [["subs", orgId]] });
  return (
    <Card title="Automation webhooks (Zapier-compatible)" actions={<Button size="sm" onClick={() => setF({ ...f, open: true })}><Webhook className="size-4" />Add webhook</Button>}>
      <DataTable rows={subs.data ?? []} columns={[{ key: "event_type", header: "Event" }, { key: "target_url", header: "Target" },
        { key: "active", header: "Active", render: (r) => <Badge tone={r.active ? "ok" : "muted"}>{r.active ? "active" : "off"}</Badge> },
        { key: "x", header: "", render: (r) => <Button size="sm" variant="ghost" aria-label="Delete" onClick={() => del.mutate(r.id)}><Trash2 className="size-4" /></Button> }]} />
      <h3 className="mb-2 mt-4 text-sm font-semibold">Recent deliveries</h3>
      <DataTable rows={execs.data ?? []} filterKey="status" columns={[{ key: "created_at", header: "When", render: (r) => fmtDate(String(r.created_at)) }, { key: "event_type", header: "Event" }, { key: "attempts", header: "Attempts" }, { key: "last_response", header: "Response" }, { key: "status", header: "Status", render: (r) => <Badge>{String(r.status)}</Badge> }]} />
      <Dialog open={f.open} onOpenChange={(o) => setF({ ...f, open: o })} title="Subscribe a webhook" description="Deliveries are signed with X-Spark-Signature (HMAC-SHA256).">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); add.mutate(undefined); }}>
          <Field label="Event"><Select value={f.event_type} onChange={(e) => setF({ ...f, event_type: e.target.value })}>{(types.data ?? []).map((t) => <option key={t}>{t}</option>)}</Select></Field>
          <Field label="Target URL"><Input type="url" required value={f.target_url} onChange={(e) => setF({ ...f, target_url: e.target.value })} placeholder="https://hooks.zapier.com/…" /></Field>
          <Button type="submit" loading={add.isPending}>Subscribe</Button>
        </form>
      </Dialog>
    </Card>
  );
}

function Jobs({ orgId }: { orgId: string }) {
  const q = useApi<Row[]>(["jobs", orgId], `/organizations/${orgId}/jobs`, { refetchInterval: 10_000 });
  const run = useAction(() => api<Record<string, number>>(`/organizations/${orgId}/jobs/run`, { method: "POST" }),
    { success: (r) => `Ran jobs: ${r.succeeded} ok, ${r.retrying} retrying, ${r.failed} failed`, invalidate: [["jobs", orgId], ["dashboard"]] });
  const retry = useAction((id: string) => api(`/jobs/${id}/retry`, { method: "POST" }), { success: "Job re-queued", invalidate: [["jobs", orgId]] });
  return (
    <Card title="Background jobs" actions={<Button size="sm" variant="secondary" loading={run.isPending} onClick={() => run.mutate(undefined)}><Play className="size-4" />Run queued jobs now</Button>}>
      <DataTable rows={q.data ?? []} filterKey="status" columns={[
        { key: "created_at", header: "Created", render: (r) => fmtDate(String(r.created_at)) }, { key: "kind", header: "Kind" }, { key: "workflow_id", header: "Workflow" },
        { key: "retry_count", header: "Retries" }, { key: "status", header: "Status", render: (r) => <Badge>{String(r.status)}</Badge> },
        { key: "error", header: "Error", render: (r) => <span className="line-clamp-1 max-w-xs text-xs">{String(r.error ?? "")}</span> },
        { key: "x", header: "", render: (r) => r.status === "failed" ? <Button size="sm" variant="secondary" onClick={() => retry.mutate(r.id)}>Retry</Button> : null },
      ]} />
    </Card>
  );
}

function Audit({ orgId }: { orgId: string }) {
  const q = useApi<Row[]>(["audit", orgId], `/organizations/${orgId}/audit?limit=100`);
  return (
    <Card title="Audit log">
      <DataTable rows={q.data ?? []} searchKeys={["action", "target_type"]} columns={[
        { key: "created_at", header: "When", render: (r) => new Date(String(r.created_at)).toLocaleString() },
        { key: "action", header: "Action" }, { key: "target_type", header: "Target" }, { key: "actor_user_id", header: "Actor", render: (r) => String(r.actor_user_id ?? "system").slice(0, 8) },
      ]} />
    </Card>
  );
}
