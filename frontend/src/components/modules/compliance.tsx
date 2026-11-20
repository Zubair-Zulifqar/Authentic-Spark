"use client";
import { useState } from "react";
import { Globe, Ban, Inbox } from "lucide-react";
import { api, fmtDate } from "@/lib/api";
import { useAction, useApi, useMe } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Client, Row } from "@/lib/types";
import { Badge, Button, Card, DataTable, Dialog, ErrorState, Field, Input, LoadingRows, Select, Textarea } from "@/components/ui";

type Domain = Row & { domain: string; dkim_selectors: string[]; last_check: Record<string, { status: string; detail?: string; record?: string }> & { overall?: string }; last_checked_at: string | null };

export function ComplianceTab({ client }: { client: Client }) {
  const me = useMe();
  const w = can(me.data, "compliance:write", client.organization_id, client.id);
  const approver = can(me.data, "compliance:approve", client.organization_id, client.id);
  const cid = client.id;
  const domains = useApi<Domain[]>(["domains", cid], `/clients/${cid}/domains`);
  const supp = useApi<Row[]>(["supp", cid], `/clients/${cid}/suppressions?limit=200`);
  const events = useApi<Row[]>(["cevents", cid], `/clients/${cid}/compliance-events?limit=200`);
  const deliv = useApi<{ events: Record<string, number>; suppressions: Record<string, number> }>(["deliv", cid], `/clients/${cid}/deliverability`);
  const [dom, setDom] = useState({ open: false, domain: "", selectors: "" });
  const [sup, setSup] = useState({ open: false, channel: "email", value: "", reason: "manual", scope: "client" });
  const [reply, setReply] = useState({ open: false, from_address: "", text: "" });
  const inv = [["domains", cid], ["supp", cid], ["cevents", cid], ["deliv", cid]];
  const addDomain = useAction(() => api(`/clients/${cid}/domains`, { method: "POST", json: { domain: dom.domain.toLowerCase(), dkim_selectors: dom.selectors.split(/[\s,]+/).filter(Boolean) } }),
    { success: "Domain added", invalidate: inv, onSuccess: () => setDom({ ...dom, open: false }) });
  const check = useAction((id: string) => api<Domain>(`/domains/${id}/check`, { method: "POST" }), { success: (r) => `DNS check: ${r.last_check.overall}`, invalidate: inv });
  const addSup = useAction(() => api(`/clients/${cid}/suppressions`, { method: "POST", json: { channel: sup.channel, value: sup.value, reason: sup.reason, scope: sup.scope } }),
    { success: "Suppression recorded", invalidate: inv, onSuccess: () => setSup({ ...sup, open: false, value: "" }) });
  const logReply = useAction(() => api<Row>(`/clients/${cid}/inbound-replies`, { method: "POST", json: { from_address: reply.from_address, text: reply.text } }),
    { success: (r) => `Reply classified: ${String(r.status)}`, invalidate: inv, onSuccess: () => setReply({ open: false, from_address: "", text: "" }) });
  const review = useAction(({ id, decision }: { id: string; decision: string }) => api(`/compliance-events/${id}/review`, { method: "POST", json: { decision } }), { success: "Review recorded", invalidate: inv });
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted">These checks support compliance review; they are not legal advice and do not guarantee compliance with every applicable law. Explicit opt-out requests are suppressed immediately and are never overridden by AI.</p>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Deliverability summary">
          {deliv.data ? <div className="space-y-2 text-sm"><div className="flex flex-wrap gap-1">{Object.entries(deliv.data.events).map(([k, v]) => <Badge key={k} tone="muted">{`${k}: ${v}`}</Badge>)}</div><div className="flex flex-wrap gap-1">{Object.entries(deliv.data.suppressions).map(([k, v]) => <Badge key={k} tone="bad">{`${k}: ${v}`}</Badge>)}</div></div> : <LoadingRows rows={2} />}
        </Card>
        <Card title="Sending domains" className="lg:col-span-2" actions={w && <Button size="sm" onClick={() => setDom({ ...dom, open: true })}><Globe className="size-4" />Add domain</Button>}>
          {domains.isLoading ? <LoadingRows /> : domains.error ? <ErrorState error={domains.error} /> : (
            <DataTable rows={domains.data ?? []} columns={[
              { key: "domain", header: "Domain", render: (r) => <span className="font-medium">{r.domain}</span> },
              ...(["spf", "dkim", "dmarc"] as const).map((k) => ({ key: k, header: k.toUpperCase(), render: (r: Domain) => r.last_check?.[k] ? <span title={r.last_check[k].detail || r.last_check[k].record || ""}><Badge>{r.last_check[k].status}</Badge></span> : "—" })),
              { key: "last_checked_at", header: "Checked", render: (r) => fmtDate(r.last_checked_at) },
              { key: "a", header: "", render: (r) => <Button size="sm" variant="secondary" onClick={() => check.mutate(r.id)}>Check DNS</Button> },
            ]} />
          )}
        </Card>
      </div>
      <Card title="Opt-out & compliance events" actions={w && <Button size="sm" onClick={() => setReply({ ...reply, open: true })}><Inbox className="size-4" />Log inbound reply</Button>}>
        {events.isLoading ? <LoadingRows /> : (
          <DataTable rows={events.data ?? []} searchKeys={["subject_value", "raw_text"]} filterKey="status" columns={[
            { key: "created_at", header: "When", render: (r) => fmtDate(String(r.created_at)) },
            { key: "kind", header: "Kind" }, { key: "subject_value", header: "Contact" },
            { key: "raw_text", header: "Message", render: (r) => <span className="line-clamp-2 max-w-xs">{String(r.raw_text ?? "")}</span> },
            { key: "classification", header: "Classifier", render: (r) => { const c = r.classification as { intent?: string; explicit?: boolean }; return c?.intent ? `${c.intent}${c.explicit ? " (explicit)" : ""}` : "—"; } },
            { key: "status", header: "Status", render: (r) => <Badge>{String(r.status)}</Badge> },
            { key: "act", header: "", render: (r) => approver && r.status === "needs_review" ? <div className="flex gap-1"><Button size="sm" onClick={() => review.mutate({ id: r.id, decision: "suppress" })}>Suppress</Button><Button size="sm" variant="secondary" onClick={() => review.mutate({ id: r.id, decision: "dismiss" })}>Dismiss</Button></div> : null },
          ]} />
        )}
      </Card>
      <Card title="Suppression list" actions={w && <Button size="sm" onClick={() => setSup({ ...sup, open: true })}><Ban className="size-4" />Add suppression</Button>}>
        {supp.isLoading ? <LoadingRows /> : (
          <DataTable rows={supp.data ?? []} searchKeys={["value"]} filterKey="reason" columns={[
            { key: "value", header: "Value" }, { key: "channel", header: "Channel" }, { key: "reason", header: "Reason" },
            { key: "client_id", header: "Scope", render: (r) => r.client_id ? "client" : <Badge tone="info">global</Badge> },
            { key: "source", header: "Source" }, { key: "created_at", header: "Added", render: (r) => fmtDate(String(r.created_at)) },
          ]} />
        )}
      </Card>
      <Dialog open={dom.open} onOpenChange={(o) => setDom({ ...dom, open: o })} title="Add sending domain">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); addDomain.mutate(undefined); }}>
          <Field label="Domain"><Input required value={dom.domain} onChange={(e) => setDom({ ...dom, domain: e.target.value })} placeholder="mail.example.org" /></Field>
          <Field label="DKIM selectors" hint="Comma separated, e.g. google, s1"><Input value={dom.selectors} onChange={(e) => setDom({ ...dom, selectors: e.target.value })} /></Field>
          <Button type="submit" loading={addDomain.isPending}>Add</Button>
        </form>
      </Dialog>
      <Dialog open={sup.open} onOpenChange={(o) => setSup({ ...sup, open: o })} title="Add suppression">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); addSup.mutate(undefined); }}>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Channel"><Select value={sup.channel} onChange={(e) => setSup({ ...sup, channel: e.target.value })}><option>email</option><option>sms</option></Select></Field>
            <Field label="Reason"><Select value={sup.reason} onChange={(e) => setSup({ ...sup, reason: e.target.value })}>{["manual", "unsubscribe", "stop_keyword", "bounce", "complaint"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
          </div>
          <Field label={sup.channel === "sms" ? "Phone (E.164, e.g. +15552010001)" : "Email"}><Input required value={sup.value} onChange={(e) => setSup({ ...sup, value: e.target.value })} /></Field>
          {approver && <Field label="Scope"><Select value={sup.scope} onChange={(e) => setSup({ ...sup, scope: e.target.value })}><option value="client">This client</option><option value="global">Global (all clients)</option></Select></Field>}
          <Button type="submit" loading={addSup.isPending}>Add</Button>
        </form>
      </Dialog>
      <Dialog open={reply.open} onOpenChange={(o) => setReply({ ...reply, open: o })} title="Log inbound reply" description="Clear opt-outs are suppressed immediately; uncertain messages go to human review.">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); logReply.mutate(undefined); }}>
          <Field label="From address"><Input required value={reply.from_address} onChange={(e) => setReply({ ...reply, from_address: e.target.value })} /></Field>
          <Field label="Message text"><Textarea required value={reply.text} onChange={(e) => setReply({ ...reply, text: e.target.value })} /></Field>
          <Button type="submit" loading={logReply.isPending}>Classify & record</Button>
        </form>
      </Dialog>
    </div>
  );
}
