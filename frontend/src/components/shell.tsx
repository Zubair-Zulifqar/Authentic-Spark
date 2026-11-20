"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard, Building2, Flag, Mail, Users, MessageSquare, Megaphone, Bot, Receipt, ShieldCheck, Plug,
  BarChart3, Settings, LogOut, Moon, Sun, Menu, Sparkles,
} from "lucide-react";
import { useAuth, signOut, AUTH_MODE } from "@/lib/auth";
import { useMe, useOrgId } from "@/lib/hooks";
import { useUI } from "@/lib/store";
import { canAnyClient } from "@/lib/permissions";
import { Button, cx, ErrorState, Skeleton } from "./ui";
import { LoginScreen } from "./login";
import { Onboarding } from "./onboarding";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard, perm: "clients:read" },
  { href: "/clients", label: "Clients", icon: Building2, perm: "clients:read" },
  { href: "/m/campaigns", label: "Campaigns", icon: Flag, perm: "campaigns:read" },
  { href: "/m/email", label: "Email operations", icon: Mail, perm: "email:read" },
  { href: "/m/contacts", label: "Contact lists", icon: Users, perm: "contacts:read" },
  { href: "/m/sms", label: "SMS", icon: MessageSquare, perm: "sms:read" },
  { href: "/m/ads", label: "Advertising", icon: Megaphone, perm: "ads:read" },
  { href: "/ai", label: "AI agents", icon: Bot, perm: "ai:read" },
  { href: "/m/billing", label: "Invoicing", icon: Receipt, perm: "billing:read" },
  { href: "/m/compliance", label: "Compliance", icon: ShieldCheck, perm: "compliance:read" },
  { href: "/integrations", label: "Integrations", icon: Plug, perm: "integrations:read" },
  { href: "/analytics", label: "Analytics", icon: BarChart3, perm: "analytics:read" },
  { href: "/settings", label: "Settings", icon: Settings, perm: "clients:read" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const { ready, email, emailVerified } = useAuth();
  const me = useMe();
  const orgId = useOrgId();
  const { theme, setTheme, setOrg } = useUI();
  const path = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [path]);

  if (!ready) return <div className="p-8"><Skeleton className="h-8 w-48" /></div>;
  if (!email) return <LoginScreen />;
  if (AUTH_MODE !== "dev" && !emailVerified) return <LoginScreen verify />;
  if (me.isLoading) return <div className="space-y-3 p-8"><Skeleton className="h-8 w-48" /><Skeleton className="h-40 w-full" /></div>;
  if (me.error) return <div className="p-8"><ErrorState error={me.error} onRetry={() => me.refetch()} /></div>;
  if (!me.data?.organizations.length) return <Onboarding />;

  const nav = NAV.filter((n) => canAnyClient(me.data, n.perm, orgId));
  const dark = theme === "dark" || (theme === "system" && typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches);

  return (
    <div className="min-h-screen md:grid md:grid-cols-[232px_1fr]">
      <aside className={cx("fixed inset-y-0 left-0 z-30 w-[232px] border-r border-border bg-panel transition-transform md:static md:translate-x-0", open ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <Sparkles className="size-5 text-accent" /><span className="font-semibold tracking-tight">Authentic Spark</span>
        </div>
        {me.data.organizations.length > 1 && (
          <div className="px-3 pt-3">
            <select aria-label="Organization" className="w-full rounded-md border border-border px-2 py-1 text-sm" value={orgId ?? ""} onChange={(e) => setOrg(e.target.value)}>
              {me.data.organizations.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </div>
        )}
        <nav aria-label="Main" className="space-y-0.5 p-2">
          {nav.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? path === "/" : path.startsWith(href);
            return (
              <Link key={href} href={href} aria-current={active ? "page" : undefined}
                className={cx("flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm", active ? "bg-accent/10 font-medium text-accent" : "text-muted hover:bg-panel-2 hover:text-text")}>
                <Icon className="size-4" />{label}
              </Link>
            );
          })}
        </nav>
      </aside>
      {open && <div className="fixed inset-0 z-20 bg-black/30 md:hidden" onClick={() => setOpen(false)} />}
      <div className="min-w-0">
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between gap-2 border-b border-border bg-panel/90 px-4 backdrop-blur">
          <button className="md:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}><Menu className="size-5" /></button>
          <span className="truncate text-sm text-muted">{me.data.organizations.find((o) => o.id === orgId)?.name}</span>
          <div className="flex items-center gap-1">
            <span className="hidden text-xs text-muted sm:inline">{email}</span>
            <Button variant="ghost" size="sm" aria-label="Toggle theme" onClick={() => setTheme(dark ? "light" : "dark")}>{dark ? <Sun className="size-4" /> : <Moon className="size-4" />}</Button>
            <Button variant="ghost" size="sm" onClick={async () => { await signOut(); router.push("/"); }}><LogOut className="size-4" />Sign out</Button>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6 md:px-6">{children}</main>
      </div>
    </div>
  );
}
