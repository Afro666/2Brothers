import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import type { Supplier } from "@/types";
import { renderApp } from "@/test/render";
import { nextCutoff } from "@/pages/home/cutoff";

const DEMO_NOW = "2026-11-13T21:00:00%2B02:00";

function supplier(orderDays: number[] | null, cutoffTime: string | null): Supplier {
  return {
    id: "SUP-TEST",
    name: "Test supplier",
    adapter: "manual",
    freeDeliveryThresholdEur: null,
    deliveryFeeEur: null,
    orderDays,
    cutoffTime,
    leadTimeDays: null,
  };
}

describe("HomePage", () => {
  beforeEach(() => localStorage.clear());

  it("shows the kitchen dashboard for the demo timestamp", async () => {
    renderApp(`/?now=${DEMO_NOW}`, createMockApi());

    expect(await screen.findByText("Waiting for your approval")).toBeInTheDocument();
    expect(screen.getByText("1", { selector: ".text-3xl" })).toBeInTheDocument();
    expect(screen.getByText("€2,210.41 incl VAT")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review approvals" })).toHaveAttribute("href", "/approvals");
    expect(screen.getByText("Hakaniemi Fish").parentElement).toHaveTextContent("terms not set");
    expect(screen.getAllByText("not counted").length).toBeGreaterThan(0);
    expect(screen.getByText("Latest steps")).toBeInTheDocument();
  });

  it("shows Valio risk counts and demand navigation for a Valio planner", async () => {
    localStorage.setItem("purchasing-role", "valio_planner");
    renderApp(`/?now=${DEMO_NOW}`, createMockApi());
    expect(
      await screen.findByText(
        (_, element) => element?.textContent?.replace(/\s+/g, " ").trim() === "3 SHORT · 12 UNKNOWN · 0 AT_RISK",
      ),
    ).toBeInTheDocument();
    expect(
      screen
        .getAllByRole("link", { name: "Open demand view" })
        .every((link) => link.getAttribute("href") === "/demand"),
    ).toBe(true);
    expect(screen.getByText("Only kitchens that agreed to share appear here.")).toBeInTheDocument();
    expect(screen.getByText("Where demand may outrun supply.")).toBeInTheDocument();
  });

  it("labels next-week forecasts when the current week has no rows", async () => {
    localStorage.setItem("purchasing-role", "valio_planner");
    const api = createMockApi();
    let calls = 0;
    api.getSupplierDemand = async () => {
      calls += 1;
      if (calls === 1) return [];
      return [
        {
          productId: "MILK-001",
          productName: "Milk",
          unit: "L",
          date: "2026-11-16",
          forecastDemand: 10,
          kitchens: 1,
          byKitchen: [{ kitchenId: "K01", kitchenName: "School 1 Tampere", demand: 10 }],
          available: 0,
          risk: "SHORT",
          suggestedBuy: 10,
        },
      ];
    };
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(await screen.findByText("No forecasts for this week yet; showing next week.")).toBeInTheDocument();
    expect(screen.getByText("Shortage risk, week 47 · Mon 16 Nov–Sun 22 Nov")).toBeInTheDocument();
  });

  it("shows demanded products with no stock row as not counted", async () => {
    const api = createMockApi();
    api.getStock = async () => [];
    api.getDemand = async () => [
      {
        productId: "MILK-001",
        productName: "Uncounted milk",
        unit: "L",
        date: "2026-11-13",
        need: 4,
        why: "planned menu",
      },
    ];
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(await screen.findByText("Stock to check")).toBeInTheDocument();
    expect(await screen.findByText("Uncounted milk")).toBeInTheDocument();
    expect(screen.getByText("Uncounted milk").parentElement).toHaveTextContent("not counted");
    expect(screen.getByText("What needs you today.")).toBeInTheDocument();
  });
});

describe("nextCutoff", () => {
  it("returns today's cutoff before its Helsinki local time", () => {
    const result = nextCutoff(supplier([5], "22:00"), new Date("2026-11-13T21:00:00+02:00"));
    expect(result?.toISOString()).toBe("2026-11-13T20:00:00.000Z");
  });

  it("rolls an order day whose cut-off already passed today to the next order day", () => {
    const result = nextCutoff(supplier([5], "20:00"), new Date("2026-11-13T21:00:00+02:00"));
    expect(result?.toISOString()).toBe("2026-11-20T18:00:00.000Z");
  });

  it("wraps to Monday from the weekend", () => {
    const result = nextCutoff(supplier([1], "09:30"), new Date("2026-11-15T12:00:00+02:00"));
    expect(result?.toISOString()).toBe("2026-11-16T07:30:00.000Z");
  });

  it("returns null when order terms are missing", () => {
    expect(nextCutoff(supplier(null, null), new Date("2026-11-13T21:00:00+02:00"))).toBeNull();
    expect(nextCutoff(supplier([1], null), new Date("2026-11-13T21:00:00+02:00"))).toBeNull();
  });
});
