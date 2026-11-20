"use client";
import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { api, formatError } from "./api";
import { useAuth } from "./auth";
import { useUI } from "./store";
import type { Me } from "./types";
import { toast } from "@/components/ui/toast";

export function useMe() {
  const email = useAuth((s) => s.email);
  return useQuery({ queryKey: ["me", email], queryFn: () => api<Me>("/me"), enabled: !!email });
}

export function useOrgId(): string | null {
  const { data } = useMe();
  const orgId = useUI((s) => s.orgId);
  return orgId ?? data?.organizations[0]?.id ?? null;
}

export function useApi<T>(key: QueryKey, path: string | null, opts: { refetchInterval?: number } = {}) {
  return useQuery({ queryKey: key, queryFn: () => api<T>(path as string), enabled: !!path, ...opts });
}

/** Mutation helper: calls the API, toasts the outcome and invalidates related queries. */
export function useAction<V = unknown, R = unknown>(fn: (v: V) => Promise<R>, opts: { success?: string | ((r: R) => string); invalidate?: QueryKey[]; onSuccess?: (r: R) => void } = {}) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (r) => {
      if (opts.success) toast.ok(typeof opts.success === "function" ? opts.success(r) : opts.success);
      opts.invalidate?.forEach((k) => qc.invalidateQueries({ queryKey: k }));
      opts.onSuccess?.(r);
    },
    onError: (e) => toast.error("Action failed", formatError(e)),
  });
}
