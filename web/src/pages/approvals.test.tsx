import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mapKitchenSettings } from "@/api/map-planning";
import { createMockApi } from "@/api/mock";
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
  it.each([
    ["on", "Leipomo Demo must confirm stock. If you approve, the order is sent and waits for their confirmation: call or e-mail them."],
    ["off", "Leipomo Demo must confirm stock before this order can be approved."],
    ["absent", "Leipomo Demo must confirm stock before this order can be approved."],
    ["failed", "Leipomo Demo must confirm stock before this order can be approved."],
  ] as const)("shows the supplier-confirm notice when the kitchen setting is %s", async (setting, expected) => {
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

    expect((await screen.findAllByText(expected)).length).toBeGreaterThan(0);
    if (setting === "on") {
      expect(screen.queryByText("Leipomo Demo must confirm stock before this order can be approved.")).toBeNull();
    } else {
      expect(screen.queryByText(/Leipomo Demo must confirm stock\. If you approve/)).toBeNull();
    }
    expect(api.getKitchenSettings).toHaveBeenCalledTimes(1);
  });

  it("keeps the milk proposal visible while awaiting stock confirmation", async () => {
    renderApp("/approvals", createMockApi());
    expect(await screen.findByRole("heading", { name: "Waiting for you (4)" })).toBeVisible();
    expect(await screen.findByText(/Waiting for supplier stock confirmation/)).toBeVisible();
    expect(screen.getAllByRole("button", { name: /^Approve/ }).filter((button) => button.hasAttribute("disabled"))).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Reject" })[0]).toBeEnabled();
  });
  beforeEach(() => localStorage.clear());

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

    const button = (await screen.findAllByRole("button", { name: "Show order lines" }))[1];
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.click(button);

    expect(screen.getByRole("button", { name: "Hide order lines" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByText("Valio Eila 3 % lactose free milk drink 1 L").length).toBeGreaterThan(0);
  });

  it("changes a quantity, approves the new total and records feedback", async () => {
    const user = userEvent.setup();
    const api = withConfirmedStock();
    renderApp("/approvals", api);
    await user.click((await screen.findAllByRole("button", { name: "Show order lines" }))[0]);
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
    await user.click((await screen.findAllByRole("button", { name: "Show order lines" }))[1]);
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

  it("follows the edited lines: approval opens once the line with unconfirmed stock is removed", async () => {
    const user = userEvent.setup();
    renderApp("/approvals", createMockApi());
    await user.click((await screen.findAllByRole("button", { name: "Show order lines" }))[1]);
    await user.type(screen.getByRole("searchbox", { name: "Search products" }), "Arla 1 L");
    await user.click(await screen.findByRole("button", { name: "Add Arla 1 L lactose free fat free UHT milk drink" }));
    // Arla's stock is known, Eila's is not: the order is still blocked.
    await screen.findByRole("button", { name: "Remove Arla 1 L lactose free fat free UHT milk drink" });
    expect(screen.getByText(/Waiting for supplier stock confirmation/)).toBeVisible();
    expect(screen.getAllByRole("button", { name: /^Approve/ })[1]).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Remove Valio Eila 3 % lactose free milk drink 1 L" }));
    await waitFor(() => expect(screen.queryByText(/Waiting for supplier stock confirmation/)).toBeNull());
    expect(screen.getAllByRole("button", { name: /^Approve/ })[1]).toBeEnabled();
  });

  it("shows the API message when removing the only line is refused", async () => {
    const user = userEvent.setup();
    renderApp("/approvals", createMockApi());
    await user.click((await screen.findAllByRole("button", { name: "Show order lines" }))[1]);
    await user.click(screen.getByRole("button", { name: "Remove Valio Eila 3 % lactose free milk drink 1 L" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("An order needs at least one line; reject it instead.");
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
