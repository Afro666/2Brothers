import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("audit page", () => {
  beforeEach(() => localStorage.clear());

  it("shows the milk-case steps in time order", async () => {
    renderApp("/audit");
    await screen.findByText("1,000 L lactose-free milk by Monday");
    const timeline = screen.getAllByRole("list").at(-1);
    expect(timeline).toBeDefined();
    const summaries = within(timeline!).getAllByText(
      /lactose-free milk|Searched|Price and availability|Split:|ORD-1042|ORD-1043|Asked/,
    );

    expect(summaries[0]).toHaveTextContent("1,000 L lactose-free milk by Monday");
    expect(summaries.at(-1)).toHaveTextContent("Asked the buyer to approve ORD-1043");
    expect(screen.getByText("8 steps")).toBeInTheDocument();
  });

  it("filters by order and restores all steps with Clear filters", async () => {
    const user = userEvent.setup();
    renderApp("/audit");
    await screen.findByText("8 steps");

    await user.click(screen.getByRole("combobox", { name: "Order" }));
    await user.click(await screen.findByRole("option", { name: "ORD-1042" }));
    expect(await screen.findByText("2 steps")).toBeInTheDocument();
    expect(screen.getByText("ORD-1042 placed for Mon 16 Nov")).toBeInTheDocument();
    expect(screen.queryByText("Asked the buyer to approve ORD-1043")).not.toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "Actor" }));
    await user.click(await screen.findByRole("option", { name: "Valio" }));
    expect(await screen.findByText("No audit steps match these filters")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("8 steps")).toBeInTheDocument();
    expect(screen.getByText("Asked the buyer to approve ORD-1043")).toBeInTheDocument();
  });

  it("preserves source order when event times are equal", async () => {
    const api = createMockApi();
    const listAudit = api.listAudit.bind(api);
    api.listAudit = async (filter) => {
      const events = await listAudit(filter);
      return [
        { ...events[1], id: "same-a", at: events[0].at, summary: "First at same time" },
        { ...events[0], id: "same-b", at: events[0].at, summary: "Second at same time" },
      ];
    };
    renderApp("/audit", api);
    await screen.findByText("First at same time");
    const timeline = screen.getAllByRole("list").at(-1);
    expect(timeline).toBeDefined();
    const summaries = within(timeline!).getAllByText(/same time/);
    expect(summaries[0]).toHaveTextContent("First at same time");
    expect(summaries[1]).toHaveTextContent("Second at same time");
  });
});
