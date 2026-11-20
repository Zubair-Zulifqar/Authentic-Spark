"use client";
import { useState } from "react";
import { Upload, ShieldCheck, Download, Database } from "lucide-react";
import { api, fmtDate, openAuthed } from "@/lib/api";
import { useAction, useApi, useMe } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Client, Row } from "@/lib/types";
import { Badge, Button, Card, DataTable, Dialog, ErrorState, Field, Input, LoadingRows, Select, Textarea } from "@/components/ui";

type Preview = { headers: string[]; row_count: number; sample: Record<string, string>[]; suggested_mapping: Record<string, string>; fields: string[] };
type ListRow = Row & { name: string; source_vendor: string; usage_permission: string; status: string; stats: Record<string, number | string>; crm_import_status: string | null; follow_up_date: string | null };

export function ContactsTab({ client }: { client: Client }) {
  const me = useMe();
  const w = can(me.data, "contacts:write", client.organization_id, client.id);
  const q = useApi<ListRow[]>(["lists", client.id], `/clients/${client.id}/contact-lists`);
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  return (
    <Card title="Contact lists (List Buys)" actions={w && <Button size="sm" onClick={() => setOpen(true)}><Upload className="size-4" />Upload vendor list</Button>}>
      <p className="mb-3 text-xs text-muted">Verified deliverability is not permission to send. Every list records its vendor, usage permission and consent evidence.</p>
      {q.isLoading ? <LoadingRows /> : q.error ? <ErrorState error={q.error} /> : (
        <DataTable rows={q.data ?? []} searchKeys={["name", "source_vendor"]} filterKey="status" onRowClick={(r) => setDetail(r.id)} columns={[
          { key: "name", header: "List", render: (r) => <span className="font-medium">{r.name}</span> },
          { key: "source_vendor", header: "Vendor" },
          { key: "usage_permission", header: "Permission", render: (r) => <Badge tone="muted">{r.usage_permission}</Badge> },
          { key: "stats", header: "Accepted / total", render: (r) => `${r.stats.accepted ?? 0} / ${r.stats.total ?? 0}` },
          { key: "status", header: "Status", render: (r) => <Badge>{r.status}</Badge> },
          { key: "follow_up_date", header: "Follow-up", render: (r) => fmtDate(r.follow_up_date) },
        ]} />
      )}
      {open && <UploadDialog client={client} onClose={() => setOpen(false)} />}
      {detail && <ListDetail id={detail} writable={w} clientId={client.id} onClose={() => setDetail(null)} />}
    </Card>
  );
}

function UploadDialog({ client, onClose }: { client: Client; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [f, setF] = useState({ name: "", source_vendor: "", usage_permission: "vendor_attested_opt_in", consent_evidence: "", follow_up_date: "" });
  const doPreview = useAction(async (fl: File) => {
    const fd = new FormData(); fd.append("file", fl);
    return api<Preview>(`/clients/${client.id}/contact-lists/preview`, { method: "POST", body: fd });
  }, { onSuccess: (p) => { setPreview(p); setMapping(p.suggested_mapping); } });
  const doImport = useAction(async () => {
    const fd = new FormData();
    fd.append("file", file!);
    Object.entries(f).forEach(([k, v]) => v && fd.append(k, v));
    fd.append("mapping", JSON.stringify(Object.fromEntries(Object.entries(mapping).filter(([, v]) => v))));
    return api<ListRow>(`/clients/${client.id}/contact-lists`, { method: "POST", body: fd });
  }, { success: (r) => `Imported: ${r.stats.accepted} accepted, ${r.stats.invalid} invalid, ${r.stats.duplicates} duplicates`, invalidate: [["lists", client.id]], onSuccess: onClose });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title="Upload vendor contact list" wide description="CSV only, up to 20MB. Contacts are de-duplicated and checked against suppression lists.">
      <div className="space-y-3">
        <Input type="file" accept=".csv,text/csv" aria-label="CSV file" onChange={(e) => { const fl = e.target.files?.[0] ?? null; setFile(fl); setPreview(null); if (fl) doPreview.mutate(fl); }} />
        {preview && (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); doImport.mutate(undefined); }}>
            <p className="text-sm text-muted">{preview.row_count} rows detected. Map columns:</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {preview.fields.map((fld) => (
                <Field key={fld} label={fld}>
                  <Select value={mapping[fld] ?? ""} onChange={(e) => setMapping({ ...mapping, [fld]: e.target.value })}>
                    <option value="">— none —</option>{preview.headers.map((h) => <option key={h}>{h}</option>)}
                  </Select>
                </Field>
              ))}
            </div>
            <div className="overflow-x-auto rounded border border-border text-xs"><table className="w-full"><thead className="bg-panel-2"><tr>{preview.headers.map((h) => <th key={h} className="px-2 py-1 text-left">{h}</th>)}</tr></thead>
              <tbody>{preview.sample.map((r, i) => <tr key={i} className="border-t border-border">{preview.headers.map((h) => <td key={h} className="px-2 py-1">{r[h]}</td>)}</tr>)}</tbody></table></div>
            <div className="grid gap-2 sm:grid-cols-2">
              <Field label="List name"><Input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
              <Field label="Source vendor"><Input required value={f.source_vendor} onChange={(e) => setF({ ...f, source_vendor: e.target.value })} /></Field>
              <Field label="Usage permission"><Select value={f.usage_permission} onChange={(e) => setF({ ...f, usage_permission: e.target.value })}><option value="opt_in">opt_in</option><option value="vendor_attested_opt_in">vendor_attested_opt_in</option><option value="transactional">transactional</option></Select></Field>
              <Field label="Follow-up date"><Input type="date" value={f.follow_up_date} onChange={(e) => setF({ ...f, follow_up_date: e.target.value })} /></Field>
            </div>
            <Field label="Consent evidence" hint="How and when recipients opted in; retained for audit."><Textarea value={f.consent_evidence} onChange={(e) => setF({ ...f, consent_evidence: e.target.value })} /></Field>
            <Button type="submit" loading={doImport.isPending}>Import list</Button>
          </form>
        )}
        {doPreview.isPending && <LoadingRows rows={2} />}
      </div>
    </Dialog>
  );
}

function ListDetail({ id, writable, clientId, onClose }: { id: string; writable: boolean; clientId: string; onClose: () => void }) {
  const q = useApi<ListRow & { contacts: Row[]; issues: Row[]; status_counts: Record<string, number> }>(["list", id], `/contact-lists/${id}?limit=200`, { refetchInterval: 5000 });
  const [url, setUrl] = useState("");
  const inv = [["list", id], ["lists", clientId]];
  const verify = useAction(() => api<{ job_id: string }>(`/contact-lists/${id}/verify`, { method: "POST" }), { success: "Verification queued", invalidate: inv });
  const crm = useAction(() => api<{ job_id: string; mode: string }>(`/contact-lists/${id}/crm-import`, { method: "POST", json: { target: "ngpvan", file_url: url } }),
    { success: (r) => `NGP VAN bulk import submitted (${r.mode}) job ${r.job_id}`, invalidate: inv });
  const d = q.data;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={d?.name ?? "List"} wide>
      {!d ? <LoadingRows /> : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">{Object.entries(d.status_counts).map(([k, v]) => <Badge key={k}>{`${k}: ${v}`}</Badge>)}<Badge tone="muted">{`list status: ${d.status}`}</Badge>{d.crm_import_status && <Badge tone="info">{`CRM: ${d.crm_import_status}`}</Badge>}</div>
          {writable && <div className="flex flex-wrap gap-2">
            <Button size="sm" loading={verify.isPending} onClick={() => verify.mutate(undefined)}><ShieldCheck className="size-4" />Verify with ZeroBounce</Button>
            <Button size="sm" variant="secondary" onClick={() => openAuthed(`/contact-lists/${id}/export.csv`)}><Download className="size-4" />Export valid contacts CSV</Button>
          </div>}
          {writable && d.status === "verified" && (
            <div className="flex gap-2"><Input placeholder="Signed URL of exported CSV (Cloud Storage)" value={url} onChange={(e) => setUrl(e.target.value)} />
              <Button size="sm" loading={crm.isPending} onClick={() => crm.mutate(undefined)}><Database className="size-4" />NGP VAN import</Button></div>
          )}
          <p className="text-xs text-muted">Verification runs as a background job; drain the queue from Settings → Jobs locally, or via Cloud Scheduler in production.</p>
          <DataTable rows={d.contacts} searchKeys={["email", "first_name", "last_name"]} filterKey="status" columns={[
            { key: "source_row", header: "Row" }, { key: "email", header: "Email" }, { key: "phone", header: "Phone" },
            { key: "first_name", header: "First" }, { key: "sms_consent", header: "SMS consent", render: (r) => (r.sms_consent ? "yes" : "no") },
            { key: "status", header: "Status", render: (r) => <Badge>{String(r.status)}</Badge> },
          ]} />
          {d.issues.length > 0 && <Card title={`Import issues (${d.issues.length})`}><ul className="max-h-40 overflow-y-auto text-xs">{d.issues.map((i) => <li key={i.id}>Row {String(i.row_number)}: {String(i.reason)}</li>)}</ul></Card>}
        </div>
      )}
    </Dialog>
  );
}
