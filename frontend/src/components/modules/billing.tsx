"use client";
import { useState } from "react";
import { Plus, Trash2, FileDown } from "lucide-react";
import { api, fmtDate, money, openAuthed } from "@/lib/api";
import { useAction, useApi, useMe } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Client, Row } from "@/lib/types";
import { Badge, Button, Card, DataTable, Dialog, ErrorState, Field, Input, LoadingRows, Select, Textarea } from "@/components/ui";

type Inv = Row & { number: string; status: string; issue_date: string; due_date: string; total_cents: number; paid_cents: number; qbo_invoice_id: string | null };
type Line = { description: string; quantity: number; unit_price_cents: number };

export function BillingTab({ client }: { client: Client }) {
  const me = useMe();
  const w = can(me.data, "billing:write", client.organization_id, client.id);
  const approver = can(me.data, "billing:approve", client.organization_id, client.id);
  const q = useApi<Inv[]>(["invoices", client.id], `/clients/${client.id}/invoices`);
  const [open, setOpen] = useState(false);
  const [pay, setPay] = useState<Inv | null>(null);
  const inv = [["invoices", client.id], ["dashboard"]];
  const approve = useAction((id: string) => api(`/invoices/${id}/approve`, { method: "POST" }), { success: "Invoice approved", invalidate: inv });
  const issue = useAction((id: string) => api<Inv & { mode: string }>(`/invoices/${id}/issue`, { method: "POST" }), { success: (r) => `Created in QuickBooks (${r.mode}) #${r.qbo_invoice_id}`, invalidate: inv });
  return (
    <Card title="Invoices" actions={w && <Button size="sm" onClick={() => setOpen(true)}><Plus className="size-4" />New invoice</Button>}>
      {q.isLoading ? <LoadingRows /> : q.error ? <ErrorState error={q.error} /> : (
        <DataTable rows={q.data ?? []} searchKeys={["number"]} filterKey="status" columns={[
          { key: "number", header: "Invoice", render: (r) => <span className="font-medium">{r.number}</span> },
          { key: "issue_date", header: "Issued", sortable: true, render: (r) => fmtDate(r.issue_date) },
          { key: "due_date", header: "Due", render: (r) => fmtDate(r.due_date) },
          { key: "total_cents", header: "Total", render: (r) => money(r.total_cents) },
          { key: "paid_cents", header: "Paid", render: (r) => money(r.paid_cents) },
          { key: "status", header: "Status", render: (r) => <Badge>{r.status}</Badge> },
          { key: "actions", header: "", render: (r) => (
            <div className="flex gap-1">
              <Button size="sm" variant="ghost" aria-label="PDF" onClick={() => openAuthed(`/invoices/${r.id}/pdf`)}><FileDown className="size-4" /></Button>
              {approver && r.status === "draft" && <Button size="sm" variant="secondary" onClick={() => approve.mutate(r.id)}>Approve</Button>}
              {approver && r.status === "approved" && <Button size="sm" variant="secondary" onClick={() => issue.mutate(r.id)}>Issue to QuickBooks</Button>}
              {w && ["issued", "partially_paid"].includes(r.status) && <Button size="sm" variant="secondary" onClick={() => setPay(r)}>Record payment</Button>}
            </div>) },
        ]} />
      )}
      {open && <InvoiceEditor client={client} onClose={() => setOpen(false)} />}
      {pay && <PaymentDialog invoice={pay} onClose={() => setPay(null)} invalidate={inv} />}
    </Card>
  );
}

function InvoiceEditor({ client, onClose }: { client: Client; onClose: () => void }) {
  const [lines, setLines] = useState<Line[]>([{ description: "", quantity: 1, unit_price_cents: 0 }]);
  const [terms, setTerms] = useState("net_30");
  const [tax, setTax] = useState(0);
  const [memo, setMemo] = useState("");
  const [preview, setPreview] = useState<{ subtotal_cents: number; tax_cents: number; total_cents: number; due_date: string } | null>(null);
  const body = { line_items: lines, payment_terms: terms, tax_rate: tax / 100, memo };
  const doPreview = useAction(() => api<typeof preview>(`/clients/${client.id}/invoices/preview`, { method: "POST", json: body }), { onSuccess: setPreview });
  const create = useAction(() => api(`/clients/${client.id}/invoices`, { method: "POST", json: body }), { success: "Draft invoice created", invalidate: [["invoices", client.id]], onSuccess: onClose });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title="New invoice (draft)" wide description="Preview totals before saving. Drafts require finance approval before issuing.">
      <div className="space-y-3">
        {lines.map((l, i) => (
          <div key={i} className="grid grid-cols-[1fr_80px_120px_32px] items-end gap-2">
            <Field label={i ? "" : "Description"}><Input value={l.description} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, description: e.target.value } : x))} /></Field>
            <Field label={i ? "" : "Qty"}><Input type="number" min="0.01" step="0.01" value={l.quantity} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, quantity: Number(e.target.value) } : x))} /></Field>
            <Field label={i ? "" : "Unit price ($)"}><Input type="number" min="0" step="0.01" value={l.unit_price_cents / 100} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, unit_price_cents: Math.round(Number(e.target.value) * 100) } : x))} /></Field>
            <Button variant="ghost" size="sm" aria-label="Remove line" disabled={lines.length === 1} onClick={() => setLines(lines.filter((_, j) => j !== i))}><Trash2 className="size-4" /></Button>
          </div>
        ))}
        <Button size="sm" variant="secondary" onClick={() => setLines([...lines, { description: "", quantity: 1, unit_price_cents: 0 }])}>Add line</Button>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Payment terms"><Select value={terms} onChange={(e) => setTerms(e.target.value)}>{["due_on_receipt", "net_15", "net_30", "net_45", "net_60"].map((t) => <option key={t}>{t}</option>)}</Select></Field>
          <Field label="Tax rate (%)"><Input type="number" min="0" max="25" step="0.01" value={tax} onChange={(e) => setTax(Number(e.target.value))} /></Field>
        </div>
        <Field label="Memo"><Textarea value={memo} onChange={(e) => setMemo(e.target.value)} /></Field>
        {preview && <div className="rounded-md border border-border bg-panel-2 p-3 text-sm">Subtotal {money(preview.subtotal_cents)} · Tax {money(preview.tax_cents)} · <b>Total {money(preview.total_cents)}</b> · Due {fmtDate(preview.due_date)}</div>}
        <div className="flex gap-2"><Button variant="secondary" loading={doPreview.isPending} onClick={() => doPreview.mutate(undefined)}>Preview</Button><Button loading={create.isPending} onClick={() => create.mutate(undefined)}>Save draft</Button></div>
      </div>
    </Dialog>
  );
}

function PaymentDialog({ invoice, onClose, invalidate }: { invoice: Inv; onClose: () => void; invalidate: unknown[][] }) {
  const [amt, setAmt] = useState(((invoice.total_cents - invoice.paid_cents) / 100).toFixed(2));
  const [ref, setRef] = useState("");
  const pays = useApi<Row[]>(["payments", invoice.id], `/invoices/${invoice.id}/payments`);
  const rec = useAction(() => api(`/invoices/${invoice.id}/payments`, { method: "POST", json: { amount_cents: Math.round(Number(amt) * 100), external_id: ref || undefined } }),
    { success: "Payment recorded", invalidate: [...invalidate, ["payments", invoice.id]], onSuccess: onClose });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={`Payment for ${invoice.number}`}>
      <div className="space-y-3">
        <Field label="Amount ($)"><Input type="number" min="0.01" step="0.01" value={amt} onChange={(e) => setAmt(e.target.value)} /></Field>
        <Field label="Reference (check #, transaction id)" hint="Used to prevent duplicate entries."><Input value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
        <Button loading={rec.isPending} onClick={() => rec.mutate(undefined)}>Record payment</Button>
        <ul className="text-xs text-muted">{(pays.data ?? []).map((p) => <li key={p.id}>{fmtDate(String(p.received_at))} · {money(Number(p.amount_cents))} · {String(p.source)}</li>)}</ul>
      </div>
    </Dialog>
  );
}
