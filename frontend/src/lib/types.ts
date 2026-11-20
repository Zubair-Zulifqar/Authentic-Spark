export type Row = Record<string, unknown> & { id: string };
export type Client = Row & { name: string; client_type: string; status: string; settings: Record<string, unknown>; pinned_modules: string[]; organization_id: string };
export type Me = {
  user: { id: string; email: string; display_name: string };
  organizations: { id: string; name: string }[];
  memberships: { organization_id: string; client_id: string | null; role: string; modules: string[] | null }[];
  permissions: Record<string, string[]>;
};
