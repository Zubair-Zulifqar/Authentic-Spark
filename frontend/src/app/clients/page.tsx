"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Plus } from "lucide-react";
import { api } from "@/lib/api";
import { useAction, useApi, useMe, useOrgId } from "@/lib/hooks";
import { can } from "@/lib/permissions";
import type { Client } from "@/lib/types";
import { Badge, Button, Card, DataTable, Dialog, ErrorState, Field, Input, LoadingRows, PageHeader, Select } from "@/components/ui";

export default function ClientsPage() {
  const orgId = useOrgId();
  const me = useMe();
  const router = useRouter();
  const q = useApi<Client[]>(["clients", orgId], orgId ? `/organizations/${orgId}/clients` : null);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", client_type: "nonprofit" });
  const create = useAction((v: typeof form) => api<Client>(`/organizations/${orgId}/clients`, { method: "POST", json: v }), {
    success: "Client created", invalidate: [["clients"], ["dashboard"]], onSuccess: (c) => { setOpen(false); router.push(`/clients/${c.id}`); },
  });
  return (
    <>
      <PageHeader title="Clients" subtitle="Each client has an isolated operational workspace."
        actions={can(me.data, "clients:write", orgId) && <Button onClick={() => setOpen(true)}><Plus className="size-4" />New client</Button>} />
      <Card>
        {q.isLoading ? <LoadingRows /> : q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : (
          <DataTable rows={q.data ?? []} searchKeys={["name"]} filterKey="status" onRowClick={(r) => router.push(`/clients/${r.id}`)}
            columns={[
              { key: "name", header: "Name", sortable: true, render: (r) => <span className="font-medium">{r.name}</span> },
              { key: "client_type", header: "Type", render: (r) => <Badge tone="muted">{r.client_type}</Badge> },
              { key: "status", header: "Status", render: (r) => <Badge>{r.status}</Badge> },
              { key: "pinned_modules", header: "Pinned modules", render: (r) => (r.pinned_modules ?? []).join(", ") },
            ]} />
        )}
      </Card>
      <Dialog open={open} onOpenChange={setOpen} title="New client">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(form); }}>
          <Field label="Name"><Input required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Type">
            <Select value={form.client_type} onChange={(e) => setForm({ ...form, client_type: e.target.value })}>
              {["nonprofit", "campaign", "pac", "advocacy", "business"].map((t) => <option key={t}>{t}</option>)}
            </Select>
          </Field>
          <Button type="submit" loading={create.isPending}>Create</Button>
        </form>
      </Dialog>
    </>
  );
}
