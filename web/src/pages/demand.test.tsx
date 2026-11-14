import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import type { Api } from "@/api/types";
import { renderApp } from "@/test/render";
import type { SupplierDemandRow } from "@/types";
import { groupByProduct } from "./demand";

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
  const text = within(firstDay).getAllByRole("cell")[2].textContent ?? "";
  return Number(text.match(/^\d+/)?.[0]);
}

async function openProduct(productId: string) {
  await userEvent.click(within(productSection(productId)[0]).getByRole("button"));
}

async function demandTableReady() {
  await waitFor(() => expect(productSections().length).toBeGreaterThan(0));
}

function demandRow(overrides: Partial<SupplierDemandRow> = {}): SupplierDemandRow {
  return {
    productId: "milk",
    productName: "Milk",
    unit: "L",
    date: "2026-11-16",
    forecastDemand: 100,
    kitchens: 2,
    byKitchen: [],
    available: 50,
    risk: "SHORT",
    suggestedBuy: 50,
    ...overrides,
  };
}

function demandApi(rows: SupplierDemandRow[]): Api {
  const api = createMockApi();
  api.getSupplierDemand = async () => rows;
  return api;
}

describe("groupByProduct", () => {
  it("sums known buys only and counts short and unknown days", () => {
    const [group] = groupByProduct([
      demandRow({ date: "2026-11-18", risk: "COVERED", suggestedBuy: 8, kitchens: 3 }),
      demandRow({ date: "2026-11-16", risk: "SHORT", suggestedBuy: 12, kitchens: 2 }),
      demandRow({ date: "2026-11-17", risk: "UNKNOWN", available: null, suggestedBuy: null, kitchens: 5 }),
    ]);

    expect(group).toMatchObject({ totalBuy: 20, unknownBuyDays: 1, shortDays: 1, maxKitchens: 5, worst: "SHORT" });
    expect(group.rows.map((row) => row.date)).toEqual(["2026-11-16", "2026-11-17", "2026-11-18"]);

    const [unknown] = groupByProduct([
      demandRow({ risk: "UNKNOWN", available: null, suggestedBuy: null }),
      demandRow({ date: "2026-11-17", risk: "UNKNOWN", available: null, suggestedBuy: null }),
    ]);
    expect(unknown).toMatchObject({ totalBuy: null, unknownBuyDays: 2, shortDays: 0 });
  });

  it("orders short by largest known buy, then unknown and covered", () => {
    const groups = groupByProduct([
      demandRow({ productId: "covered", productName: "Butter", risk: "COVERED", available: 500, suggestedBuy: 0 }),
      demandRow({ productId: "short-low", productName: "Yogurt", suggestedBuy: 5 }),
      demandRow({ productId: "unknown", productName: "Flour", risk: "UNKNOWN", available: null, suggestedBuy: null }),
      demandRow({ productId: "short-high", productName: "Cheese", suggestedBuy: 50 }),
    ]);

    expect(groups.map((group) => group.productId)).toEqual(["short-high", "short-low", "unknown", "covered"]);
  });
});

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
    expect(head).toHaveTextContent("462775");
    expect(head).toHaveTextContent("Short on 3 of 3 days");
    expect(head).toHaveTextContent(/Buy [\d,.]+ L/);
    expect(head).toHaveTextContent("kitchens: up to 4");
    expect(within(head).getByText("Short")).toHaveAttribute("data-risk", "SHORT");
    expect(days).toHaveLength(3);
    for (const day of days) expect(day).not.toBeVisible();
    await openProduct("462775");
    for (const day of days) {
      expect(day).toBeVisible();
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
    await demandTableReady();
    const [head, ...days] = productSection("462921");
    expect(head).toHaveTextContent("+ days with an unknown amount: 3");
    expect(head).not.toHaveTextContent("Buy 0 L");
    expect(head).toHaveTextContent("kitchens: up to 4");
    await openProduct("462921");
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
    await demandTableReady();
    await openProduct("462775");
    expect(kitchensFor("462775")).toBe(4);
  });

  it("expands a demand row to list kitchen names and their demand", async () => {
    const user = userEvent.setup();
    renderApp("/demand?week=2026-W47", createMockApi());
    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });
    await demandTableReady();

    await openProduct("463335");
    const firstDay = productSection("463335")[1];
    const button = within(firstDay).getByRole("button", { name: /^5 kitchens for Valio Eila 3 % milk, / });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(within(firstDay).getByRole("list", { hidden: true })).toHaveAttribute(
      "id",
      button.getAttribute("aria-controls"),
    );
    expect(within(firstDay).getByText("K00 Demo restaurant, Helsinki")).not.toBeVisible();
    await user.click(button);

    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(within(firstDay).getByText("K00 Demo restaurant, Helsinki")).toBeVisible();
    expect(within(firstDay).getByText("31 L")).toBeVisible();
    expect(within(firstDay).getByText("K01 School 1 Tampere")).toBeVisible();
  });

  it("gives the table and the phone list their own kitchen list ids", async () => {
    renderApp("/demand?week=2026-W47", createMockApi());
    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });
    await waitFor(() => expect(document.querySelectorAll("button[aria-controls]")).toHaveLength(30));

    const ids = [...document.querySelectorAll("button[aria-controls]")].map((button) =>
      button.getAttribute("aria-controls"),
    );
    expect(ids).toHaveLength(30);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("lists the kitchens of an expanded row largest demand first", async () => {
    const user = userEvent.setup();
    renderApp("/demand?week=2026-W47", createMockApi());
    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });
    await demandTableReady();

    await openProduct("462775");
    const firstDay = productSection("462775")[1];
    await user.click(within(firstDay).getByRole("button", { name: /^4 kitchens/ }));
    expect(
      within(firstDay)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "K07 Hospital kitchen Turku73.34 L",
      "K01 School 1 Tampere73.33 L",
      "K04 Hotel Aurora Helsinki73.33 L",
      "K00 Demo restaurant, Helsinki16 L",
    ]);
  });

  it("says so instead of offering a toggle when no kitchen shares a forecast", async () => {
    const api: Api = createMockApi();
    const getSupplierDemand = api.getSupplierDemand;
    api.getSupplierDemand = async (from, to) =>
      (await getSupplierDemand(from, to))
        .slice(0, 1)
        .map((row) => ({ ...row, byKitchen: [], kitchens: 0, forecastDemand: 0 }));
    renderApp("/demand?week=2026-W47", api);
    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });

    // Once in the table and once in the phone list.
    expect(await screen.findAllByText("No kitchens share this forecast")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /kitchens? for/ })).not.toBeInTheDocument();
  });

  it("loses a kitchen when the kitchen turns sharing off", async () => {
    const closed = createMockApi();
    await closed.setSharing("SUP-VALIO", false, "human");
    cleanup();
    renderApp("/demand?week=2026-W47", closed);
    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });
    await demandTableReady();

    await openProduct("462775");
    expect(kitchensFor("462775")).toBe(3);
    await openProduct("463335");
    const firstDay = productSection("463335")[1];
    const user = userEvent.setup();
    await user.click(within(firstDay).getByRole("button", { name: /^4 kitchens/ }));
    expect(within(firstDay).queryByText("K00 Demo restaurant, Helsinki")).not.toBeInTheDocument();
    expect(within(firstDay).getByText("K01 School 1 Tampere")).toBeVisible();
  });

  it("keeps covered products in one closed group and opens their product lines first", async () => {
    const user = userEvent.setup();
    renderApp(
      "/demand?week=2026-W47",
      demandApi([
        demandRow({ productId: "butter", productName: "Butter", risk: "COVERED", available: 500, suggestedBuy: 0 }),
      ]),
    );
    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });
    await demandTableReady();

    const table = within(document.querySelector("table")!);
    const covered = table.getByRole("button", { name: "Covered products: 1" });
    expect(covered).toHaveAttribute("aria-expanded", "false");
    expect(productSection("butter")[0]).not.toBeVisible();

    await user.click(screen.getByRole("button", { name: "Covered (1)" }));
    expect(covered).toHaveAttribute("aria-expanded", "true");
    expect(productSection("butter")[0]).toBeVisible();
    expect(productSection("butter")[1]).not.toBeVisible();
    await openProduct("butter");
    expect(productSection("butter")[1]).toBeVisible();
  });

  it("filters to short products and opens every day with Open all", async () => {
    const user = userEvent.setup();
    renderApp(
      "/demand?week=2026-W47",
      demandApi([
        demandRow({ productId: "short-low", productName: "Yogurt", suggestedBuy: 5 }),
        demandRow({ productId: "covered", productName: "Butter", risk: "COVERED", available: 500, suggestedBuy: 0 }),
        demandRow({ productId: "unknown", productName: "Flour", risk: "UNKNOWN", available: null, suggestedBuy: null }),
        demandRow({ productId: "short-high", productName: "Cheese", suggestedBuy: 50 }),
      ]),
    );
    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });
    await demandTableReady();

    expect(screen.getByRole("button", { name: "All (4)" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Short (2)" }));
    const table = within(document.querySelector("table")!);
    expect(table.getAllByRole("rowheader").map((header) => header.textContent)).toEqual([
      expect.stringContaining("Cheese"),
      expect.stringContaining("Yogurt"),
    ]);
    expect(table.queryByRole("rowheader", { name: /Flour/ })).not.toBeInTheDocument();
    expect(table.queryByRole("button", { name: /^Covered products:/ })).not.toBeInTheDocument();

    // Open all opens what the filter shows and leaves the filter as the person set it.
    await user.click(screen.getByRole("button", { name: "Open all" }));
    expect(screen.getByRole("button", { name: "Short (2)" })).toHaveAttribute("aria-pressed", "true");
    expect(table.queryByRole("rowheader", { name: /Flour/ })).not.toBeInTheDocument();
    for (const body of productSections()) {
      const [, ...days] = [...body.querySelectorAll<HTMLElement>(":scope > tr")];
      for (const day of days) expect(day).toBeVisible();
    }

    await user.click(screen.getByRole("button", { name: "Close all" }));
    for (const body of productSections()) {
      const [, ...days] = [...body.querySelectorAll<HTMLElement>(":scope > tr")];
      for (const day of days) expect(day).not.toBeVisible();
    }
  });

  it("says so when the chosen filter has no products, in the table and the phone list", async () => {
    const user = userEvent.setup();
    renderApp(
      "/demand?week=2026-W47",
      demandApi([
        demandRow({ productId: "butter", productName: "Butter", risk: "COVERED", available: 500, suggestedBuy: 0 }),
      ]),
    );
    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });
    await demandTableReady();

    expect(screen.queryByText("No products in this filter")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Short (0)" }));
    const table = within(document.querySelector("table")!);
    expect(table.getByText("No products in this filter")).toBeInTheDocument();
    const phone = within(document.querySelector("ul.md\\:hidden")!);
    expect(phone.getByText("No products in this filter")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Covered (1)" }));
    expect(screen.queryByText("No products in this filter")).not.toBeInTheDocument();
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
    await screen.findByRole("rowheader", { name: /Arla lactose-free milk/ });

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

  it("opens on next week when no week is asked for", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-13T12:00:00Z"));
    try {
      renderApp("/demand", createMockApi());
      expect(await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" })).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("links from an invalid week back to next week", async () => {
    renderApp("/demand?week=banana", createMockApi());

    const alert = await screen.findByRole("alert");
    const link = within(alert).getByRole("link", { name: /^Go to next week, Week \d+/ });
    expect(link).toHaveAttribute("href", "/demand");
  });

  it("shows no buying note box without a note", async () => {
    renderApp("/demand?week=2026-W47", createMockApi());
    await demandTableReady();
    expect(screen.queryByRole("heading", { name: "Buying note" })).not.toBeInTheDocument();
  });

  it("shows the buying note lines under a Written by note", async () => {
    const api: Api = createMockApi();
    api.getBuyingNote = async () => ({
      model: "nemotron-3.5-super-vl",
      lines: [
        { productId: "462775", productName: "Arla lactose-free milk", date: "2026-11-16", risk: "SHORT",
          text: "Forecast 2400 L from 6 kitchens: buy 700 L more." },
        { productId: "462775", productName: "Arla lactose-free milk", date: "2026-11-17", risk: "SHORT",
          text: "Forecast 2500 L from 6 kitchens: buy 800 L more." },
        { productId: "462921", productName: "Wheat flour 2 kg", date: "2026-11-17", risk: "UNKNOWN",
          text: "Availability unknown for 3 kitchens: ask the mill." },
      ],
    });
    renderApp("/demand?week=2026-W47", api);

    const box = await screen.findByRole("region", { name: "Buying note" });
    // Two days of one product are grouped under its name, said once.
    expect(within(box).getAllByText("Arla lactose-free milk")).toHaveLength(1);
    const lines = box.querySelectorAll("[data-note-risk]");
    expect(lines).toHaveLength(3);
    expect(lines[0]).toHaveTextContent("Mon 16 Nov");
    expect(lines[0]).toHaveTextContent("Forecast 2400 L from 6 kitchens: buy 700 L more.");
    expect(lines[0]).toHaveAttribute("data-note-risk", "SHORT");
    expect(lines[1]).toHaveTextContent("Tue 17 Nov");
    expect(lines[2]).toHaveAttribute("data-note-risk", "UNKNOWN");
    expect(box).toHaveTextContent(
      "Written by nemotron-3.5-super-vl. Every number is checked against its row in the table.",
    );
  });

  it("renders the table before a slow note arrives", async () => {
    const api: Api = createMockApi();
    let resolve: ((note: Awaited<ReturnType<Api["getBuyingNote"]>>) => void) | undefined;
    api.getBuyingNote = () => new Promise((done) => { resolve = done; });
    renderApp("/demand?week=2026-W47", api);

    await demandTableReady();
    expect(screen.queryByRole("heading", { name: "Buying note" })).not.toBeInTheDocument();
    resolve?.({
      model: "nemotron-3.5-super-vl",
      lines: [{ productId: "462775", productName: "Arla lactose-free milk", date: "2026-11-16", risk: "SHORT", text: "Buy more." }],
    });
    expect(await screen.findByRole("heading", { name: "Buying note" })).toBeInTheDocument();
  });
});
