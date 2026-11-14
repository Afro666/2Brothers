import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mapKitchenSettings } from "@/api/map-planning";
import { createMockApi } from "@/api/mock";
import { ApiError } from "@/api/types";
import { renderApp } from "@/test/render";

function withConfirmedStock() {
  const api = createMockApi();
  const getOrder = api.getOrder;
  api.getOrder = async (id) => {
    const order = structuredClone(await getOrder(id));
    order.lines.forEach((line) => {
      line.offer.availableAmount = line.quantity;
    });
    return order;
  };
  return api;
}

describe("ApprovalsPage", () => {
  it.each(["on", "off", "absent", "failed"] as const)(
    "says the order is sent and waits for the supplier whatever the kitchen setting (%s)",
    async (setting) => {
      const api = createMockApi();
      const listApprovals = api.listApprovals;
      api.listApprovals = async () => (await listApprovals()).map((approval, index) => index === 0 ? {
        ...approval,
        suppliersToConfirm: [{ supplierId: "sup-bakery", name: "Leipomo Demo" }],
      } : approval);
      const getKitchenSettings = api.getKitchenSettings;
      api.getKitchenSettings = vi.fn(async () => {
        if (setting === "failed") throw new Error("Settings unavailable");
        if (setting === "absent") return mapKitchenSettings({});
        return { ...(await getKitchenSettings()), approveUnconfirmedManual: setting === "on" };
      });
      renderApp("/approvals", api);

      expect((await screen.findAllByText("Leipomo Demo must confirm")).length).toBeGreaterThan(0);
      for (const inspect of await screen.findAllByRole("button", { name: /^Inspect/ })) await userEvent.click(inspect);
      expect((await screen.findAllByText("Leipomo Demo must confirm stock. If you approve, the order is sent and waits for their confirmation: call or e-mail them.")).length).toBeGreaterThan(0);
      expect(screen.queryByText(/before this order can be approved/)).toBeNull();
    },
  );

  it("keeps the milk proposal visible while awaiting stock confirmation", async () => {
    renderApp("/approvals", createMockApi());
    expect(await screen.findByRole("heading", { name: "Waiting for you (4)" })).toBeVisible();
    // Compact: a chip names who must confirm; the full sentence is under Inspect.
    expect(await screen.findByText("Valio must confirm 1")).toBeVisible();
    await userEvent.click(screen.getAllByRole("button", { name: /^Inspect/ })[1]);
    expect(await screen.findByText("Some lines wait for the supplier's stock confirmation. You can still approve: the order is sent and marked as waiting for the supplier.")).toBeVisible();
    expect(screen.getAllByRole("button", { name: /^Approve/ }).filter((button) => button.hasAttribute("disabled"))).toHaveLength(0);
    expect(screen.getAllByRole("button", { name: "Reject" })[0]).toBeEnabled();
  });
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    delete window.Telegram;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("puts a valid linked proposal first, open, scrolled to and focused", async () => {
    const scroll = vi.spyOn(Element.prototype, "scrollIntoView");
    renderApp("/approvals?proposal=APR-312");

    const heading = await screen.findByRole("heading", { name: "Waiting for you (4)" });
    const card = document.getElementById("proposal-ORD-1044");
    expect(card).not.toBeNull();
    expect(heading.closest("section")?.querySelector('[id^="proposal-"]')).toBe(card);
    expect(within(card!).getByRole("button", { name: /Approve €148\.76 incl VAT/ })).toBeVisible();
    await waitFor(() => expect(card).toHaveFocus());
    expect(scroll.mock.contexts).toContain(card);
  });

  it("keeps the normal inbox and says a linked proposal is held by a recall", async () => {
    const api = createMockApi();
    const listApprovals = api.listApprovals;
    api.listApprovals = async () =>
      (await listApprovals()).map((approval) =>
        approval.id === "APR-312" ? { ...approval, status: "BLOCKED_BY_RECALL" as const } : approval,
      );
    renderApp("/approvals?proposal=APR-312", api);

    expect(await screen.findByText("Proposal APR-312 is held by a recall and cannot be approved.")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Held by a recall (1)" })).toBeVisible();
  });

  it("keeps the normal inbox and reports an unknown linked proposal", async () => {
    renderApp("/approvals?proposal=APR-DOES-NOT-EXIST");

    expect(await screen.findByText("Proposal APR-DOES-NOT-EXIST was not found.")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Waiting for you (4)" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Decided" })).toBeVisible();
  });

  it("keeps the normal inbox and reports an already decided linked proposal", async () => {
    renderApp("/approvals?proposal=APR-UNKNOWN-1046");

    expect(await screen.findByText("Proposal APR-UNKNOWN-1046 has already been decided.")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Waiting for you (4)" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Decided" })).toBeVisible();
  });

  it("hides the menu in Telegram and closes the Mini App two seconds after approval", async () => {
    const ready = vi.fn();
    const expand = vi.fn();
    const close = vi.fn();
    window.Telegram = { WebApp: { ready, expand, close } };
    renderApp("/approvals?proposal=APR-312", withConfirmedStock());

    const approve = await screen.findByRole("button", { name: /Approve €148\.76 incl VAT/ });
    expect(ready).toHaveBeenCalledTimes(1);
    expect(expand).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Open menu" })).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(approve.closest("main")).toHaveClass("w-full");

    fireEvent.click(approve);
    const dialog = screen.getByRole("dialog", { name: "Approve this order?" });
    vi.useFakeTimers();
    fireEvent.click(within(dialog).getByRole("button", { name: "Yes, approve €148.76" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByTestId("approval-toast")).toHaveTextContent("Approved: €148.76 incl VAT");
    expect(close).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1999);
    expect(close).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("keeps the Mini App open when the gateway refuses the approval", async () => {
    const close = vi.fn();
    window.Telegram = { WebApp: { ready: vi.fn(), expand: vi.fn(), close } };
    const api = withConfirmedStock();
    api.failNextApprove("TOTAL_MISMATCH", "The total moved.");
    renderApp("/approvals?proposal=APR-312", api);

    fireEvent.click(await screen.findByRole("button", { name: /Approve €148\.76 incl VAT/ }));
    const dialog = screen.getByRole("dialog", { name: "Approve this order?" });
    vi.useFakeTimers();
    fireEvent.click(within(dialog).getByRole("button", { name: "Yes, approve €148.76" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByRole("alert")).toHaveTextContent("The total moved.");
    expect(close).not.toHaveBeenCalled();
  });

  it("does not close the Mini App after the page is gone, even after two quick approvals", async () => {
    const close = vi.fn();
    window.Telegram = { WebApp: { ready: vi.fn(), expand: vi.fn(), close } };
    const { api } = renderApp("/approvals?proposal=APR-312", withConfirmedStock());
    const approved = async () => (await api.listApprovals()).filter(({ status }) => status === "APPROVED").length;
    const approvedBefore = await approved();

    fireEvent.click(await screen.findByRole("button", { name: /Approve €148\.76 incl VAT/ }));
    vi.useFakeTimers();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Yes, approve €148.76" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect((await api.getApproval("APR-312")).status).toBe("APPROVED");
    fireEvent.click(screen.getAllByRole("button", { name: /^Approve €/ })[0]);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: /^Yes, approve/ }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(await approved()).toBe(approvedBefore + 2);
    cleanup();
    vi.advanceTimersByTime(3000);
    expect(close).not.toHaveBeenCalled();
  });

  it("reads an all-digit linked proposal id as text", async () => {
    renderApp("/approvals?proposal=312");

    expect(await screen.findByText("Proposal 312 was not found.")).toBeVisible();
  });

  it("shows the pending approval and its total, then reloads it under Decided", async () => {
    const user = userEvent.setup();
    const api = withConfirmedStock();
    renderApp("/approvals", api);

    expect(await screen.findByRole("heading", { name: "Waiting for you (4)" })).toBeInTheDocument();
    expect(screen.getByText("€148.76")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Approve €148\.76 incl VAT/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €148.76" }));

    expect(await screen.findByRole("heading", { name: "Decided" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Waiting for you (3)" })).toBeInTheDocument();
    expect(await screen.findByTestId("approval-toast")).toHaveTextContent("Approved: €148.76 incl VAT");
    await waitFor(async () => {
      const events = await api.listAudit();
      expect(events.filter((event) => event.kind === "approval").at(-1)).toMatchObject({
        actor: "human",
        orderId: "ORD-1044",
        summary: "Approved ORD-1044",
      });
    });
  });

  it("tells the person to call the supplier named by the answered order", async () => {
    const user = userEvent.setup();
    const api = withConfirmedStock();
    const getOrder = api.getOrder;
    api.getOrder = async (id) => ({
      ...(await getOrder(id)),
      supplierMustConfirm: id === "ORD-1044" ? ["SUP-BAKERY"] : [],
    });
    renderApp("/approvals", api);

    await user.click(await screen.findByRole("button", { name: /Approve €148\.76 incl VAT/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €148.76" }));

    expect(await screen.findByTestId("approval-toast")).toHaveTextContent(
      "Order placed. Call Töölö Bakery to confirm.",
    );
  });

  it("keeps the approval waiting and shows the gateway error", async () => {
    const user = userEvent.setup();
    const api = withConfirmedStock();
    api.failNextApprove("TOTAL_MISMATCH", "The total moved.");
    renderApp("/approvals", api);

    await user.click(await screen.findByRole("button", { name: /Approve €148\.76 incl VAT/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €148.76" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The total moved.");
    expect(screen.getByRole("heading", { name: "Waiting for you (4)" })).toBeInTheDocument();
    expect(screen.queryByTestId("approval-toast")).not.toBeInTheDocument();
  });

  it("records a rejection reason in the audit log", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/approvals", api);

    await user.click((await screen.findAllByRole("button", { name: "Reject" }))[1]);
    const dialog = await screen.findByRole("dialog", { name: "Reject this order?" });
    await user.type(within(dialog).getByRole("textbox", { name: "Reason (optional)" }), "Too much milk");
    await user.click(within(dialog).getByRole("button", { name: "Reject" }));

    await screen.findByRole("heading", { name: "Decided" });
    await waitFor(async () => {
      const events = await api.listAudit();
      expect(events.filter((event) => event.kind === "approval").at(-1)).toMatchObject({
        actor: "human",
        reason: "Too much milk",
      });
    });
  });

  it("reveals the order line when requested", async () => {
    const user = userEvent.setup();
    renderApp("/approvals", createMockApi());

    const button = (await screen.findAllByRole("button", { name: /^Inspect/ }))[1];
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.click(button);

    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByText("Valio Eila 3 % lactose free milk drink 1 L").length).toBeGreaterThan(0);
  });

  it("changes a quantity, approves the new total and records feedback", async () => {
    const user = userEvent.setup();
    const api = withConfirmedStock();
    renderApp("/approvals", api);
    await user.click((await screen.findAllByRole("button", { name: /^Inspect/ }))[0]);
    const originalQuantity = screen.getByRole("spinbutton", {
      name: "Quantity for Arla 1 L lactose free fat free UHT milk drink (ST)",
    });
    await user.clear(originalQuantity);
    await user.type(originalQuantity, "40");
    await user.click(screen.getByRole("button", { name: "Update Arla 1 L lactose free fat free UHT milk drink" }));

    const approve = await screen.findByRole("button", { name: /Approve €116\.68 incl VAT/ });
    await user.click(approve);
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    expect(within(dialog).getByText(/€102\.80 ex VAT \(€116\.68 incl VAT\)/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €116.68" }));

    await waitFor(async () => {
      expect(await api.listFeedback({ orderId: "ORD-1044" })).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ kind: "QUANTITY_CHANGED", productId: "462775", from: 51, to: 40 }),
          expect.objectContaining({ kind: "APPROVED" }),
        ]),
      );
    });
  });

  it("adds a product using its suggested quantity", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/approvals", api);
    await user.click((await screen.findAllByRole("button", { name: /^Inspect/ }))[1]);
    await user.click(screen.getByRole("button", { name: "Add products" }));
    const search = screen.getByRole("searchbox", { name: "Search products" });
    await user.type(search, "Arla 1 L");
    const productRow = screen.getByText("Arla 1 L lactose free fat free UHT milk drink").closest("li");
    expect(productRow).not.toBeNull();
    await user.click(
      within(productRow as HTMLElement).getByRole("button", {
        name: "Add Arla 1 L lactose free fat free UHT milk drink",
      }),
    );

    expect(await screen.findByRole("button", { name: /Approve €2,213\.33 incl VAT/ })).toBeInTheDocument();
    expect((await api.getOrder("ORD-1043")).lines).toHaveLength(2);
    const lineQuantities = screen.getAllByRole("spinbutton", { name: /Quantity for .* \(ST\)/ });
    const updateButtons = screen.getAllByRole("button", { name: /^Update / });
    expect(lineQuantities).toHaveLength(3);
    expect(updateButtons).toHaveLength(2);
    expect(new Set(lineQuantities.map((input) => (input as HTMLInputElement).labels?.[0]?.textContent)).size).toBe(3);
    expect(new Set(updateButtons.map((button) => button.getAttribute("aria-label"))).size).toBe(2);
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Add Arla 1 L lactose free fat free UHT milk drink" })).toBeNull(),
    );
    await user.click(screen.getByRole("button", { name: "Remove Arla 1 L lactose free fat free UHT milk drink" }));
    expect(
      await screen.findByRole("button", { name: "Add Arla 1 L lactose free fat free UHT milk drink" }),
    ).toBeInTheDocument();
    expect(await api.listFeedback({ orderId: "ORD-1043" })).toEqual(
      expect.arrayContaining([expect.objectContaining({ kind: "LINE_ADDED", productId: "462775", to: 1 })]),
    );
  });

  it("follows the edited lines: the waiting notice goes once the line with unconfirmed stock is removed", async () => {
    const user = userEvent.setup();
    renderApp("/approvals", createMockApi());
    await user.click((await screen.findAllByRole("button", { name: /^Inspect/ }))[1]);
    await user.click(screen.getByRole("button", { name: "Add products" }));
    await user.type(screen.getByRole("searchbox", { name: "Search products" }), "Arla 1 L");
    await user.click(await screen.findByRole("button", { name: "Add Arla 1 L lactose free fat free UHT milk drink" }));
    // Arla's stock is known, Eila's is not: the order still waits for the supplier, but can be approved.
    await screen.findByRole("button", { name: "Remove Arla 1 L lactose free fat free UHT milk drink" });
    expect(screen.getByText(/wait for the supplier's stock confirmation/)).toBeVisible();
    expect(screen.getAllByRole("button", { name: /^Approve/ })[1]).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Remove Valio Eila 3 % lactose free milk drink 1 L" }));
    await waitFor(() => expect(screen.queryByText(/wait for the supplier's stock confirmation/)).toBeNull());
    expect(screen.getAllByRole("button", { name: /^Approve/ })[1]).toBeEnabled();
  });

  it("after a lost answer it reloads the inbox and does not say the proposal is unchanged", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const listed = vi.spyOn(api, "listApprovals");
    api.changeProposal = async () => {
      throw new ApiError("NETWORK", "Could not reach the gateway.");
    };
    renderApp("/approvals", api);
    await user.click((await screen.findAllByRole("button", { name: /^Inspect/ }))[1]);
    const before = listed.mock.calls.length;
    await user.click(screen.getByRole("button", { name: "Remove Valio Eila 3 % lactose free milk drink 1 L" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("the change may or may not be saved");
    expect(alert).not.toHaveTextContent("unchanged");
    await waitFor(() => expect(listed.mock.calls.length).toBeGreaterThan(before));
  });

  it("two fast presses send one change", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    let finish: (() => void) | undefined;
    const change = vi.fn(() => new Promise<never>((_, reject) => { finish = () => reject(new ApiError("NOT_PENDING", "no")); }));
    api.changeProposal = change;
    renderApp("/approvals", api);
    await user.click((await screen.findAllByRole("button", { name: /^Inspect/ }))[1]);
    const remove = screen.getByRole("button", { name: "Remove Valio Eila 3 % lactose free milk drink 1 L" });
    fireEvent.click(remove);
    fireEvent.click(remove);
    expect(change).toHaveBeenCalledTimes(1);
    finish?.();
    expect(await screen.findByRole("alert")).toHaveTextContent("no longer waiting for approval");
  });

  it("shows the API message when removing the only line is refused", async () => {
    const user = userEvent.setup();
    renderApp("/approvals", createMockApi());
    await user.click((await screen.findAllByRole("button", { name: /^Inspect/ }))[1]);
    await user.click(screen.getByRole("button", { name: "Remove Valio Eila 3 % lactose free milk drink 1 L" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not change this proposal: An order needs at least one line; reject it instead. The proposal is unchanged.",
    );
  });

  it("keeps rejection feedback with the reason", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/approvals", api);
    await user.click((await screen.findAllByRole("button", { name: "Reject" }))[1]);
    const dialog = await screen.findByRole("dialog", { name: "Reject this order?" });
    await user.type(within(dialog).getByRole("textbox", { name: "Reason (optional)" }), "Wrong fat percentage");
    await user.click(within(dialog).getByRole("button", { name: "Reject" }));
    await waitFor(async () =>
      expect(await api.listFeedback()).toEqual(
        expect.arrayContaining([expect.objectContaining({ kind: "REJECTED", reason: "Wrong fat percentage" })]),
      ),
    );
  });

  it("stores a null rejection reason and keeps the fallback in the audit event", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/approvals", api);
    await user.click((await screen.findAllByRole("button", { name: "Reject" }))[1]);
    const dialog = await screen.findByRole("dialog", { name: "Reject this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Reject" }));

    await waitFor(async () => {
      expect(await api.listFeedback()).toEqual(
        expect.arrayContaining([expect.objectContaining({ kind: "REJECTED", reason: null })]),
      );
      expect(await api.listAudit()).toEqual(
        expect.arrayContaining([expect.objectContaining({ kind: "approval", reason: "No reason given." })]),
      );
    });
  });
});
