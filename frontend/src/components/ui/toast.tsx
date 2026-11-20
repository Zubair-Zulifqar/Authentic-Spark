"use client";
import * as RToast from "@radix-ui/react-toast";
import { create } from "zustand";
import { cx } from "./index";

type T = { id: number; title: string; body?: string; tone: "ok" | "bad" | "info" };
const useToasts = create<{ items: T[]; push: (t: Omit<T, "id">) => void; remove: (id: number) => void }>((set) => ({
  items: [],
  push: (t) => set((s) => ({ items: [...s.items, { ...t, id: Date.now() + Math.random() }] })),
  remove: (id) => set((s) => ({ items: s.items.filter((x) => x.id !== id) })),
}));

export const toast = {
  ok: (title: string, body?: string) => useToasts.getState().push({ title, body, tone: "ok" }),
  error: (title: string, body?: string) => useToasts.getState().push({ title, body, tone: "bad" }),
  info: (title: string, body?: string) => useToasts.getState().push({ title, body, tone: "info" }),
};

export function Toaster() {
  const { items, remove } = useToasts();
  return (
    <RToast.Provider swipeDirection="right" duration={5000}>
      {items.map((t) => (
        <RToast.Root key={t.id} onOpenChange={(o) => !o && remove(t.id)}
          className={cx("rounded-md border bg-panel p-3 shadow-lg", t.tone === "ok" ? "border-ok/40" : t.tone === "bad" ? "border-bad/40" : "border-accent/40")}>
          <RToast.Title className={cx("text-sm font-semibold", t.tone === "bad" && "text-bad")}>{t.title}</RToast.Title>
          {t.body && <RToast.Description className="mt-0.5 text-xs text-muted">{t.body}</RToast.Description>}
        </RToast.Root>
      ))}
      <RToast.Viewport className="fixed bottom-4 right-4 z-[60] flex w-[min(360px,calc(100vw-32px))] flex-col gap-2" />
    </RToast.Provider>
  );
}
