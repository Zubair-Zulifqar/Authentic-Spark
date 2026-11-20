"use client";
import { useState } from "react";
import { Plus } from "lucide-react";
import { api, fmtDate, money } from "@/lib/api";
import { useAction, useApi, useMe } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Client, Row } from "@/lib/types";
import { Badge, Button, Card, DataTable, Dialog, ErrorState, Field, Input, LoadingRows, Select, Textarea } from "@/components/ui";

const STATUSES = ["planning", "active", "paused", "completed", "archived"];

export function CampaignsTab({ client }: { client: Client }) {
  const me = useMe();
  const writable = can(me.data, "campaigns:write", client.organization_id, client.id);
  const q = useApi<Row[]>(["campaigns", client.id], `/clients/${client.id}/campaigns`);
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", objective: "", channel: "multi", start_date: "", end_date: "", budget: "" });
  const create = useAction(() => api(`/clients/${client.id}/campaigns`, { method: "POST", json: {
    name: f.name, objective: f.objective, channel: f.channel, start_date: f.start_date || null, end_date: f.end_date || null,
    budget_cents: Math.round(Number(f.budget || 0) * 100) } }), { success: "Campaign created", invalidate: [["campaigns", client.id], ["overview", client.id]], onSuccess: () => setOpen(false) });
  const setStatus = useAction(({ id, status }: { id: string; status: string }) => api(`/campaigns/${id}`, { method: "PATCH", json: { status } }),
    { success: "Status updated", invalidate: [["campaigns", client.id]] });
  return (
    <Card title="Campaigns" actions={writable && <Button size="sm" onClick={() => setOpen(true)}><Plus className="size-4" />New campaign</Button>}>
      {q.isLoading ? <LoadingRows /> : q.error ? <ErrorState error={q.error} /> : (
        <DataTable rows={q.data ?? []} searchKeys={["name", "objective"]} filterKey="status" filterOptions={STATUSES} columns={[
          { key: "name", header: "Name", sortable: true, render: (r) => <span className="font-medium">{String(r.name)}</span> },
          { key: "channel", header: "Channel" },
          { key: "start_date", header: "Dates", render: (r) => `${fmtDate(r.start_date as string)} – ${fmtDate(r.end_date as string)}` },
          { key: "budget_cents", header: "Budget", render: (r) => money(Number(r.budget_cents)) },
          { key: "status", header: "Status", render: (r) => writable ? (
            <Select aria-label="Campaign status" className="w-32 py-0.5" value={String(r.status)} onChange={(e) => setStatus.mutate({ id: r.id, status: e.target.value })}>
              {STATUSES.map((s) => <option key={s}>{s}</option>)}
            </Select>) : <Badge>{String(r.status)}</Badge> },
        ]} />
      )}
      <Dialog open={open} onOpenChange={setOpen} title="New campaign">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(undefined); }}>
          <Field label="Name"><Input required minLength={2} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Objective"><Textarea value={f.objective} onChange={(e) => setF({ ...f, objective: e.target.value })} /></Field>
          <div className="grid grid-cols-3 gap-2">
            <Field label="Channel"><Select value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })}>{["multi", "email", "sms", "ads"].map((c) => <option key={c}>{c}</option>)}</Select></Field>
            <Field label="Start"><Input type="date" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} /></Field>
            <Field label="End"><Input type="date" value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} /></Field>
          </div>
          <Field label="Budget (USD)"><Input type="number" min="0" step="0.01" value={f.budget} onChange={(e) => setF({ ...f, budget: e.target.value })} /></Field>
          <Button type="submit" loading={create.isPending}>Create campaign</Button>
        </form>
      </Dialog>
    </Card>
  );
}
