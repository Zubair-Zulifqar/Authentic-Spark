"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useAction, useApi, useMe, useOrgId } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import { Badge, Button, Card, Dialog, ErrorState, Field, Input, LoadingRows, PageHeader, Textarea } from "@/components/ui";

type Integration = { provider: string; mode: string; status: string; config: Record<string, unknown>; last_error: string | null };
const OAUTH: Record<string, string> = { google_workspace: "google_docs", google_ads: "google_ads", quickbooks: "quickbooks" };
const TESTABLE = new Set(["zerobounce", "ngpvan", "google_ads"]);

export default function IntegrationsPage() {
  const orgId = useOrgId();
  const me = useMe();
  const w = can(me.data, "integrations:write", orgId);
  const q = useApi<Integration[]>(["integrations", orgId], orgId ? `/organizations/${orgId}/integrations` : null);
  const [cfg, setCfg] = useState<{ provider: string; config: string; secret_ref: string } | null>(null);
  const test = useAction((p: string) => api<{ status: string; mode: string; error: string | null }>(`/organizations/${orgId}/integrations/${p}/test`, { method: "POST" }),
    { success: (r) => `${r.status} (${r.mode})${r.error ? `: ${r.error}` : ""}` });
  const oauth = useAction((p: string) => api<{ authorization_url: string }>(`/oauth/${p}/start?organization_id=${orgId}`), { onSuccess: (r) => { window.location.href = r.authorization_url; } });
  const save = useAction(() => api(`/organizations/${orgId}/integrations`, { method: "POST", json: { provider: cfg!.provider, config: JSON.parse(cfg!.config || "{}"), secret_ref: cfg!.secret_ref || null } }),
    { success: "Integration configured", invalidate: [["integrations", orgId]], onSuccess: () => setCfg(null) });
  return (
    <>
      <PageHeader title="Integrations" subtitle="Credentials live in Secret Manager; the platform stores only references and non-secret settings." />
      {q.isLoading ? <LoadingRows /> : q.error ? <ErrorState error={q.error} /> : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {q.data!.map((i) => (
            <Card key={i.provider} title={i.provider.replace(/_/g, " ")} actions={<Badge>{i.mode === "mock" ? "mock" : i.status}</Badge>}>
              <p className="text-xs text-muted">{i.mode === "mock" ? "Development mock adapter active — configure credentials to go live." : i.mode === "disabled" ? "Disabled until a token is configured." : "Live adapter."}</p>
              {Object.keys(i.config).length > 0 && <pre className="mt-2 overflow-auto rounded bg-panel-2 p-2 text-xs">{JSON.stringify(i.config)}</pre>}
              <div className="mt-3 flex flex-wrap gap-2">
                {TESTABLE.has(i.provider) && <Button size="sm" variant="secondary" onClick={() => test.mutate(i.provider)}>Test connection</Button>}
                {w && OAUTH[i.provider] && <Button size="sm" variant="secondary" onClick={() => oauth.mutate(OAUTH[i.provider])}>Connect with OAuth</Button>}
                {w && <Button size="sm" variant="ghost" onClick={() => setCfg({ provider: i.provider, config: JSON.stringify(i.config), secret_ref: "" })}>Configure</Button>}
              </div>
            </Card>
          ))}
        </div>
      )}
      {cfg && (
        <Dialog open onOpenChange={(o) => !o && setCfg(null)} title={`Configure ${cfg.provider}`}>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined); }}>
            <Field label="Non-secret settings (JSON)" hint="Allowed keys: channel_ids, project_gid, workspace_gid, customer_id, realm_id, folder_id, instance, committee_id, notes"><Textarea className="font-mono text-xs" value={cfg.config} onChange={(e) => setCfg({ ...cfg, config: e.target.value })} /></Field>
            <Field label="Secret Manager reference" hint="projects/<project>/secrets/<name>"><Input value={cfg.secret_ref} onChange={(e) => setCfg({ ...cfg, secret_ref: e.target.value })} /></Field>
            <Button type="submit" loading={save.isPending}>Save</Button>
          </form>
        </Dialog>
      )}
    </>
  );
}
