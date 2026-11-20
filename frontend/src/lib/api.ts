import { getToken } from "./auth";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

export function formatError(e: unknown): string {
  if (e instanceof ApiError) {
    if (Array.isArray(e.details)) {
      return `${e.message}: ${e.details.map((d) => (typeof d === "string" ? d : `${(d as { loc?: string[] }).loc?.join(".") ?? ""} ${(d as { msg?: string }).msg ?? ""}`)).join("; ")}`;
    }
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const token = await getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  const res = await fetch(`${API_URL}/api/v1${path}`, { ...init, headers, body });
  const type = res.headers.get("content-type") ?? "";
  if (!type.includes("json")) {
    if (!res.ok) throw new ApiError(res.status, "http_error", `Request failed (${res.status})`);
    return (await res.blob()) as T;
  }
  const payload = await res.json();
  if (!res.ok) {
    const err = payload?.error ?? {};
    // Some endpoints return 422 with data (e.g. compliance review results).
    if (payload?.data && !payload?.error) throw new ApiError(res.status, "rejected", "Checks did not pass", payload.data);
    throw new ApiError(res.status, err.code ?? "error", err.message ?? "Request failed", err.details);
  }
  return payload.data as T;
}

export async function openAuthed(path: string) {
  const blob = await api<Blob>(path);
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export const money = (cents: number) =>
  (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });

export const fmtDate = (s?: string | null) => (s ? new Date(s.length === 10 ? `${s}T00:00:00` : s).toLocaleDateString() : "—");
