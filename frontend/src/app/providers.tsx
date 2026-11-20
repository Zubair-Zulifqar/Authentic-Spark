"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { initAuth } from "@/lib/auth";
import { useUI } from "@/lib/store";
import { Toaster } from "@/components/ui/toast";
import { ApiError } from "@/lib/api";

export function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(() => new QueryClient({
    defaultOptions: { queries: { staleTime: 15_000, retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 2 } },
  }));
  useEffect(() => {
    let t: string | null = null;
    try { t = localStorage.getItem("spark.theme"); } catch { /* ignore */ }
    if (t === "light" || t === "dark") useUI.getState().setTheme(t);
    return initAuth();
  }, []);
  return <QueryClientProvider client={qc}>{children}<Toaster /></QueryClientProvider>;
}
