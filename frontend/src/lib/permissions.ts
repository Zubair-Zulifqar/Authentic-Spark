import type { Me } from "./types";

/** Mirrors server-side RBAC for UI visibility only; the API enforces authorization independently. */
export function can(me: Me | undefined, perm: string, orgId: string | null, clientId?: string | null): boolean {
  if (!me || !orgId) return false;
  const agency = me.permissions[`${orgId}:*`] ?? [];
  if (agency.includes(perm)) return true;
  return clientId ? (me.permissions[`${orgId}:${clientId}`] ?? []).includes(perm) : false;
}

export function canAnyClient(me: Me | undefined, perm: string, orgId: string | null): boolean {
  if (!me || !orgId) return false;
  return Object.entries(me.permissions).some(([k, v]) => k.startsWith(`${orgId}:`) && v.includes(perm));
}
