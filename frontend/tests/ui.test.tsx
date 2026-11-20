import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Badge, DataTable } from "@/components/ui";
import { formatError, ApiError, money } from "@/lib/api";

describe("DataTable", () => {
  const rows = [{ id: "1", name: "Alpha", status: "active" }, { id: "2", name: "Beta", status: "paused" }];
  it("searches and filters", () => {
    render(<DataTable rows={rows} searchKeys={["name"]} filterKey="status" columns={[{ key: "name", header: "Name" }]} />);
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "bet" } });
    expect(screen.queryByText("Alpha")).toBeNull();
    expect(screen.getByText("Beta")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "active" } });
    expect(screen.getByText("Alpha")).toBeTruthy();
    expect(screen.queryByText("Beta")).toBeNull();
  });
});

describe("helpers", () => {
  it("badge humanizes status", () => { render(<Badge>pending_approval</Badge>); expect(screen.getByText("pending approval")).toBeTruthy(); });
  it("formats validation errors", () => {
    expect(formatError(new ApiError(422, "validation_failed", "Request validation failed", [{ loc: ["name"], msg: "too short" }]))).toContain("name too short");
  });
  it("formats money", () => expect(money(123456)).toBe("$1,234.56"));
});
