"use client";
import * as React from "react";
import * as RDialog from "@radix-ui/react-dialog";
import clsx from "clsx";
import { X, Search, AlertTriangle, Inbox } from "lucide-react";

export const cx = clsx;

export function Button({ variant = "primary", size = "md", className, loading, ...p }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md"; loading?: boolean }) {
  return (
    <button
      {...p}
      disabled={p.disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition disabled:opacity-50 disabled:cursor-not-allowed",
        size === "sm" ? "h-8 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        variant === "primary" && "bg-accent text-accent-fg hover:opacity-90",
        variant === "secondary" && "border border-border bg-panel hover:bg-panel-2",
        variant === "ghost" && "hover:bg-panel-2",
        variant === "danger" && "bg-bad text-white hover:opacity-90",
        className,
      )}
    >
      {loading ? <span className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" /> : null}
      {p.children}
    </button>
  );
}

export function Card({ title, actions, children, className }: { title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-lg border border-border bg-panel", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          <div className="flex gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const TONES: Record<string, string> = {
  ok: "text-ok bg-ok/10 border-ok/30", warn: "text-warn bg-warn/10 border-warn/30",
  bad: "text-bad bg-bad/10 border-bad/30", info: "text-accent bg-accent/10 border-accent/30", muted: "text-muted bg-panel-2 border-border",
};
const STATUS_TONE: Record<string, keyof typeof TONES> = {
  active: "ok", approved: "ok", valid: "ok", verified: "ok", paid: "ok", succeeded: "ok", delivered: "ok", handed_off: "ok",
  produced: "ok", pass: "ok", validated: "info", provisioned: "ok", live: "ok", connected: "ok", configured: "ok",
  pending_approval: "warn", in_review: "warn", needs_review: "warn", awaiting_approval: "warn", risky: "warn", warn: "warn",
  partially_paid: "warn", queued: "warn", verifying: "warn", drafting: "info", issued: "info", mock: "muted", test_prepared: "info",
  failed: "bad", invalid: "bad", rejected: "bad", fail: "bad", error: "bad", suppressed: "bad", open: "warn",
};
export function Badge({ children, tone }: { children: React.ReactNode; tone?: keyof typeof TONES }) {
  const t = tone ?? STATUS_TONE[String(children)] ?? "muted";
  return <span className={cx("inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap", TONES[t])}>{String(children).replace(/_/g, " ")}</span>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded bg-panel-2", className ?? "h-4 w-full")} />;
}

export function LoadingRows({ rows = 5 }: { rows?: number }) {
  return <div className="space-y-2" aria-busy="true">{Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-8 w-full" />)}</div>;
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-bad/30 bg-bad/5 p-3 text-sm">
      <AlertTriangle className="mt-0.5 size-4 text-bad" />
      <div className="flex-1"><p className="font-medium text-bad">Something went wrong</p><p className="text-muted">{msg}</p></div>
      {onRetry && <Button size="sm" variant="secondary" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center">
      <Inbox className="size-6 text-muted" />
      <p className="text-sm font-medium">{title}</p>
      {hint && <p className="max-w-sm text-xs text-muted">{hint}</p>}
      {action}
    </div>
  );
}

export function Dialog({ open, onOpenChange, title, description, children, wide }:
  { open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <RDialog.Content className={cx("fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-panel p-5 shadow-xl", wide ? "max-w-3xl" : "max-w-lg")}>
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <RDialog.Title className="text-base font-semibold">{title}</RDialog.Title>
              {description ? <RDialog.Description className="mt-1 text-sm text-muted">{description}</RDialog.Description> : <RDialog.Description className="sr-only">{title}</RDialog.Description>}
            </div>
            <RDialog.Close aria-label="Close" className="rounded p-1 hover:bg-panel-2"><X className="size-4" /></RDialog.Close>
          </div>
          {children}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1 text-sm">
      <span className="font-medium">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted">{hint}</span>}
    </label>
  );
}

const inputCls = "w-full rounded-md border border-border px-2.5 py-1.5 text-sm placeholder:text-muted";
export const Input = (p: React.InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cx(inputCls, p.className)} />;
export const Textarea = (p: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={cx(inputCls, "min-h-24", p.className)} />;
export const Select = (p: React.SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cx(inputCls, p.className)} />;

export type Column<T> = { key: string; header: string; render?: (row: T) => React.ReactNode; sortable?: boolean; className?: string };

export function DataTable<T extends Record<string, unknown>>({ rows, columns, searchKeys, filterKey, filterOptions, onRowClick, empty }:
  { rows: T[]; columns: Column<T>[]; searchKeys?: string[]; filterKey?: string; filterOptions?: string[]; onRowClick?: (r: T) => void; empty?: React.ReactNode }) {
  const [q, setQ] = React.useState("");
  const [filter, setFilter] = React.useState("");
  const [sort, setSort] = React.useState<{ key: string; dir: 1 | -1 } | null>(null);
  const shown = React.useMemo(() => {
    let r = rows;
    if (q && searchKeys) r = r.filter((x) => searchKeys.some((k) => String(x[k] ?? "").toLowerCase().includes(q.toLowerCase())));
    if (filter && filterKey) r = r.filter((x) => String(x[filterKey]) === filter);
    if (sort) r = [...r].sort((a, b) => (String(a[sort.key] ?? "") > String(b[sort.key] ?? "") ? sort.dir : -sort.dir));
    return r;
  }, [rows, q, filter, sort, searchKeys, filterKey]);
  return (
    <div className="space-y-3">
      {(searchKeys || filterKey) && (
        <div className="flex flex-wrap gap-2">
          {searchKeys && (
            <div className="relative min-w-48 flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-muted" />
              <Input aria-label="Search" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} className="pl-8" />
            </div>
          )}
          {filterKey && (
            <Select aria-label="Filter by status" value={filter} onChange={(e) => setFilter(e.target.value)} className="w-44">
              <option value="">All statuses</option>
              {(filterOptions ?? Array.from(new Set(rows.map((r) => String(r[filterKey]))))).map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
            </Select>
          )}
        </div>
      )}
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="bg-panel-2 text-left text-xs text-muted">
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={cx("px-3 py-2 font-medium", c.className)}>
                  {c.sortable ? (
                    <button className="hover:text-text" onClick={() => setSort((s) => ({ key: c.key, dir: s?.key === c.key && s.dir === 1 ? -1 : 1 }))}>
                      {c.header}{sort?.key === c.key ? (sort.dir === 1 ? " ↑" : " ↓") : ""}
                    </button>
                  ) : c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={String(r.id ?? i)} onClick={onRowClick ? () => onRowClick(r) : undefined}
                className={cx("border-t border-border", onRowClick && "cursor-pointer hover:bg-panel-2")}>
                {columns.map((c) => <td key={c.key} className={cx("px-3 py-2 align-top", c.className)}>{c.render ? c.render(r) : String(r[c.key] ?? "—")}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
        {shown.length === 0 && (empty ?? <Empty title="No records" hint={q || filter ? "Try clearing search or filters." : undefined} />)}
      </div>
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-border bg-panel p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      <div className="flex flex-wrap gap-2">{actions}</div>
    </div>
  );
}

export function Checks({ checks }: { checks: { check: string; passed: boolean; detail?: unknown; severity?: string }[] }) {
  return (
    <ul className="space-y-1 text-sm">
      {checks.map((c) => (
        <li key={c.check} className="flex items-start gap-2">
          <Badge tone={c.passed ? "ok" : c.severity === "warning" ? "warn" : "bad"}>{c.passed ? "pass" : c.severity === "warning" ? "warn" : "fail"}</Badge>
          <span className="font-medium">{c.check.replace(/_/g, " ")}</span>
          {c.detail ? <span className="truncate text-muted">{typeof c.detail === "string" ? c.detail : JSON.stringify(c.detail).slice(0, 120)}</span> : null}
        </li>
      ))}
    </ul>
  );
}
