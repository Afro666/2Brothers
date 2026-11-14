import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { ApiError } from "@/api/types";
import { formatEur } from "@/lib/format";
import { renderApp } from "@/test/render";

/** Fixes "today" for the page; only `Date` is faked, so user events and timers still run. */
function onDay(date: string) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(`${date}T12:00:00Z`));
}

describe("PlannerPage", () => {
  beforeEach(() => localStorage.clear());
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
    renderApp("/planner?week=2026-W47", createMockApi());

    expect(await screen.findByRole("heading", { name: "Week 47, 16 to 22 Nov 2026" })).toBeInTheDocument();
    const monday = (await screen.findByRole("heading", { name: /Monday/ })).closest("[data-slot='card']");
    expect(monday).not.toBeNull();
    expect(within(monday as HTMLElement).getByText(/Rice pudding/)).toBeInTheDocument();
    expect(within(monday as HTMLElement).getByText(/180 covers/)).toBeInTheDocument();
    expect(screen.getByText(/180 covers x 0\.15 L \(Rice pudding\)/)).toBeInTheDocument();
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
