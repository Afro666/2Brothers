import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiProvider } from "@/api";
import { createMockApi } from "@/api/mock";
import { PENDING_APPROVALS_REFRESH_MS, PendingApprovalsProvider, usePendingApprovals } from "@/lib/pending-approvals";
import { renderApp } from "@/test/render";

function menu() {
  return within(screen.getAllByRole("navigation", { name: "Main" })[0]);
}

/** How many approvals wait in this mock right now. */
async function waiting(api: ReturnType<typeof createMockApi>): Promise<number> {
  return (await api.listApprovals()).filter((approval) => approval.status === "PENDING").length;
}

describe("Waiting-approvals count", () => {
  beforeEach(() => localStorage.clear());

  it("shows the count on the Orders entry and the To approve tab, and keeps the link names", async () => {
    const api = createMockApi();
    const count = await waiting(api);
    expect(count).toBeGreaterThan(0);
    renderApp("/approvals", api);

    const orders = await waitFor(() => {
      const link = menu().getByRole("link", { name: "Orders" });
      expect(link).toHaveAttribute("aria-description", `${count} waiting`);
      return link;
    });
    expect(orders).toHaveTextContent(String(count));
    const tab = within(screen.getByRole("navigation", { name: "Orders" })).getByRole("link", { name: "To approve" });
    expect(tab).toHaveAttribute("aria-description", `${count} waiting`);
  });

  it("drops right after an approval, without navigation", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const before = await waiting(api);
    renderApp("/approvals", api);
    await waitFor(() =>
      expect(menu().getByRole("link", { name: "Orders" })).toHaveAttribute("aria-description", `${before} waiting`),
    );

    await user.click((await screen.findAllByRole("button", { name: /Reject/ }))[0]);
    const dialog = await screen.findByRole("dialog");
    const reason = within(dialog).queryByRole("textbox");
    if (reason) await user.type(reason, "Too much for this week");
    await user.click(within(dialog).getByRole("button", { name: /Reject/ }));

    await waitFor(() =>
      expect(menu().getByRole("link", { name: "Orders" })).toHaveAttribute(
        "aria-description",
        `${before - 1} waiting`,
      ),
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

  describe("reload on an interval", () => {
    afterEach(() => vi.useRealTimers());

    it("shows a new PENDING approval without a page reload", async () => {
      vi.useFakeTimers();
      const base = createMockApi();
      const all = await base.listApprovals();
      const pending = all.filter((approval) => approval.status === "PENDING");
      let shown = pending.slice(0, 1);
      const api = { ...base, listApprovals: () => Promise.resolve(shown) };
      function Count() {
        const { count } = usePendingApprovals();
        return <p>count: {String(count)}</p>;
      }
      render(
        <ApiProvider api={api}>
          <PendingApprovalsProvider>
            <Count />
          </PendingApprovalsProvider>
        </ApiProvider>,
      );
      await act(async () => {});
      expect(screen.getByText("count: 1")).toBeInTheDocument();

      shown = [...pending.slice(0, 1), { ...pending[0], id: `${pending[0].id}-new` }];
      await act(async () => {
        await vi.advanceTimersByTimeAsync(PENDING_APPROVALS_REFRESH_MS);
      });
      expect(screen.getByText("count: 2")).toBeInTheDocument();
    });
  });
});
