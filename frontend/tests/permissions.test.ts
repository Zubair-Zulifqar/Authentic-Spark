import { describe, expect, it } from "vitest";
import { can, canAnyClient } from "@/lib/permissions";
import type { Me } from "@/lib/types";

const me = {
  user: { id: "u", email: "a@x.org", display_name: "" }, organizations: [{ id: "o1", name: "O" }], memberships: [],
  permissions: { "o1:*": ["clients:read"], "o1:c1": ["email:write", "email:read"] },
} as Me;

describe("permissions", () => {
  it("agency-wide grants apply to all clients", () => expect(can(me, "clients:read", "o1", "c9")).toBe(true));
  it("client grants are scoped", () => {
    expect(can(me, "email:write", "o1", "c1")).toBe(true);
    expect(can(me, "email:write", "o1", "c2")).toBe(false);
  });
  it("other orgs are denied", () => expect(can(me, "clients:read", "o2")).toBe(false));
  it("canAnyClient detects module access for nav", () => {
    expect(canAnyClient(me, "email:read", "o1")).toBe(true);
    expect(canAnyClient(me, "billing:read", "o1")).toBe(false);
  });
});
