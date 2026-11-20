"use client";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, formatError } from "@/lib/api";
import { Button, Card, Field, Input } from "./ui";
import { toast } from "./ui/toast";

export function Onboarding() {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  return (
    <div className="mx-auto mt-20 max-w-md px-4">
      <Card title="Create your agency workspace">
        <form className="space-y-3" onSubmit={async (e) => {
          e.preventDefault(); setBusy(true);
          try { await api("/organizations", { method: "POST", json: { name } }); qc.invalidateQueries({ queryKey: ["me"] }); }
          catch (err) { toast.error("Could not create organization", formatError(err)); } finally { setBusy(false); }
        }}>
          <p className="text-sm text-muted">You are not a member of any organization yet. Create one (you become its administrator) or ask an admin to invite you.</p>
          <Field label="Agency name"><Input required minLength={2} value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Button type="submit" loading={busy}>Create organization</Button>
        </form>
      </Card>
    </div>
  );
}
