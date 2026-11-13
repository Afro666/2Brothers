import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { createAppRouter } from "@/router";

async function renderAt(path: string) {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  render(
    <TooltipProvider>
      <RouterProvider router={router} />
    </TooltipProvider>,
  );
}

describe("application routes", () => {
  beforeEach(() => localStorage.clear());
  it.each([
    ["/requests", "Requests"],
    ["/approvals", "Approvals"],
    ["/orders", "Orders"],
    ["/orders/ORD-1", "Order ORD-1"],
    ["/audit", "Audit log"],
    ["/catalog", "Catalog"],
    ["/stock", "Stock"],
    ["/suppliers", "Suppliers"],
    ["/products", "Products"],
    ["/planner", "Planner"],
    ["/demand", "Demand"],
  ])("renders %s", async (path, title) => {
    await renderAt(path);
    expect(await screen.findByRole("heading", { level: 1, name: title })).toBeInTheDocument();
  });

  it("switches the nav to the Valio side and returns home", async () => {
    const user = userEvent.setup();
    await renderAt("/requests");
    await screen.findByRole("heading", { level: 1, name: "Requests" });
    await user.click(screen.getAllByRole("combobox")[0]);
    await user.click(await screen.findByRole("option", { name: "Valio planner" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Kitchen Buyer" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Demand" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "Approvals" })).not.toBeInTheDocument();
  });
});
