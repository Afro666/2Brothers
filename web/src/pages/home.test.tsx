import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mapAudit } from "@/api/gateway-map";
import { createMockApi } from "@/api/mock";
import { updateLanguage } from "@/lib/i18n";
import type { Api } from "@/api/types";
import type { Supplier } from "@/types";
import { approval, milkOptions } from "@/mocks/milk-case";
import { renderApp } from "@/test/render";
import { nextCutoff } from "@/pages/home/cutoff";
import { oldestWaiting } from "@/pages/home/kitchen";
import type { ApprovalRequest } from "@/types";

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

describe("oldestWaiting", () => {
  const approval = (id: string, createdAt: string | null) => ({ id, createdAt }) as ApprovalRequest;

  it("treats a proposal with no creation time as the oldest", () => {
    expect(oldestWaiting([approval("new", "2026-11-14T09:00:00+02:00"), approval("no-time", null)])?.id).toBe("no-time");
  });

  it("picks the earliest known creation time", () => {
    expect(oldestWaiting([approval("new", "2026-11-14T09:00:00+02:00"), approval("old", "2026-11-13T09:00:00+02:00")])?.id).toBe("old");
  });
});

describe("HomePage", () => {
  beforeEach(() => localStorage.clear());

  it("shows the count before slow approval details arrive", async () => {
    const api = createMockApi(); const rows = await api.listApprovals();
    let finish!: (value: typeof rows) => void;
    api.listApprovals = vi.fn(() => new Promise<typeof rows>((resolve) => { finish = resolve; }));
    api.countPendingApprovals = vi.fn(async () => 7);
    renderApp(`/?now=${DEMO_NOW}`, api);
    const label = await screen.findByText("Loading approval details...");
    expect(label.parentElement).toHaveTextContent("7");
    await act(async () => finish(rows)); await screen.findByText("Oldest waiting");
    expect(screen.queryByText("Loading approval details...")).not.toBeInTheDocument();
  });

  it("keeps fresh data on a live reload without showing the cached-visit banner", async () => {
    const api = createMockApi(); const rows = await api.listApprovals();
    api.countPendingApprovals = async () => 4;
    let publish!: Parameters<NonNullable<Api["subscribeEvents"]>>[0];
    api.subscribeEvents = (onEvent) => { publish = onEvent; return () => {}; };
    api.listApprovals = vi.fn(async () => rows);
    renderApp(`/?now=${DEMO_NOW}`, api); await screen.findByText("Oldest waiting");
    let finish!: (value: typeof rows) => void;
    const load = vi.fn(() => new Promise<typeof rows>((resolve) => { finish = resolve; }));
    api.listApprovals = load;
    act(() => publish({ kind: "proposal", operation: "update" }));
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    expect(screen.getByText("Oldest waiting")).toBeInTheDocument();
    expect(screen.queryByText("Showing previous results while refreshing...")).not.toBeInTheDocument();
    await act(async () => finish([])); await screen.findByText("Nothing is waiting.");
  });

  it("shows a cached summary on return, labels it and replaces it after refresh", async () => {
    const api = createMockApi(); api.countPendingApprovals = async () => 4;
    const rows = await api.listApprovals(); api.listApprovals = vi.fn(async () => rows);
    const { router } = renderApp(`/?now=${DEMO_NOW}`, api); await screen.findByText("Oldest waiting");
    await act(async () => { await router.navigate({ to: "/about" }); });
    let finish!: (value: typeof rows) => void;
    api.listApprovals = vi.fn(() => new Promise<typeof rows>((resolve) => { finish = resolve; }));
    await act(async () => { await router.navigate({ to: "/" }); });
    expect(await screen.findByText("Showing previous results while refreshing...")).toBeInTheDocument();
    expect(screen.getByText("Oldest waiting")).toBeInTheDocument();
    await act(async () => finish([])); await screen.findByText("Nothing is waiting.");
    await waitFor(() => expect(screen.queryByText("Showing previous results while refreshing...")).not.toBeInTheDocument());
  });

  it("shows the kitchen dashboard for the demo timestamp", async () => {
    renderApp(`/?now=${DEMO_NOW}`, createMockApi());

    expect(await screen.findByText("Waiting for your approval")).toBeInTheDocument();
    expect(await screen.findByText("4", { selector: ".text-3xl" })).toBeInTheDocument();
    expect(screen.getByText("€2,210.41 incl VAT")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review orders to approve" })).toHaveAttribute("href", "/approvals");
    expect(screen.getByText("Hakaniemi Fish").parentElement).toHaveTextContent("terms not set");
    expect(screen.getAllByText("not counted").length).toBeGreaterThan(0);
    expect(screen.getByText("Latest steps")).toBeInTheDocument();
    // Who decides what: two machines and the person, in that order; only the person approves.
    const strip = screen.getByRole("region", { name: "Who decides what" });
    expect(
      [...strip.querySelectorAll(".actor-box")].map((box) => `${box.textContent}:${box.getAttribute("data-actor")}`),
    ).toEqual(["Buyer agent:machine", "Ordering engine:machine", "You:person"]);
    expect([...strip.querySelectorAll("li")].map((step) => /approve/.test(step.textContent ?? ""))).toEqual([
      false,
      false,
      true,
    ]);
    // The mock is not Atlas, so nothing on the page says it is.
    expect(screen.queryByTestId("atlas-mark")).not.toBeInTheDocument();
  });

  it("shows the gateway's approval figure, including its delivery fee", async () => {
    const api = createMockApi();
    api.listApprovals = async () => [{ ...approval, totalInclVat: 62.74, inclVat: 37.74 }];
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(await screen.findByText("€62.74 in all")).toBeInTheDocument();
    expect(screen.queryByText("€37.74 incl VAT")).not.toBeInTheDocument();
  });

  it("names the recommended option's total while the basket is still the Buyer's own, as the card does (#1911)", async () => {
    const [a, b] = milkOptions;
    const options = [
      { ...a!, recommended: true, stockConfirmed: true, chosen: false, cutoffPassed: false, totalInclVat: 2099.41 },
      { ...b!, recommended: false, chosen: true, source: "original" as const, totalInclVat: 2634.13 },
    ];
    const api = createMockApi();
    api.listApprovals = async () => [{ ...approval, totalInclVat: 2634.13, options }];
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(await screen.findByText("€2,099.41 in all")).toBeInTheDocument();
    expect(screen.queryByText(/€2,634\.13/)).not.toBeInTheDocument();
  });

  it("keeps the basket total once a person chose the basket (#1911)", async () => {
    const [a, b] = milkOptions;
    const options = [
      { ...a!, recommended: true, stockConfirmed: true, chosen: false, cutoffPassed: false, totalInclVat: 2099.41 },
      { ...b!, recommended: false, chosen: true, source: "supplier" as const, totalInclVat: 2634.13 },
    ];
    const api = createMockApi();
    api.listApprovals = async () => [{ ...approval, totalInclVat: 2634.13, options }];
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(await screen.findByText("€2,634.13 incl VAT")).toBeInTheDocument();
  });

  it.each<keyof Api>(["listAudit", "getDrift"])("marks only the tile fed by %s as MongoDB Atlas", async (method) => {
    const api = Object.assign(createMockApi(), { live: new Set<keyof Api>([method]) });
    renderApp(`/?now=${DEMO_NOW}`, api);
    expect(await screen.findByText("Latest steps")).toBeInTheDocument();
    expect(screen.getAllByTestId("atlas-mark")).toHaveLength(1);
    expect(screen.getByTestId("atlas-mark")).toHaveTextContent("MongoDB Atlas");
  });

  it("shows Valio risk counts and demand navigation for a Valio planner", async () => {
    localStorage.setItem("purchasing-role", "valio_planner");
    const api = createMockApi();
    await api.signIn("planner@demo.valio", "demo-kitchen-2026");
    renderApp(`/?now=${DEMO_NOW}`, api);
    expect(
      await screen.findByText(
        (_, element) => element?.textContent?.replace(/\s+/g, " ").trim() === "3 SHORT · 12 UNKNOWN · 0 AT_RISK",
      ),
    ).toBeInTheDocument();
    const unknownValues = screen.getAllByText("unknown");
    expect(unknownValues.length).toBeGreaterThan(0);
    for (const value of unknownValues) expect(value).toHaveClass("unknown-value");
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
    await api.signIn("planner@demo.valio", "demo-kitchen-2026");
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
    expect(screen.getByText("1", { selector: ".text-3xl" })).toBeInTheDocument();
    // One request for this week, one for the fallback week: both tiles share the data.
    expect(calls).toBe(2);
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
    expect(screen.getByText("Uncounted milk").closest("li")).toHaveTextContent("not counted");
    expect(screen.getByText("What needs you today.")).toBeInTheDocument();
  });

  it("rounds shortfalls up: whole pieces, one decimal for weights", async () => {
    const api = createMockApi();
    const row = { onOrder: 0, countedAt: null, lastDelivery: null };
    api.getStock = async () => [
      { ...row, productId: "PCS-001", productName: "Bread rolls", unit: "PCS", onHand: 0 },
      { ...row, productId: "KG-001", productName: "Potatoes", unit: "KG", onHand: 0 },
    ];
    const line = { date: "2026-11-13", why: "planned menu" };
    api.getDemand = async () => [
      { ...line, productId: "PCS-001", productName: "Bread rolls", unit: "PCS", need: 1921.159 },
      { ...line, productId: "KG-001", productName: "Potatoes", unit: "KG", need: 41.41 },
    ];
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(await screen.findByText("Bread rolls")).toBeInTheDocument();
    expect(screen.getByText("Bread rolls").closest("li")).toHaveTextContent("short by 1,922 pieces");
    expect(screen.getByText("Potatoes").closest("li")).toHaveTextContent("short by 41.5 kg");
  });

  it("uses plain words for raw audit step codes in Latest steps", async () => {
    const api = createMockApi();
    api.listAudit = async () => [
      { id: "step-1", at: "2026-11-14T10:00:00Z", kind: "other", actor: "agent", summary: "kitchen_brief_read", reason: "" },
      { id: "step-2", at: "2026-11-14T10:01:00Z", kind: "other", actor: "agent", summary: "proposal_explanation_failed", reason: "" },
    ];
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(await screen.findByText("Kitchen brief read")).toBeInTheDocument();
    expect(screen.getByText("No model sentence for a proposal")).toBeInTheDocument();
    expect(screen.queryByText(/kitchen_brief_read|proposal_explanation_failed/)).not.toBeInTheDocument();
  });

  it("leaves the demo's own housekeeping steps out of Latest steps (#1978)", async () => {
    const api = createMockApi();
    const kinds = ["proposal_created", "demo_inbox_cleared", "proposal_explanation_failed", "demo_inbox_cleared", "option_chosen"];
    api.listAudit = async () =>
      mapAudit(kinds.map((kind, i) => ({ event_id: `e-${i}`, kind, actor: "human", at: `2026-11-14T10:0${i}:00Z` })));
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(await screen.findByText("A person chose an option")).toBeInTheDocument();
    expect(screen.getByText("Proposal created")).toBeInTheDocument();
    expect(screen.queryByText("No model sentence for a proposal")).not.toBeInTheDocument();
    expect(screen.queryByText(/Demo inbox reset|Inbox cleared/)).not.toBeInTheDocument();
  });

  describe("Latest steps in Finnish (#1776)", () => {
    afterEach(() => {
      updateLanguage("en", false);
      localStorage.removeItem("purchasing-language");
    });

    it("shows the label of a gateway event in Finnish when the page is in Finnish", async () => {
      updateLanguage("fi"); // stored too: the app reads the stored language when it mounts
      const api = createMockApi();
      api.listAudit = async () =>
        mapAudit([
          { event_id: "e-1", kind: "approval_token_revoked", actor: "operator-cli", at: "2026-11-14T14:57:50+00:00" },
          { event_id: "e-2", kind: "settings_changed", actor: "aron", at: "2026-11-14T15:00:00+00:00" },
        ]);
      renderApp(`/?now=${DEMO_NOW}`, api);

      expect(await screen.findByText("Henkilökohtainen hyväksyntätunnus kumottu")).toBeInTheDocument();
      expect(screen.getByText("Asetuksia muutettu")).toBeInTheDocument();
    });
  });

  it("shows gateway audit kinds as plain words in Latest steps, a new kind too (mock jury, 14 Nov)", async () => {
    const api = createMockApi();
    const kinds = ["approval_token_created", "token_created", "settings_changed", "proposal_changed", "some_future_kind"];
    api.listAudit = async () =>
      mapAudit(kinds.map((kind, i) => ({ event_id: `e-${i}`, kind, actor: "system", at: `2026-11-14T10:0${i}:00Z` })));
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(await screen.findByText("Personal approval token created")).toBeInTheDocument();
    expect(screen.getByText("Kitchen API token created")).toBeInTheDocument();
    expect(screen.getByText("Settings changed")).toBeInTheDocument();
    expect(screen.getByText("Proposal changed")).toBeInTheDocument();
    expect(screen.getByText("Some future kind")).toBeInTheDocument();
    expect(screen.queryByText(/_/)).not.toBeInTheDocument();
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
  it("shows the 5 most urgent stock rows and links the rest to the stock page", async () => {
    const api = createMockApi();
    const ids = ["A", "B", "C", "D", "E", "F", "G"];
    api.getStock = async () =>
      ids.map((id, i) => ({ productId: id, productName: `Item ${id}`, unit: "KG", onHand: i, onOrder: 0, countedAt: null, lastDelivery: null }));
    api.getDemand = async () =>
      ids.map((id) => ({ productId: id, productName: `Item ${id}`, unit: "KG", date: "2026-11-13", need: 10, why: "menu" }));
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(await screen.findByText("Item A")).toBeInTheDocument();
    expect(screen.getByText("Item E")).toBeInTheDocument();
    expect(screen.queryByText("Item F")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "+2 more" })).toHaveAttribute("href", "/stock");
    // A thumb hits it on a phone: the link is at least 44 px high.
    expect(screen.getByRole("link", { name: "+2 more" })).toHaveClass("min-h-11");
    // The tile links on the same page too.
    expect(screen.getByRole("link", { name: "Count stock" })).toHaveClass("min-h-11");
    expect(screen.getByText(/A purchasing agent for professional kitchens/)).toBeInTheDocument();
  });
});
