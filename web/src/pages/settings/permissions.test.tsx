import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("Permissions settings", () => {
  beforeEach(() => localStorage.clear());

  it("renders the three groups", async () => {
    renderApp("/settings/permissions");

    const alone = await screen.findByRole("list", { name: "The Buyer does alone" });
    expect(within(alone).getAllByRole("listitem")).toHaveLength(7);
    expect(within(alone).getByText("Refuse unsafe lines")).toBeInTheDocument();

    const person = screen.getByRole("list", { name: "A person signs off" });
    expect(
      within(person)
        .getAllByRole("listitem")
        .map((row) => row.textContent),
    ).toEqual([
      expect.stringContaining("Every order"),
      expect.stringContaining("Any substitute"),
      expect.stringContaining("Standing-order changes"),
      expect.stringContaining("Sharing forecasts"),
    ]);

    const never = screen.getByRole("list", { name: "The Buyer can never" });
    expect(within(never).getAllByRole("listitem")).toHaveLength(3);
    expect(within(never).getByText("Change a quantity after approval")).toBeInTheDocument();
  });

  it("a row opens the audit log filtered to its kind", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/settings/permissions");

    const link = await screen.findByRole("link", { name: /Search the catalog/ });
    expect(link).toHaveAttribute("href", "/audit?kind=search");
    await user.click(link);

    expect(await screen.findByRole("heading", { level: 1, name: "Audit log" })).toBeInTheDocument();
    expect(router.state.location.search).toEqual({ kind: "search" });
    expect(await screen.findByRole("combobox", { name: "Kind" })).toHaveTextContent("Search");
    await screen.findByText(/^\d+ steps?$/);
    const steps = document.querySelectorAll("li[data-kind]");
    expect(steps.length).toBeGreaterThan(0);
    for (const step of steps) expect(step).toHaveAttribute("data-kind", "search");
  });

  it("ignores an audit kind that does not exist", async () => {
    renderApp("/audit?kind=toString");
    expect(await screen.findByText("8 steps")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Kind" })).toHaveTextContent("All kinds");
  });

  it("keeps auto-approve off and disabled, with the learning progress", async () => {
    const user = userEvent.setup();
    renderApp("/settings/permissions");

    const toggle = await screen.findByRole("switch", { name: "Auto-approve small routine orders" });
    expect(toggle).toBeDisabled();
    expect(toggle).not.toBeChecked();
    await user.click(toggle);
    expect(toggle).not.toBeChecked();

    expect(
      screen.getByText(
        "Let the Buyer learn your kitchen first. After about 4 weeks of your approvals and corrections it can approve routine orders under your limit. Substitutes, unknown stock, allergens and anything over budget always come to you.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/unlocks after the learning period and is not available yet/)).toBeInTheDocument();
    const progress = await screen.findByLabelText("Learning progress");
    expect(progress).toHaveTextContent("Weeks1 of 4");
    expect(progress).toHaveTextContent("Decisions6 of 20");
    expect(progress).toHaveTextContent("Edit rate33 % (needs 10 % or less)");
  });

  it("stays off and disabled past the learning thresholds, and shows an unknown edit rate as unknown", async () => {
    const api = createMockApi();
    api.getAutoApproveLearning = async () => ({
      weeks: 6,
      weeksNeeded: 4,
      decisions: 40,
      decisionsNeeded: 20,
      editRate: null,
      maxEditRate: 0.1,
    });
    renderApp("/settings/permissions", api);

    expect(await screen.findByLabelText("Learning progress")).toHaveTextContent("Edit rateunknown");
    const toggle = screen.getByRole("switch", { name: "Auto-approve small routine orders" });
    expect(toggle).toBeDisabled();
    expect(toggle).not.toBeChecked();
  });
});
