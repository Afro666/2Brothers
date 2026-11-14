import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

function menu() {
  return within(screen.getAllByRole("navigation", { name: "Main" })[0]);
}

describe("Waiting-approvals count", () => {
  beforeEach(() => localStorage.clear());

  it("shows the count on the Orders entry and the To approve tab, and keeps the link names", async () => {
    renderApp("/approvals", createMockApi());

    const orders = await waitFor(() => {
      const link = menu().getByRole("link", { name: "Orders" });
      expect(link).toHaveAttribute("aria-description", "2 waiting");
      return link;
    });
    expect(orders).toHaveTextContent("2");
    const tab = within(screen.getByRole("navigation", { name: "Orders" })).getByRole("link", { name: "To approve" });
    expect(tab).toHaveAttribute("aria-description", "2 waiting");
  });

  it("drops right after an approval, without navigation", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/approvals", api);
    await waitFor(() =>
      expect(menu().getByRole("link", { name: "Orders" })).toHaveAttribute("aria-description", "2 waiting"),
    );

    await user.click((await screen.findAllByRole("button", { name: /Reject/ }))[0]);
    const dialog = await screen.findByRole("dialog");
    const reason = within(dialog).queryByRole("textbox");
    if (reason) await user.type(reason, "Too much for this week");
    await user.click(within(dialog).getByRole("button", { name: /Reject/ }));

    await waitFor(() =>
      expect(menu().getByRole("link", { name: "Orders" })).toHaveAttribute("aria-description", "1 waiting"),
    );
  });

  it("shows no badge when the count is not known", async () => {
    const api = { ...createMockApi(), listApprovals: () => Promise.reject(new Error("The gateway is down.")) };
    renderApp("/stock", api);

    await screen.findByRole("heading", { level: 1 });
    expect(menu().getByRole("link", { name: "Orders" })).not.toHaveAttribute("aria-description");
  });

  it("shows no badge on the Valio side", async () => {
    localStorage.setItem("purchasing-role", "valio_planner");
    renderApp("/", createMockApi());

    await screen.findByRole("heading", { level: 1 });
    await waitFor(() => expect(screen.queryByText("2 waiting")).not.toBeInTheDocument());
    for (const link of menu().getAllByRole("link")) expect(link).not.toHaveAttribute("aria-description");
  });

  it("opens Requests from the Home button", async () => {
    renderApp("/", createMockApi());

    expect(await screen.findByRole("link", { name: "Request an order" })).toHaveAttribute("href", "/requests");
  });
});
