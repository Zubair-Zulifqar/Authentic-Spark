"use client";
import { useMemo, useState } from "react";
import { CalendarPlus, FileText, Wand2, Send, CheckCircle2, Eye } from "lucide-react";
import { api, fmtDate, openAuthed } from "@/lib/api";
import { useAction, useApi, useMe } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Client, Row } from "@/lib/types";
import { Badge, Button, Card, Checks, DataTable, Dialog, ErrorState, Field, Input, LoadingRows, Select, Textarea, cx } from "@/components/ui";

type Sched = Row & { send_date: string; theme: string; status: string; brief: string; draft_deadline: string | null; content_author: string | null; asana_task_gid: string | null; owner_user_id: string | null };
type Cal = Row & { name: string; start_date: string; end_date: string; objectives: string; google_doc_id: string | null; emails?: Sched[] };
type Prod = Row & { subject: string; status: string; validation: { passed: boolean; checks: { check: string; passed: boolean; detail?: string; severity?: string }[] }; html?: string; crm_platform?: string; history: { at: string; action: string }[] };

export function EmailTab({ client }: { client: Client }) {
  return <div className="space-y-4"><Calendars client={client} /><Productions client={client} /></div>;
}

function Calendars({ client }: { client: Client }) {
  const me = useMe();
  const w = can(me.data, "email:write", client.organization_id, client.id);
  const cals = useApi<Cal[]>(["calendars", client.id], `/clients/${client.id}/email-calendars`);
  const [sel, setSel] = useState<string | null>(null);
  const calId = sel ?? cals.data?.[0]?.id ?? null;
  const [newOpen, setNewOpen] = useState(false);
  const [nf, setNf] = useState({ name: "", objectives: "", start_date: "", end_date: "" });
  const create = useAction(() => api<Cal>(`/clients/${client.id}/email-calendars`, { method: "POST", json: nf }),
    { success: "Calendar created", invalidate: [["calendars", client.id]], onSuccess: (c) => { setSel(c.id); setNewOpen(false); } });
  return (
    <Card title="Email calendars" actions={<>
      {cals.data?.length ? <Select aria-label="Calendar" className="w-56 py-1" value={calId ?? ""} onChange={(e) => setSel(e.target.value)}>{cals.data.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select> : null}
      {w && <Button size="sm" onClick={() => setNewOpen(true)}><CalendarPlus className="size-4" />New calendar</Button>}
    </>}>
      {cals.isLoading ? <LoadingRows /> : cals.error ? <ErrorState error={cals.error} /> : calId ? <CalendarView calId={calId} client={client} writable={w} /> : <p className="text-sm text-muted">No calendars yet.</p>}
      <Dialog open={newOpen} onOpenChange={setNewOpen} title="New email calendar">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(undefined); }}>
          <Field label="Name"><Input required minLength={2} value={nf.name} onChange={(e) => setNf({ ...nf, name: e.target.value })} /></Field>
          <Field label="Campaign objectives" hint="Approved planning inputs from the client."><Textarea value={nf.objectives} onChange={(e) => setNf({ ...nf, objectives: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Start"><Input type="date" required value={nf.start_date} onChange={(e) => setNf({ ...nf, start_date: e.target.value })} /></Field>
            <Field label="End"><Input type="date" required value={nf.end_date} onChange={(e) => setNf({ ...nf, end_date: e.target.value })} /></Field>
          </div>
          <Button type="submit" loading={create.isPending}>Create</Button>
        </form>
      </Dialog>
    </Card>
  );
}

function CalendarView({ calId, client, writable }: { calId: string; client: Client; writable: boolean }) {
  const q = useApi<Cal>(["calendar", calId], `/email-calendars/${calId}`);
  const [view, setView] = useState<"list" | "week" | "month">("month");
  const [planOpen, setPlanOpen] = useState(false);
  const [plan, setPlan] = useState({ sends_per_week: 2, themes: "", blackout: "" });
  const [proposal, setProposal] = useState<{ id: string; output: { slots: { send_date: string; theme: string; draft_deadline: string }[] } } | null>(null);
  const [editing, setEditing] = useState<Sched | null>(null);
  const inv = [["calendar", calId], ["overview", client.id], ["dashboard"]];
  const runPlan = useAction(() => api<typeof proposal>(`/email-calendars/${calId}/plan`, { method: "POST", json: {
    sends_per_week: plan.sends_per_week, themes: plan.themes.split("\n").map((s) => s.trim()).filter(Boolean),
    blackout_dates: plan.blackout.split(/[\s,]+/).filter(Boolean) } }), { onSuccess: (r) => setProposal(r) });
  const decide = useAction((approve: boolean) => api<{ created: number }>(`/agent-executions/${proposal!.id}/decision`, { method: "POST", json: { approve } }),
    { success: (r) => `${r.created} emails scheduled`, invalidate: inv, onSuccess: () => { setProposal(null); setPlanOpen(false); } });
  const exportDoc = useAction(() => api<{ google_doc_id: string; mode: string }>(`/email-calendars/${calId}/export-doc`, { method: "POST" }),
    { success: (r) => `Review doc created (${r.mode}): ${r.google_doc_id}`, invalidate: inv });
  if (q.isLoading) return <LoadingRows />;
  if (q.error) return <ErrorState error={q.error} />;
  const cal = q.data!;
  const emails = cal.emails ?? [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">{fmtDate(cal.start_date)} – {fmtDate(cal.end_date)} · {emails.length} emails {cal.google_doc_id && <>· review doc <code>{cal.google_doc_id}</code></>}</p>
        <div className="flex gap-1">
          {(["month", "week", "list"] as const).map((v) => <Button key={v} size="sm" variant={view === v ? "primary" : "secondary"} onClick={() => setView(v)}>{v}</Button>)}
          {writable && <Button size="sm" variant="secondary" onClick={() => setPlanOpen(true)}><Wand2 className="size-4" />Plan with AI</Button>}
          {writable && <Button size="sm" variant="secondary" loading={exportDoc.isPending} onClick={() => exportDoc.mutate(undefined)}><FileText className="size-4" />Export to Google Docs</Button>}
        </div>
      </div>
      {view === "list" ? (
        <DataTable rows={emails} searchKeys={["theme", "brief"]} filterKey="status" onRowClick={writable ? (r) => setEditing(r) : undefined} columns={[
          { key: "send_date", header: "Send date", sortable: true, render: (r) => fmtDate(r.send_date) },
          { key: "theme", header: "Theme" },
          { key: "draft_deadline", header: "Draft due", render: (r) => fmtDate(r.draft_deadline) },
          { key: "content_author", header: "Author", render: (r) => r.content_author ?? <span className="text-muted">unassigned</span> },
          { key: "status", header: "Status", render: (r) => <Badge>{r.status}</Badge> },
          { key: "asana_task_gid", header: "Asana", render: (r) => r.asana_task_gid ? <Badge tone="ok">linked</Badge> : "—" },
        ]} />
      ) : <CalendarGrid emails={emails} start={cal.start_date} mode={view} onPick={writable ? setEditing : undefined} />}

      <Dialog open={planOpen} onOpenChange={(o) => { setPlanOpen(o); if (!o) setProposal(null); }} title="AI calendar planning" wide
        description="The planner distributes your approved themes across dates and sets draft deadlines. Nothing is created until you approve. Email content remains human-authored.">
        {!proposal ? (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); runPlan.mutate(undefined); }}>
            <Field label="Sends per week"><Input type="number" min={1} max={7} value={plan.sends_per_week} onChange={(e) => setPlan({ ...plan, sends_per_week: Number(e.target.value) })} /></Field>
            <Field label="Approved themes (one per line)"><Textarea required value={plan.themes} onChange={(e) => setPlan({ ...plan, themes: e.target.value })} /></Field>
            <Field label="Blackout dates" hint="YYYY-MM-DD, comma separated"><Input value={plan.blackout} onChange={(e) => setPlan({ ...plan, blackout: e.target.value })} /></Field>
            <Button type="submit" loading={runPlan.isPending}>Generate proposal</Button>
          </form>
        ) : (
          <div className="space-y-3">
            <DataTable rows={proposal.output.slots.map((s, i) => ({ ...s, id: String(i) }))} columns={[
              { key: "send_date", header: "Send", render: (r) => fmtDate(r.send_date) }, { key: "theme", header: "Theme" },
              { key: "draft_deadline", header: "Draft due", render: (r) => fmtDate(r.draft_deadline) }]} />
            <div className="flex gap-2">
              <Button loading={decide.isPending} onClick={() => decide.mutate(true)}><CheckCircle2 className="size-4" />Approve & schedule</Button>
              <Button variant="secondary" onClick={() => decide.mutate(false)}>Reject</Button>
            </div>
          </div>
        )}
      </Dialog>
      {editing && <ScheduledEditor email={editing} client={client} onClose={() => setEditing(null)} invalidate={inv} />}
    </div>
  );
}

function CalendarGrid({ emails, start, mode, onPick }: { emails: Sched[]; start: string; mode: "week" | "month"; onPick?: (e: Sched) => void }) {
  const [offset, setOffset] = useState(0);
  const days = useMemo(() => {
    const base = new Date(`${start}T00:00:00`);
    if (mode === "month") { base.setDate(1); base.setMonth(base.getMonth() + offset); base.setDate(base.getDate() - base.getDay()); }
    else { base.setDate(base.getDate() - base.getDay() + offset * 7); }
    return Array.from({ length: mode === "month" ? 42 : 7 }, (_, i) => { const d = new Date(base); d.setDate(base.getDate() + i); return d; });
  }, [start, mode, offset]);
  const key = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const label = mode === "month" ? days[15].toLocaleDateString(undefined, { month: "long", year: "numeric" }) : `Week of ${days[0].toLocaleDateString()}`;
  return (
    <div>
      <div className="mb-2 flex items-center gap-2"><Button size="sm" variant="secondary" onClick={() => setOffset(offset - 1)} aria-label="Previous">‹</Button><span className="text-sm font-medium">{label}</span><Button size="sm" variant="secondary" onClick={() => setOffset(offset + 1)} aria-label="Next">›</Button></div>
      <div className="grid grid-cols-7 gap-px overflow-hidden rounded-md border border-border bg-border text-xs">
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => <div key={d} className="bg-panel-2 px-2 py-1 font-medium text-muted">{d}</div>)}
        {days.map((d) => (
          <div key={key(d)} className={cx("min-h-20 bg-panel p-1.5", mode === "week" && "min-h-40")}>
            <div className="mb-1 text-muted">{d.getDate()}</div>
            {emails.filter((e) => e.send_date === key(d)).map((e) => (
              <button key={e.id} onClick={() => onPick?.(e)} className="mb-1 block w-full truncate rounded bg-accent/10 px-1.5 py-0.5 text-left text-accent hover:bg-accent/20" title={`${e.theme} (${e.status})`}>{e.theme}</button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function ScheduledEditor({ email, client, onClose, invalidate }: { email: Sched; client: Client; onClose: () => void; invalidate: unknown[][] }) {
  const me = useMe();
  const [f, setF] = useState({ theme: email.theme, brief: email.brief, status: email.status, content_author: email.content_author ?? "", source_doc_id: (email.source_doc_id as string) ?? "" });
  const save = useAction(() => api(`/scheduled-emails/${email.id}`, { method: "PATCH", json: { ...f, content_author: f.content_author || null, source_doc_id: f.source_doc_id || null } }),
    { success: "Email updated", invalidate, onSuccess: onClose });
  const asana = useAction(() => api<{ asana_task_gid: string; duplicate: boolean }>(`/scheduled-emails/${email.id}/asana-handoff`, { method: "POST" }),
    { success: (r) => r.duplicate ? "Asana task already exists" : `Asana task ${r.asana_task_gid} created`, invalidate });
  const statuses = ["planned", "drafting", "in_review", ...(can(me.data, "email:approve", client.organization_id, client.id) ? ["approved"] : []), "produced"];
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={`${fmtDate(email.send_date)} — ${email.theme}`}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined); }}>
        <Field label="Theme"><Input value={f.theme} onChange={(e) => setF({ ...f, theme: e.target.value })} /></Field>
        <Field label="Content brief"><Textarea value={f.brief} onChange={(e) => setF({ ...f, brief: e.target.value })} /></Field>
        <Field label="Content author (human)" hint="Required before approval."><Input value={f.content_author} onChange={(e) => setF({ ...f, content_author: e.target.value })} /></Field>
        <Field label="Source Google Doc ID"><Input value={f.source_doc_id} onChange={(e) => setF({ ...f, source_doc_id: e.target.value })} /></Field>
        <Field label="Review status"><Select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>{statuses.map((s) => <option key={s}>{s}</option>)}</Select></Field>
        <div className="flex gap-2">
          <Button type="submit" loading={save.isPending}>Save</Button>
          <Button type="button" variant="secondary" loading={asana.isPending} onClick={() => asana.mutate(undefined)}><Send className="size-4" />Hand off to Asana</Button>
        </div>
      </form>
    </Dialog>
  );
}

function Productions({ client }: { client: Client }) {
  const me = useMe();
  const w = can(me.data, "email:write", client.organization_id, client.id);
  const q = useApi<Prod[]>(["productions", client.id], `/clients/${client.id}/productions`);
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  const [f, setF] = useState({ subject: "", preheader: "", source: "doc", google_doc_id: "mock-doc-spring-update", text: "", sender_name: client.name, sender_address: "", template: "standard" });
  const inv = [["productions", client.id], ["overview", client.id], ["dashboard"]];
  const create = useAction(() => api<Prod>(`/clients/${client.id}/productions`, { method: "POST", json: {
    subject: f.subject, preheader: f.preheader, sender_name: f.sender_name, sender_address: f.sender_address, template: f.template,
    ...(f.source === "doc" ? { google_doc_id: f.google_doc_id } : { text: f.text }) } }),
    { success: (r) => `Converted — ${r.validation.passed ? "validation passed" : "validation issues found"}`, invalidate: inv, onSuccess: (r) => { setOpen(false); setDetail(r.id); } });
  return (
    <Card title="Email production pipeline" actions={w && <Button size="sm" onClick={() => setOpen(true)}><FileText className="size-4" />New production</Button>}>
      {q.isLoading ? <LoadingRows /> : q.error ? <ErrorState error={q.error} /> : (
        <DataTable rows={q.data ?? []} searchKeys={["subject"]} filterKey="status" onRowClick={(r) => setDetail(r.id)} columns={[
          { key: "subject", header: "Subject", render: (r) => <span className="font-medium">{r.subject}</span> },
          { key: "validation", header: "Validation", render: (r) => <Badge tone={r.validation?.passed ? "ok" : "bad"}>{r.validation?.passed ? "passed" : "issues"}</Badge> },
          { key: "crm_platform", header: "Handoff", render: (r) => r.crm_platform ?? "—" },
          { key: "status", header: "Status", render: (r) => <Badge>{r.status}</Badge> },
          { key: "created_at", header: "Created", sortable: true, render: (r) => fmtDate(r.created_at as string) },
        ]} />
      )}
      <Dialog open={open} onOpenChange={setOpen} title="Convert approved content to email HTML" wide>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(undefined); }}>
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Subject"><Input required value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} /></Field>
            <Field label="Preheader"><Input value={f.preheader} onChange={(e) => setF({ ...f, preheader: e.target.value })} /></Field>
            <Field label="Sender name"><Input required value={f.sender_name} onChange={(e) => setF({ ...f, sender_name: e.target.value })} /></Field>
            <Field label="Sender address"><Input required type="email" value={f.sender_address} onChange={(e) => setF({ ...f, sender_address: e.target.value })} /></Field>
            <Field label="Source"><Select value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })}><option value="doc">Approved Google Doc</option><option value="text">Paste approved copy</option></Select></Field>
            <Field label="Template"><Select value={f.template} onChange={(e) => setF({ ...f, template: e.target.value })}><option>standard</option><option>minimal</option></Select></Field>
          </div>
          {f.source === "doc"
            ? <Field label="Google Doc ID" hint="Without Google OAuth configured, the mock adapter provides 'mock-doc-spring-update'."><Input required value={f.google_doc_id} onChange={(e) => setF({ ...f, google_doc_id: e.target.value })} /></Field>
            : <Field label="Human-authored copy" hint="Supports # headings, - bullets, **bold**, [text](https://link)"><Textarea required className="min-h-40" value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} /></Field>}
          <Button type="submit" loading={create.isPending}>Convert & validate</Button>
        </form>
      </Dialog>
      {detail && <ProductionDetail id={detail} client={client} onClose={() => setDetail(null)} invalidate={inv} />}
    </Card>
  );
}

function ProductionDetail({ id, client, onClose, invalidate }: { id: string; client: Client; onClose: () => void; invalidate: unknown[][] }) {
  const me = useMe();
  const q = useApi<Prod>(["production", id], `/productions/${id}`);
  const [seeds, setSeeds] = useState("");
  const [platform, setPlatform] = useState("action_network");
  const inv = [...invalidate, ["production", id]];
  const approve = useAction(() => api(`/productions/${id}/approve`, { method: "POST" }), { success: "Production approved", invalidate: inv });
  const test = useAction(() => api(`/productions/${id}/prepare-test`, { method: "POST", json: { recipients: seeds.split(/[\s,]+/).filter(Boolean) } }), { success: "Test send prepared", invalidate: inv });
  const handoff = useAction(() => api<{ reference: string; mode: string }>(`/productions/${id}/handoff`, { method: "POST", json: { platform } }),
    { success: (r) => `Draft created (${r.mode}): ${r.reference}`, invalidate: inv });
  const canApprove = can(me.data, "email:approve", client.organization_id, client.id);
  const p = q.data;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={p?.subject ?? "Production"} wide>
      {!p ? <LoadingRows /> : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-3">
            <div className="flex items-center gap-2"><Badge>{p.status}</Badge><Button size="sm" variant="secondary" onClick={() => openAuthed(`/productions/${id}/preview`)}><Eye className="size-4" />Open preview</Button></div>
            <Checks checks={p.validation.checks} />
            {p.status === "validated" && canApprove && <Button loading={approve.isPending} onClick={() => approve.mutate(undefined)}><CheckCircle2 className="size-4" />Approve production</Button>}
            {["approved", "test_prepared"].includes(p.status) && (
              <div className="space-y-2 rounded-md border border-border p-3">
                <Field label="Test-send seed addresses"><Input value={seeds} onChange={(e) => setSeeds(e.target.value)} placeholder="qa@example.org" /></Field>
                <Button size="sm" variant="secondary" loading={test.isPending} onClick={() => test.mutate(undefined)}>Prepare test send</Button>
                {canApprove && <>
                  <Field label="CRM / email platform"><Select value={platform} onChange={(e) => setPlatform(e.target.value)}><option value="action_network">Action Network (draft)</option><option value="actionkit">ActionKit (draft)</option><option value="manual">Manual export</option></Select></Field>
                  <Button size="sm" loading={handoff.isPending} onClick={() => handoff.mutate(undefined)}><Send className="size-4" />Hand off as draft</Button>
                  <p className="text-xs text-muted">Creates a draft only. Sending is always performed by a human in the platform.</p>
                </>}
              </div>
            )}
            <div><p className="mb-1 text-xs font-medium text-muted">History</p><ul className="text-xs text-muted">{p.history.map((h, i) => <li key={i}>{fmtDate(h.at)} · {h.action}</li>)}</ul></div>
          </div>
          <iframe title="Email preview" sandbox="" srcDoc={p.html} className="h-[520px] w-full rounded-md border border-border bg-white" />
        </div>
      )}
    </Dialog>
  );
}
