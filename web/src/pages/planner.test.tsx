import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("PlannerPage", () => {
  beforeEach(() => localStorage.clear());

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
