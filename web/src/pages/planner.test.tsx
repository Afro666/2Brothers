import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { ApiError } from "@/api/types";
import { formatEur, formatNumber } from "@/lib/format";
import { updateLanguage } from "@/lib/i18n";
import { renderApp } from "@/test/render";

/** Fixes "today" for the page; only `Date` is faked, so user events and timers still run. */
function onDay(date: string) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(`${date}T12:00:00Z`));
}

describe("PlannerPage", () => {
  beforeEach(() => {
    localStorage.clear();
    updateLanguage("en", false);
  });
  afterEach(() => vi.useRealTimers());

  it("proposes an order for the week and points to the approvals page", async () => {
    onDay("2026-11-18");
    const user = userEvent.setup();
    const api = createMockApi();
    const propose = vi.fn(async () => ({
      id: "prop-plan-1",
      status: "READY" as const,
      totalInclVat: 212.4,
      lineCount: 3,
      needCount: 5,
      uncountedCount: 2,
      shortfallCount: 1,
      reasonCodes: ["PARTIAL_STOCK"],
    }));
    api.proposeOrderForPlan = propose;
    const approve = vi.spyOn(api, "approve");
    renderApp("/planner?week=2026-W47", api);

    await user.click(await screen.findByRole("button", { name: "Propose order for this week" }));

    const link = await screen.findByRole("link", { name: "Orders > To approve" });
    expect(link).toHaveAttribute("href", "/approvals");
    const message = link.closest("[role='status']") as HTMLElement;
    expect(message).toHaveAttribute("aria-live", "polite");
    expect(message).toHaveTextContent(
      `Proposal ready: 3 lines, ${formatEur(212.4)}. A person approves it in Orders > To approve.`,
    );
    expect(message).toHaveTextContent("2 products were never counted, so their full need is proposed.");
    expect(message).toHaveTextContent("1 product cannot be fully covered.");
    // Monday to Sunday of the shown week; delivery on the first day that is not in the past.
    expect(propose).toHaveBeenCalledTimes(1);
    expect(propose).toHaveBeenCalledWith("2026-11-16", "2026-11-22", "2026-11-18");
    expect(approve).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Propose order for this week" })).toBeEnabled();
  });

  it("says that a returned proposal was already approved and links to the orders page", async () => {
    onDay("2026-11-18");
    const user = userEvent.setup();
    const api = createMockApi();
    api.proposeOrderForPlan = async () => ({
      id: "prop-plan-2",
      status: "APPROVED" as const,
      totalInclVat: 98.5,
      lineCount: 2,
      needCount: 2,
      uncountedCount: 0,
      shortfallCount: 0,
      reasonCodes: [],
    });
    renderApp("/planner?week=2026-W47", api);

    await user.click(await screen.findByRole("button", { name: "Propose order for this week" }));

    const text = await screen.findByText(/Already approved/);
    const message = text.closest("[role='status']") as HTMLElement;
    expect(message).toHaveTextContent(`Already approved: 2 lines, ${formatEur(98.5)}. See it in Order history.`);
    expect(message).not.toHaveTextContent("automatically");
    expect(within(message).getByRole("link", { name: "Order history" })).toHaveAttribute("href", "/orders");
    expect(within(message).queryByRole("link", { name: "Orders > To approve" })).toBeNull();
  });

  it("says that stock covers the plan when the gateway answers NOTHING_NEEDED", async () => {
    onDay("2026-11-13");
    const user = userEvent.setup();
    // The sample data has no menu entries in week 48.
    renderApp("/planner?week=2026-W48", createMockApi());

    await user.click(await screen.findByRole("button", { name: "Propose order for this week" }));

    expect(await screen.findByText("Stock covers this week's plan. Nothing to order.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Orders > To approve" })).not.toBeInTheDocument();
  });

  it("shows the gateway's message for any other error", async () => {
    onDay("2026-11-13");
    const user = userEvent.setup();
    const api = createMockApi();
    api.proposeOrderForPlan = async () => {
      throw new ApiError("INVALID_REQUEST", "from must be on or before to, at most 31 days apart");
    };
    renderApp("/planner?week=2026-W47", api);

    await user.click(await screen.findByRole("button", { name: "Propose order for this week" }));

    expect(await screen.findByText("from must be on or before to, at most 31 days apart")).toBeInTheDocument();
  });

  it("does not propose an order for a week that is in the past", async () => {
    onDay("2026-11-25");
    renderApp("/planner?week=2026-W47", createMockApi());

    const button = await screen.findByRole("button", { name: "Propose order for this week" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription("This week is in the past, so there is nothing to order for it.");
  });

  it("shows the menu and saved demand for the requested week", async () => {
    const user = userEvent.setup();
    renderApp("/planner?week=2026-W47", createMockApi());

    expect(await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" })).toBeInTheDocument();
    const propose = screen.getByRole("button", { name: "Propose order for this week" });
    expect(
      screen.getByText("Plan the week's menus and covers (guests per meal). The needs below come from this plan."),
    ).toBeInTheDocument();
    const monday = (await screen.findByRole("heading", { name: /Monday/ })).closest("[data-slot='card']");
    expect(monday).not.toBeNull();
    expect(propose.compareDocumentPosition(monday as HTMLElement) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
    expect(screen.getByRole("link", { name: "Check stock" })).toHaveAttribute("href", "/stock");
    expect(screen.getByRole("link", { name: "Ask the Buyer for an order" })).toHaveAttribute("href", "/requests");
    expect(within(monday as HTMLElement).getByText(/Rice pudding/)).toBeInTheDocument();
    expect(within(monday as HTMLElement).getByText(/180 covers/)).toBeInTheDocument();
    const dailyNeed = screen.getByText(/180 covers x 0\.15 L \(Rice pudding\)/);
    expect(dailyNeed).not.toBeVisible();
    const toggle = screen.getByRole("button", { name: "Daily needs for Valio Eila 3 % milk" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(dailyNeed).toBeVisible();
  });

  it("opens with one formatted, closed row per product", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    api.getDemand = async () => [
      {
        productId: "POTATO",
        productName: "POTATO WASHED 1KG",
        unit: "KG",
        date: "2026-11-16",
        need: 28.24,
        why: "176.5 x 0.16 KG (Roast chicken)",
      },
      {
        productId: "POTATO",
        productName: "POTATO WASHED 1KG",
        unit: "KG",
        date: "2026-11-17",
        need: 23.66,
        why: "147.875 x 0.16 KG (Roast chicken)",
      },
      {
        productId: "BUN",
        productName: "Cinnamon bun",
        unit: "PCS",
        date: "2026-11-16",
        need: 2009,
        why: "2,009 covers x 1 PCS (Coffee service)",
      },
    ];
    renderApp("/planner?week=2026-W47", api);

    const potatoToggle = await screen.findByRole("button", { name: "Daily needs for POTATO WASHED 1KG" });
    expect(screen.getAllByRole("button", { name: /Daily needs for/ })).toHaveLength(2);
    expect(screen.getByText("51.9 kg total")).toBeInTheDocument();
    expect(screen.getByText("2,009 pieces total")).toBeInTheDocument();
    const monday = screen.getByText(/28\.2 kg/);
    expect(monday).not.toBeVisible();
    expect(screen.getByRole("button", { name: "Daily needs for Cinnamon bun" })).toHaveAttribute("aria-expanded", "false");
    await user.click(potatoToggle);
    expect(monday).toBeVisible();
  });

  it("names both months when the week crosses a month end", async () => {
    renderApp("/planner?week=2026-W49", createMockApi());

    expect(await screen.findByRole("heading", { name: "Week 49, 30 Nov to 6 Dec 2026" })).toBeInTheDocument();
  });

  it("names both years when the week crosses New Year", async () => {
    renderApp("/planner?week=2026-W53", createMockApi());

    expect(await screen.findByRole("heading", { name: "Week 53, 28 Dec 2026 to 3 Jan 2027" })).toBeInTheDocument();
  });

  it("leads ordered energy with its meaning and links to the counted orders", async () => {
    const api = createMockApi();
    const nutrition = await api.getNutrition("2026-11-16", "2026-11-22");
    api.getNutrition = async () => ({
      ...nutrition,
      ordered: { ...nutrition.ordered, kcal: 1779230 },
      orderedVsPlanned: 1.27,
    });
    renderApp("/planner?week=2026-W47", api);

    const ordered = await screen.findByRole("link", {
      name: `Ordered so far covers at least 127% of the plan's energy: ${formatNumber(1779230)} kcal.`,
    });
    expect(ordered).toHaveAttribute("href", "/orders");
    expect(ordered.closest("p")).toHaveTextContent("Counted from 3 of 4 order lines.");
    const dailyToggle = screen.getAllByRole("button", { name: /Daily needs for/ })[0];
    expect(dailyToggle.compareDocumentPosition(ordered) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(0);
  });

  it("says the plain share when every order line is counted", async () => {
    const api = createMockApi();
    const nutrition = await api.getNutrition("2026-11-16", "2026-11-22");
    api.getNutrition = async () => ({
      ...nutrition,
      ordered: { ...nutrition.ordered, kcal: 1779230, knownLines: nutrition.ordered.lines },
      orderedVsPlanned: 1.27,
    });
    renderApp("/planner?week=2026-W47", api);

    expect(
      await screen.findByRole("link", { name: `Ordered so far covers 127% of the plan's energy: ${formatNumber(1779230)} kcal.` }),
    ).toHaveAttribute("href", "/orders");
  });

  it("explains what an incomplete energy-per-cover number is missing", async () => {
    const api = createMockApi();
    const nutrition = await api.getNutrition("2026-11-16", "2026-11-22");
    api.getNutrition = async () => ({
      ...nutrition,
      days: nutrition.days.map((day, index) => (index === 0 ? { ...day, kcalPerCover: 968, complete: false } : day)),
    });
    renderApp("/planner?week=2026-W47", api);

    expect(
      await screen.findByText("at least 968 kcal per cover: some ingredients have no nutrition data"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/about 968 kcal per cover/)).not.toBeInTheDocument();
  });

  it("translates meal names in Finnish without translating dish data", async () => {
    localStorage.setItem("purchasing-language", "fi");
    updateLanguage("fi", false);
    const api = createMockApi();
    const menu = await api.getMenuPlan("2026-W47");
    api.getMenuPlan = async () => menu.map((entry, index) => (index === 0 ? { ...entry, meal: "Dinner" } : entry));
    renderApp("/planner?week=2026-W47", api);

    expect(await screen.findByText("Päivällinen")).toBeInTheDocument();
    expect(screen.getAllByText("Aamiainen")).toHaveLength(2);
    expect(screen.getAllByText("Lounas")).toHaveLength(2);
    expect(screen.getAllByText("Jälkiruoka")).toHaveLength(3);
    expect(screen.queryByText("Dinner")).not.toBeInTheDocument();
    expect(screen.queryByText("Breakfast")).not.toBeInTheDocument();
    expect(screen.getAllByText(/Rice pudding/).length).toBeGreaterThan(0);
  });

  it("shows a meal name that is not a known meal unchanged in Finnish", async () => {
    localStorage.setItem("purchasing-language", "fi");
    updateLanguage("fi", false);
    const api = createMockApi();
    const menu = await api.getMenuPlan("2026-W47");
    api.getMenuPlan = async () =>
      menu.map((entry, index) =>
        index === 0 ? { ...entry, meal: "Delete" } : index === 1 ? { ...entry, meal: "Cancel {x}" } : entry,
      );
    renderApp("/planner?week=2026-W47", api);

    expect(await screen.findByText("Delete")).toBeInTheDocument();
    expect(screen.getByText("Cancel {x}")).toBeInTheDocument();
    expect(screen.queryByText("Poista", { selector: "p" })).not.toBeInTheDocument();
  });

  it("opens on next week when no week is asked for", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-13T12:00:00Z"));
    try {
      renderApp("/planner", createMockApi());
      expect(await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" })).toBeInTheDocument();
      expect((await screen.findAllByText(/Rice pudding/)).length).toBeGreaterThan(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("adds and saves an entry, then refreshes the demand table", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/planner?week=2026-W47", api);

    await user.click(await screen.findByRole("button", { name: "Add to Monday" }));
    const dialog = screen.getByRole("dialog");
    await user.clear(within(dialog).getByRole("textbox", { name: "Meal" }));
    await user.type(within(dialog).getByRole("textbox", { name: "Meal" }), "Dinner");
    await user.clear(within(dialog).getByRole("spinbutton", { name: "Covers" }));
    await user.type(within(dialog).getByRole("spinbutton", { name: "Covers" }), "50");
    await user.click(within(dialog).getByRole("button", { name: "Add entry" }));
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save week" }));
    await waitFor(async () => {
      expect(await api.getMenuPlan("2026-W47")).toHaveLength(9);
    });
    expect(await screen.findByText(/Dinner/)).toBeInTheDocument();
    expect(await screen.findByText(/50 covers x 0\.15 L \(Rice pudding\)/)).toBeInTheDocument();
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
  });

  it("rejects blank covers when adding an entry", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/planner?week=2026-W47", api);

    await user.click(await screen.findByRole("button", { name: "Add to Monday" }));
    const dialog = screen.getByRole("dialog");
    const covers = within(dialog).getByRole("spinbutton", { name: "Covers" });
    expect(covers).toHaveValue(null);
    await user.click(within(dialog).getByRole("button", { name: "Add entry" }));

    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "Covers must be a whole number greater than or equal to zero.",
    );
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
    expect(await api.getMenuPlan("2026-W47")).toHaveLength(8);
  });

  it("moves to an empty week and discards removals", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/planner?week=2026-W47", api);
    await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" });

    const monday = (await screen.findByRole("heading", { name: /Monday/ })).closest("[data-slot='card']") as HTMLElement;
    await user.click(within(monday).getAllByRole("button", { name: "Remove" })[0]);
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(within(monday).getByText(/Rice pudding/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next week" }));
    expect(await screen.findByRole("heading", { name: "Week 48, 23 to 29 Nov 2026" })).toBeInTheDocument();
    expect(await screen.findByText("No menu entries this week")).toBeInTheDocument();
    expect(await api.getMenuPlan("2026-W48")).toEqual([]);
  });
});
