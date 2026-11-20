"use client";
import { useState } from "react";
import { ImagePlus } from "lucide-react";
import { api } from "@/lib/api";
import { useAction, useApi, useMe } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Client, Row } from "@/lib/types";
import { Badge, Button, Card, Checks, DataTable, Dialog, ErrorState, Field, Input, LoadingRows, Select, Textarea } from "@/components/ui";

type Creative = Row & { name: string; platform: string; format: string; status: string; version: number; headlines: string[]; descriptions: string[]; primary_text: string; disclaimer: string; is_political: boolean; tags: string[]; asset_uri: string | null; checks: { passed: boolean; checks: { check: string; passed: boolean; detail?: unknown }[] } };
const FORMATS: Record<string, string[]> = { google_ads: ["responsive_search", "responsive_display"], meta: ["single_image", "video"] };

export function AdsTab({ client }: { client: Client }) {
  const me = useMe();
  const w = can(me.data, "ads:write", client.organization_id, client.id);
  const q = useApi<Creative[]>(["ads", client.id], `/clients/${client.id}/ad-creatives`);
  const [edit, setEdit] = useState<Creative | "new" | null>(null);
  const gads = useApi<{ mode: string; campaigns: Row[] }>(["gads", client.id], (client.settings as Record<string, unknown>)?.google_ads_customer_id ? `/clients/${client.id}/google-ads/campaigns` : null);
  return (
    <div className="space-y-4">
      <Card title="Ad creatives" actions={w && <Button size="sm" onClick={() => setEdit("new")}><ImagePlus className="size-4" />New creative</Button>}>
        {q.isLoading ? <LoadingRows /> : q.error ? <ErrorState error={q.error} /> : (
          <DataTable rows={q.data ?? []} searchKeys={["name"]} filterKey="status" onRowClick={(r) => setEdit(r)} columns={[
            { key: "name", header: "Creative", render: (r) => <span className="font-medium">{r.name}</span> },
            { key: "platform", header: "Platform" }, { key: "format", header: "Format" },
            { key: "version", header: "Ver." },
            { key: "checks", header: "Checks", render: (r) => <Badge tone={r.checks?.passed ? "ok" : "bad"}>{r.checks?.passed ? "pass" : "issues"}</Badge> },
            { key: "status", header: "Status", render: (r) => <Badge>{r.status}</Badge> },
          ]} />
        )}
      </Card>
      <Card title="Google Ads campaigns (read-only reporting)">
        {!gads.data && !gads.isLoading ? <p className="text-sm text-muted">Set google_ads_customer_id in client settings to enable reporting.</p> : gads.isLoading ? <LoadingRows rows={2} /> : (
          <>
            <Badge>{gads.data!.mode}</Badge>
            <DataTable rows={gads.data!.campaigns} columns={[{ key: "name", header: "Campaign" }, { key: "status", header: "Status" }, { key: "impressions", header: "Impr." }, { key: "clicks", header: "Clicks" }, { key: "cost", header: "Cost" }]} />
            <p className="mt-2 text-xs text-muted">Activation and budget changes are not performed by this platform.</p>
          </>
        )}
      </Card>
      {edit && <CreativeEditor creative={edit === "new" ? null : edit} client={client} onClose={() => setEdit(null)} />}
    </div>
  );
}

function CreativeEditor({ creative, client, onClose }: { creative: Creative | null; client: Client; onClose: () => void }) {
  const me = useMe();
  const w = can(me.data, "ads:write", client.organization_id, client.id);
  const approver = can(me.data, "ads:approve", client.organization_id, client.id) || (creative?.is_political && can(me.data, "compliance:approve", client.organization_id, client.id));
  const [f, setF] = useState({
    platform: creative?.platform ?? "google_ads", format: creative?.format ?? "responsive_search", name: creative?.name ?? "",
    headlines: (creative?.headlines ?? []).join("\n"), descriptions: (creative?.descriptions ?? []).join("\n"), primary_text: creative?.primary_text ?? "",
    disclaimer: creative?.disclaimer ?? "", is_political: creative?.is_political ?? false, asset_uri: creative?.asset_uri ?? "", tags: (creative?.tags ?? []).join(", "),
  });
  const [current, setCurrent] = useState<Creative | null>(creative);
  const inv = [["ads", client.id], ["dashboard"]];
  const payload = () => ({ name: f.name, headlines: f.headlines.split("\n").filter(Boolean), descriptions: f.descriptions.split("\n").filter(Boolean),
    primary_text: f.primary_text, disclaimer: f.disclaimer, asset_uri: f.asset_uri || null, tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean) });
  const save = useAction(() => current
    ? api<Creative>(`/ad-creatives/${current.id}`, { method: "PATCH", json: payload() })
    : api<Creative>(`/clients/${client.id}/ad-creatives`, { method: "POST", json: { ...payload(), platform: f.platform, format: f.format, is_political: f.is_political } }),
    { success: (r) => `Saved v${r.version} — checks ${r.checks.passed ? "passed" : "found issues"}`, invalidate: inv, onSuccess: setCurrent });
  const submit = useAction(() => api<Creative>(`/ad-creatives/${current!.id}/submit`, { method: "POST" }), { success: "Submitted for review", invalidate: inv, onSuccess: setCurrent });
  const decide = useAction((approve: boolean) => api<Creative>(`/ad-creatives/${current!.id}/decision`, { method: "POST", json: { approve } }), { success: "Decision recorded", invalidate: inv, onSuccess: setCurrent });
  const versions = useApi<Row[]>(["adv", current?.id], current ? `/ad-creatives/${current.id}/versions` : null);
  const locked = current?.status === "approved";
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={current ? `${current.name} (v${current.version})` : "New creative"} wide
      description="Copy is supplied by staff. Political ads require a 'Paid for by' disclaimer and authorized approval.">
      <div className="grid gap-4 lg:grid-cols-2">
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined); }}>
          {!current && <div className="grid grid-cols-2 gap-2">
            <Field label="Platform"><Select value={f.platform} onChange={(e) => setF({ ...f, platform: e.target.value, format: FORMATS[e.target.value][0] })}><option value="google_ads">Google Ads</option><option value="meta">Meta</option></Select></Field>
            <Field label="Format"><Select value={f.format} onChange={(e) => setF({ ...f, format: e.target.value })}>{FORMATS[f.platform].map((x) => <option key={x}>{x}</option>)}</Select></Field>
          </div>}
          <Field label="Name"><Input required disabled={locked} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Headlines (one per line)"><Textarea disabled={locked} value={f.headlines} onChange={(e) => setF({ ...f, headlines: e.target.value })} /></Field>
          <Field label="Descriptions (one per line)"><Textarea disabled={locked} value={f.descriptions} onChange={(e) => setF({ ...f, descriptions: e.target.value })} /></Field>
          {f.platform === "meta" && <Field label="Primary text"><Textarea disabled={locked} value={f.primary_text} onChange={(e) => setF({ ...f, primary_text: e.target.value })} /></Field>}
          {!current && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_political} onChange={(e) => setF({ ...f, is_political: e.target.checked })} />Political / issue ad</label>}
          <Field label="Disclaimer"><Input disabled={locked} value={f.disclaimer} onChange={(e) => setF({ ...f, disclaimer: e.target.value })} /></Field>
          <Field label="Asset URI (Cloud Storage)"><Input disabled={locked} value={f.asset_uri} onChange={(e) => setF({ ...f, asset_uri: e.target.value })} /></Field>
          <Field label="Tags / asset description"><Input disabled={locked} value={f.tags} onChange={(e) => setF({ ...f, tags: e.target.value })} /></Field>
          {w && !locked && <Button type="submit" loading={save.isPending}>Save & run checks</Button>}
        </form>
        <div className="space-y-3">
          {current && <>
            <div className="flex gap-2"><Badge>{current.status}</Badge></div>
            <Checks checks={current.checks.checks} />
            <div className="flex flex-wrap gap-2">
              {w && current.status === "draft" && <Button size="sm" disabled={!current.checks.passed} onClick={() => submit.mutate(undefined)}>Submit for review</Button>}
              {approver && current.status === "in_review" && <><Button size="sm" onClick={() => decide.mutate(true)}>Approve</Button><Button size="sm" variant="danger" onClick={() => decide.mutate(false)}>Reject</Button></>}
            </div>
            <div><p className="text-xs font-medium text-muted">Version history</p><ul className="text-xs text-muted">{(versions.data ?? []).map((v) => <li key={v.id}>v{String(v.version)} · {new Date(String(v.created_at)).toLocaleString()}</li>)}</ul></div>
          </>}
        </div>
      </div>
    </Dialog>
  );
}
