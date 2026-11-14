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
    ["/requests", "Request an order"],
    ["/approvals", "To approve"],
    ["/orders", "Order history"],
    ["/orders/ORD-1", "Order ORD-1"],
    ["/audit", "Activity log"],
    ["/catalog", "Products"],
    ["/stock", "Stock count"],
    ["/suppliers", "Suppliers"],
    ["/products", "Recipes"],
    ["/planner", "Menu plan"],
    ["/demand", "Demand"],
    ["/forecast", "Forecast vs actual"],
    ["/settings", "Settings"],
    ["/trust", "Tamper check"],
  ])("renders %s", async (path, title) => {
    await renderAt(path);
    expect(await screen.findByRole("heading", { level: 1, name: title })).toBeInTheDocument();
  });

  it("switches the nav to the Valio side and returns home", async () => {
    const user = userEvent.setup();
    await renderAt("/requests");
    await screen.findByRole("heading", { level: 1, name: "Request an order" });
    await user.click(screen.getAllByRole("combobox")[0]);
    await user.click(await screen.findByRole("option", { name: "Valio planner" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Kitchen Buyer" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Demand" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "To approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Orders" })).not.toBeInTheDocument();
  });

  /** The link's label without the waiting-approvals badge, which loads a moment later. */
  function label(link: HTMLElement): string | null {
    const copy = link.cloneNode(true) as HTMLElement;
    copy.querySelectorAll("[data-nav-count]").forEach((badge) => badge.remove());
    return copy.textContent;
  }

  it("shows five menu entries and the current entry's pages as tabs", async () => {
    await renderAt("/approvals");
    await screen.findByRole("heading", { level: 1, name: "To approve" });
    const menu = within(screen.getAllByRole("navigation", { name: "Main" })[0]);
    expect(menu.getAllByRole("link").map(label)).toEqual([
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
    expect(tabs.getAllByRole("link").map(label)).toEqual([
      "Request an order",
      "To approve",
      "Order history",
    ]);
    expect(tabs.getByRole("link", { name: "To approve" })).toHaveAttribute("aria-current", "page");
  });

  it("shows no tabs on a page that stands alone", async () => {
    await renderAt("/about");
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getAllByRole("navigation").map((nav) => nav.getAttribute("aria-label"))).toEqual(["Main"]);
  });
});
