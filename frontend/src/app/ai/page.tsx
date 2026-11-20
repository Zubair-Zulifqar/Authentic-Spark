"use client";
import { useState } from "react";
import { Bot, Play } from "lucide-react";
import { api, fmtDate } from "@/lib/api";
import { useAction, useApi, useOrgId } from "@/lib/hooks";
import type { Client, Row } from "@/lib/types";
import { Badge, Button, Card, DataTable, ErrorState, Field, LoadingRows, PageHeader, Select, Textarea } from "@/components/ui";

type Agent = { key: string; name: string; responsibilities: string; permission: string; requires_approval: boolean; tools: string[]; input_schema: { properties: Record<string, { type?: string }>; required?: string[] } };
type Exec = Row & { agent: string; status: string; provider: string; model: string; duration_ms: number; output: unknown; error: string | null; prompt_tokens: number; completion_tokens: number };

const SAMPLES: Record<string, string> = {
  proofreader: '{"text": "We will recieve the the volunteer forms ."}',
  unsubscribe_classifier: '{"text": "please take me off this list"}',
  task_extractor: '{"text": "- Send brief to design 2026-12-01\\n- Confirm vendor list source"}',
  summarizer: '{"text": "Paste a document here. The agent summarizes it for staff."}',
  data_classifier: '{"items": ["invoice_march.pdf", "volunteer_list.csv"], "categories": ["invoice", "list", "other"]}',
  email_calendar_planner: '{"start_date": "2026-12-01", "end_date": "2026-12-31", "sends_per_week": 2, "themes": ["Program update", "Year-end report"]}',
};

export default function AiHub() {
  const orgId = useOrgId();
  const agents = useApi<Agent[]>(["agents"], "/agents");
  const clients = useApi<Client[]>(["clients", orgId], orgId ? `/organizations/${orgId}/clients` : null);
  const execs = useApi<{ executions: Exec[]; usage: { agent: string; runs: number; prompt_tokens: number; completion_tokens: number }[] }>(["execs", orgId], orgId ? `/organizations/${orgId}/agent-executions` : null);
  const [sel, setSel] = useState<string>("proofreader");
  const [clientId, setClientId] = useState("");
  const [input, setInput] = useState(SAMPLES.proofreader);
  const [result, setResult] = useState<Exec | null>(null);
  const run = useAction(() => {
    let parsed: unknown;
    try { parsed = JSON.parse(input); } catch { throw new Error("Input must be valid JSON"); }
    return api<Exec>(`/agents/${sel}/run`, { method: "POST", json: { organization_id: orgId, client_id: clientId || null, input: parsed } });
  }, { success: (r) => `Agent ${r.status}`, invalidate: [["execs", orgId]], onSuccess: setResult });
  const agent = agents.data?.find((a) => a.key === sel);
  return (
    <>
      <PageHeader title="AI operations hub" subtitle="Administrative agents with defined schemas, permissions, audit logs and approval gates. Agents never write political persuasion or profile individuals." />
      {agents.isLoading ? <LoadingRows /> : agents.error ? <ErrorState error={agents.error} /> : (
        <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <Card title="Agents">
            <ul className="space-y-1">
              {agents.data!.map((a) => (
                <li key={a.key}><button onClick={() => { setSel(a.key); setInput(SAMPLES[a.key] ?? "{}"); setResult(null); }}
                  className={`w-full rounded-md px-2 py-1.5 text-left text-sm ${sel === a.key ? "bg-accent/10 text-accent" : "hover:bg-panel-2"}`}>
                  <Bot className="mr-1.5 inline size-4" />{a.name}</button></li>
              ))}
            </ul>
          </Card>
          <div className="space-y-4">
            {agent && <Card title={agent.name}>
              <p className="text-sm">{agent.responsibilities}</p>
              <div className="mt-2 flex flex-wrap gap-2 text-xs"><Badge tone="muted">{`permission ${agent.permission}`}</Badge>{agent.requires_approval && <Badge tone="warn">requires approval</Badge>}{agent.tools.map((t) => <Badge key={t} tone="info">{`tool ${t}`}</Badge>)}</div>
              <p className="mt-2 text-xs text-muted">Inputs: {Object.keys(agent.input_schema.properties).join(", ")}</p>
              <form className="mt-3 space-y-3" onSubmit={(e) => { e.preventDefault(); run.mutate(undefined); }}>
                <Field label="Client context (optional)"><Select value={clientId} onChange={(e) => setClientId(e.target.value)}><option value="">Agency-level</option>{(clients.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
                <Field label="Input (JSON)"><Textarea className="min-h-32 font-mono text-xs" value={input} onChange={(e) => setInput(e.target.value)} /></Field>
                <Button type="submit" loading={run.isPending}><Play className="size-4" />Run agent</Button>
              </form>
              {result && <pre className="mt-3 max-h-80 overflow-auto rounded-md bg-panel-2 p-3 text-xs">{JSON.stringify({ status: result.status, provider: result.provider, output: result.output, error: result.error }, null, 2)}</pre>}
            </Card>}
            <Card title="Usage">
              <div className="flex flex-wrap gap-2">{(execs.data?.usage ?? []).map((u) => <Badge key={u.agent} tone="muted">{`${u.agent}: ${u.runs} runs · ${u.prompt_tokens + u.completion_tokens} tokens`}</Badge>)}</div>
            </Card>
            <Card title="Execution history">
              <DataTable rows={execs.data?.executions ?? []} filterKey="status" columns={[
                { key: "created_at", header: "When", render: (r) => fmtDate(String(r.created_at)) },
                { key: "agent", header: "Agent" }, { key: "provider", header: "Provider" },
                { key: "duration_ms", header: "ms" }, { key: "status", header: "Status", render: (r) => <Badge>{r.status}</Badge> },
                { key: "error", header: "Error", render: (r) => r.error ?? "" },
              ]} />
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
