import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { renderApp } from "@/test/render";

async function renderAt(path: string) {
  renderApp(path);
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
    ["/forecast", "Forecast check"],
    ["/settings", "Settings"],
    ["/trust", "Trust"],
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
    expect(screen.queryByRole("link", { name: "Orders" })).not.toBeInTheDocument();
  });

  it("shows five menu entries and the current entry's pages as tabs", async () => {
    await renderAt("/approvals");
    await screen.findByRole("heading", { level: 1, name: "Approvals" });
    const menu = within(screen.getAllByRole("navigation", { name: "Main" })[0]);
    expect(menu.getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Home",
      "Orders",
      "Kitchen",
      "Catalog",
      "Reports",
      "Settings",
      "About",
    ]);
    expect(menu.getByRole("link", { name: "Orders" })).toHaveAttribute("aria-current", "page");
    const tabs = within(screen.getByRole("navigation", { name: "Orders" }));
    expect(tabs.getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Request an order",
      "To approve",
      "History",
    ]);
    expect(tabs.getByRole("link", { name: "To approve" })).toHaveAttribute("aria-current", "page");
  });

  it("shows no tabs on a page that stands alone", async () => {
    await renderAt("/about");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getAllByRole("navigation").map((nav) => nav.getAttribute("aria-label"))).toEqual(["Main"]);
  });
});
