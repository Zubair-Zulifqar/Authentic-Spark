"use client";
import { useState } from "react";
import { MessageSquarePlus } from "lucide-react";
import { api } from "@/lib/api";
import { useAction, useApi, useMe } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Client, Row } from "@/lib/types";
import { Badge, Button, Card, Checks, DataTable, Dialog, ErrorState, Field, Input, LoadingRows, Select, Textarea } from "@/components/ui";

type Sms = Row & { name: string; status: string; message_body: string; eligible_recipients: number; provider_status: string | null; provider_reference: string | null;
  compliance: { passed: boolean; checks: { check: string; passed: boolean; detail?: string }[] }; delivery_stats: Record<string, number> };

export function SmsTab({ client }: { client: Client }) {
  const me = useMe();
  const w = can(me.data, "sms:write", client.organization_id, client.id);
  const q = useApi<Sms[]>(["sms", client.id], `/clients/${client.id}/sms-campaigns`);
  const lists = useApi<Row[]>(["lists", client.id], w ? `/clients/${client.id}/contact-lists` : null);
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  const [f, setF] = useState({ name: "", message_body: "", message_author: "", sender_id: "", contact_list_id: "", daily_send_limit: 1000 });
  const create = useAction(() => api<Sms>(`/clients/${client.id}/sms-campaigns`, { method: "POST", json: { ...f, contact_list_id: f.contact_list_id || null } }),
    { success: "SMS campaign drafted", invalidate: [["sms", client.id]], onSuccess: (r) => { setOpen(false); setDetail(r.id); } });
  return (
    <Card title="SMS campaigns" actions={w && <Button size="sm" onClick={() => setOpen(true)}><MessageSquarePlus className="size-4" />New SMS campaign</Button>}>
      <p className="mb-3 text-xs text-muted">Only consented, non-suppressed recipients count. STOP replies suppress immediately. The platform provisions approved campaigns; launch happens in the provider console.</p>
      {q.isLoading ? <LoadingRows /> : q.error ? <ErrorState error={q.error} /> : (
        <DataTable rows={q.data ?? []} searchKeys={["name"]} filterKey="status" onRowClick={(r) => setDetail(r.id)} columns={[
          { key: "name", header: "Campaign", render: (r) => <span className="font-medium">{r.name}</span> },
          { key: "eligible_recipients", header: "Eligible" },
          { key: "compliance", header: "Compliance", render: (r) => <Badge tone={r.compliance?.passed ? "ok" : "bad"}>{r.compliance?.passed ? "pass" : "issues"}</Badge> },
          { key: "status", header: "Status", render: (r) => <Badge>{r.status}</Badge> },
          { key: "provider_status", header: "Provider", render: (r) => r.provider_status ?? "—" },
        ]} />
      )}
      <Dialog open={open} onOpenChange={setOpen} title="New SMS campaign" description="Message copy must be written and approved by staff.">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(undefined); }}>
          <Field label="Name"><Input required minLength={2} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Sender ID" hint="Must appear in the message body."><Input required minLength={2} value={f.sender_id} onChange={(e) => setF({ ...f, sender_id: e.target.value })} /></Field>
          <Field label="Message" hint={`${f.message_body.length} chars. Include “Reply STOP to opt out”.`}><Textarea required value={f.message_body} onChange={(e) => setF({ ...f, message_body: e.target.value })} /></Field>
          <Field label="Message author (human)"><Input required minLength={2} value={f.message_author} onChange={(e) => setF({ ...f, message_author: e.target.value })} /></Field>
          <Field label="Contact list"><Select value={f.contact_list_id} onChange={(e) => setF({ ...f, contact_list_id: e.target.value })}><option value="">— select —</option>{(lists.data ?? []).map((l) => <option key={l.id} value={l.id}>{String(l.name)}</option>)}</Select></Field>
          <Field label="Daily send limit"><Input type="number" min={1} max={50000} value={f.daily_send_limit} onChange={(e) => setF({ ...f, daily_send_limit: Number(e.target.value) })} /></Field>
          <Button type="submit" loading={create.isPending}>Create draft</Button>
        </form>
      </Dialog>
      {detail && <SmsDetail id={detail} client={client} onClose={() => setDetail(null)} />}
    </Card>
  );
}

function SmsDetail({ id, client, onClose }: { id: string; client: Client; onClose: () => void }) {
  const me = useMe();
  const q = useApi<Sms>(["smsd", id], `/sms-campaigns/${id}`);
  const inv = [["smsd", id], ["sms", client.id], ["dashboard"]];
  const submit = useAction(() => api(`/sms-campaigns/${id}/submit`, { method: "POST" }), { success: "Submitted for approval", invalidate: inv });
  const decide = useAction((approve: boolean) => api(`/sms-campaigns/${id}/decision`, { method: "POST", json: { approve } }), { success: "Decision recorded", invalidate: inv });
  const provision = useAction(() => api(`/sms-campaigns/${id}/provision`, { method: "POST" }), { success: "Provisioned at provider (not launched)", invalidate: inv });
  const refresh = useAction(() => api(`/sms-campaigns/${id}/refresh-status`, { method: "POST" }), { success: "Status refreshed", invalidate: inv });
  const s = q.data;
  const w = can(me.data, "sms:write", client.organization_id, client.id);
  const approver = can(me.data, "sms:approve", client.organization_id, client.id);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={s?.name ?? "SMS campaign"} wide>
      {!s ? <LoadingRows /> : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2"><Badge>{s.status}</Badge><Badge tone="muted">{`${s.eligible_recipients} eligible`}</Badge>{s.provider_reference && <Badge tone="info">{s.provider_reference}</Badge>}</div>
          <blockquote className="rounded-md border border-border bg-panel-2 p-3 text-sm">{s.message_body}</blockquote>
          <Checks checks={s.compliance.checks} />
          <div className="flex flex-wrap gap-2">
            {w && ["draft", "rejected"].includes(s.status) && <Button size="sm" loading={submit.isPending} onClick={() => submit.mutate(undefined)}>Submit for approval</Button>}
            {approver && s.status === "pending_approval" && <><Button size="sm" onClick={() => decide.mutate(true)}>Approve</Button><Button size="sm" variant="danger" onClick={() => decide.mutate(false)}>Reject</Button></>}
            {w && s.status === "approved" && <Button size="sm" loading={provision.isPending} onClick={() => provision.mutate(undefined)}>Provision at Scale to Win</Button>}
            {s.provider_reference && <Button size="sm" variant="secondary" onClick={() => refresh.mutate(undefined)}>Refresh delivery status</Button>}
          </div>
          {s.delivery_stats && Object.keys(s.delivery_stats).length > 0 && <div className="flex gap-2">{Object.entries(s.delivery_stats).map(([k, v]) => <Badge key={k} tone="muted">{`${k}: ${v}`}</Badge>)}</div>}
        </div>
      )}
    </Dialog>
  );
}
