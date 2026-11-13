import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import type { Api } from "@/api/types";
import { renderApp } from "@/test/render";

/** The desktop table comes first in the document; a phone gets the list below it. */
function productSections(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>("table tbody[data-product-section]")];
}

function productSection(productId: string): HTMLElement[] {
  const body = document.querySelector<HTMLElement>(`table tbody[data-product-section="${productId}"]`);
  const rows = [...(body?.querySelectorAll<HTMLElement>(":scope > tr") ?? [])];
  if (rows.length < 2) throw new Error(`No demand rows for ${productId}`);
  return rows;
}

function kitchensFor(productId: string): number {
  const firstDay = productSection(productId)[1];
  return Number(within(firstDay).getAllByRole("cell")[2].textContent);
}

describe("DemandPage", () => {
  beforeEach(() => localStorage.clear());

  it("shows the week, the risk summary and the worst products first", async () => {
    renderApp("/demand?week=2026-W47", createMockApi());

    expect(await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" })).toBeInTheDocument();
    // The mock kitchen's own menu shares nothing with this week.
    expect(await screen.findByText(/^3 short and 12 unknown$/)).toBeInTheDocument();
    expect(screen.getByText("Forecasts come only from kitchens that agreed to share them.")).toBeInTheDocument();

    const [head, ...days] = productSection("462775");
    expect(head).toHaveTextContent("Arla lactose-free milk");
    expect(head).toHaveTextContent("462775·short this week·3 days");
    expect(days).toHaveLength(3);
    for (const day of days) {
      expect(within(day).getByText("Short")).toHaveAttribute("data-risk", "SHORT");
      expect(within(day).getByText("Buy")).toBeInTheDocument();
      const forecast = within(day).getAllByRole("cell")[1].textContent ?? "";
      expect(forecast).toMatch(/^\d+ L$/);
    }
    const firstBody = productSections()[0];
    expect(firstBody).toHaveAttribute("data-product-section", "462775");
  });

  it("shows unknown availability as Unknown: check stock with an unknown buy figure", async () => {
    renderApp("/demand?week=2026-W47", createMockApi());

    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });
    const [, ...days] = productSection("462921");
    expect(days).toHaveLength(3);
    for (const day of days) {
      expect(within(day).getByText("Unknown: check stock")).toHaveAttribute("data-risk", "UNKNOWN");
      expect(within(day).getAllByTitle(/not measured availability/)).toHaveLength(1);
      expect(within(day).getAllByText("unknown")).toHaveLength(2);
    }
  });

  it("counts the kitchen's own forecast when it shares with Valio", async () => {
    renderApp("/demand?week=2026-W47", createMockApi());
    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });
    expect(kitchensFor("462775")).toBe(4);
  });

  it("loses a kitchen when the kitchen turns sharing off", async () => {
    const closed = createMockApi();
    await closed.setSharing("SUP-VALIO", false, "human");
    cleanup();
    renderApp("/demand?week=2026-W47", closed);
    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });

    expect(kitchensFor("462775")).toBe(3);
  });

  it("moves to the next and previous week", async () => {
    const user = userEvent.setup();
    renderApp("/demand?week=2026-W47", createMockApi());

    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });
    await user.click(screen.getByRole("button", { name: "Next week" }));
    expect(await screen.findByRole("heading", { name: "Week 48, 23 to 29 Nov 2026" })).toBeInTheDocument();
    expect(await screen.findByText("No demand forecast for this week")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Previous week" }));
    expect(await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" })).toBeInTheDocument();
  });

  it("shows each product name as the row header of its days", async () => {
    renderApp("/demand?week=2026-W47", createMockApi());
    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });

    const table = within(document.querySelector("table")!);
    const headers = table.getAllByRole("rowheader");
    expect(headers).toHaveLength(productSections().length);
    const milk = headers.find((header) => header.textContent?.includes("Arla lactose-free milk"));
    expect(milk).toHaveAttribute("scope", "rowgroup");
    expect(table.getByRole("rowheader", { name: /Arla lactose-free milk/ })).toBe(milk);
    for (const body of productSections()) {
      expect(within(body as HTMLElement).getAllByRole("rowheader")).toHaveLength(1);
    }
  });

  it("explains the page, not just the title", async () => {
    renderApp("/demand?week=2026-W47", createMockApi());
    expect(
      await screen.findByText("What kitchens that share their forecast expect to need, against what is available."),
    ).toBeInTheDocument();
  });

  it("names both years in a week that crosses New Year", async () => {
    renderApp("/demand?week=2026-W53", createMockApi());
    expect(await screen.findByRole("heading", { name: "Week 53, 28 Dec 2026 to 3 Jan 2027" })).toBeInTheDocument();
  });

  it.each(["banana", "2026-W99"])("does not ask the API for the invalid week %s", async (week) => {
    const api: Api = createMockApi();
    let demandCalls = 0;
    const getSupplierDemand = api.getSupplierDemand;
    api.getSupplierDemand = (from, to) => {
      demandCalls += 1;
      return getSupplierDemand(from, to);
    };
    renderApp(`/demand?week=${week}`, api);

    expect(await screen.findByRole("alert")).toHaveTextContent("That week is not valid");
    expect(screen.queryByRole("heading", { name: /^Week / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next week" })).not.toBeInTheDocument();
    expect(screen.queryByText("Forecasts come only from kitchens that agreed to share them.")).not.toBeInTheDocument();
    expect(demandCalls).toBe(0);
  });

  it("links from an invalid week back to the current week", async () => {
    renderApp("/demand?week=banana", createMockApi());

    const alert = await screen.findByRole("alert");
    const link = within(alert).getByRole("link", { name: /^Go to the current week, Week \d+/ });
    expect(link).toHaveAttribute("href", "/demand");
  });
});
