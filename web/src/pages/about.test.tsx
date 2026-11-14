import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { renderApp } from "@/test/render";

describe("AboutPage", () => {
  beforeEach(() => localStorage.clear());

  it("explains the flow, the two sides and the trust rules", async () => {
    renderApp("/about");
    expect(await screen.findByRole("heading", { level: 1, name: "About Kitchen Buyer" })).toBeInTheDocument();
    const steps = screen.getAllByRole("list").find((list) => list.tagName === "OL")!;
    expect(
      within(steps)
        .getAllByRole("heading", { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual(["Request", "Lookup", "Order at a fixed price", "Approval"]);
    for (const name of [
      "The kitchen",
      "Valio",
      "A person approves every order",
      "Unknown is never treated as zero or safe",
      "Everything is audited",
      "Forecasts are shared only with consent",
    ]) {
      expect(screen.getByRole("heading", { level: 3, name })).toBeInTheDocument();
    }
  });

  it.each(["Chef", "Valio planner"])("is linked from the nav when viewing as %s", async (role) => {
    const user = userEvent.setup();
    renderApp("/");
    await user.click(await screen.findByRole("combobox", { name: "Viewing as" }));
    await user.click(await screen.findByRole("option", { name: role }));
    await user.click(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "About" }));
    expect(await screen.findByRole("heading", { level: 1, name: "About Kitchen Buyer" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "About" })).toHaveAttribute("aria-current", "page");
  });
});
