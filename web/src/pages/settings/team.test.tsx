import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("Team settings", () => {
  it("loads the three demo members and their roles", async () => {
    renderApp("/settings/team");

    const list = await screen.findByRole("list", { name: "Kitchen team members" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(within(list).getByText("buyer@demo.kitchen")).toBeVisible();
    expect(within(list).getByText("approver")).toBeVisible();
    expect(within(list).getByText("chef")).toBeVisible();
    expect(within(list).getByText("viewer")).toBeVisible();
    expect(screen.getByText("Roles are managed by the gateway. This list is read-only.")).toBeVisible();
  });

  it("never offers a viewer an approval or role-management action", async () => {
    const api = createMockApi();
    vi.spyOn(api, "getSession").mockResolvedValue({
      name: "Viewer",
      email: "viewer@demo.kitchen",
      role: "viewer",
      canApprove: false,
      kind: "human",
    });
    renderApp("/settings/team", api);

    expect(await screen.findByRole("list", { name: "Kitchen team members" })).toBeVisible();
    const section = screen.getByRole("heading", { name: "Team" }).closest("section")!;
    expect(within(section).queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
    expect(within(section).queryByRole("button")).not.toBeInTheDocument();
    expect(within(section).queryByRole("textbox")).not.toBeInTheDocument();
  });
});
