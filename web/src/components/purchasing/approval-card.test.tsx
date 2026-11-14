import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ADD_SEARCH_DEBOUNCE_MS, ApprovalCard } from "@/components/purchasing/approval-card";
import { mapApproval } from "@/api/gateway-map";
import { ApiError } from "@/api/types";
import { proposal } from "@/test/gateway-fixtures";
import { approval, orders } from "@/mocks/milk-case";

const confirmedOrder = {
  ...orders.needsApproval,
  lines: orders.needsApproval.lines.map((line) => ({
    ...line, offer: { ...line.offer, availableAmount: line.quantity },
  })),
};

describe("ApprovalCard", () => {
  it.each([false, true])("names suppliers that must confirm without changing Approve when stock is unconfirmed: %s", (unconfirmed) => {
    const order = structuredClone(confirmedOrder);
    if (unconfirmed) order.lines[0].offer.availableAmount = 999999;
    const withoutNotice = { ...approval, suppliersToConfirm: [] };
    const first = render(<ApprovalCard request={withoutNotice} order={order} />);
    const disabledWithoutNotice = (screen.getByRole("button", { name: /^Approve/ }) as HTMLButtonElement).disabled;
    first.unmount();

    render(
      <ApprovalCard
        request={{
          ...withoutNotice,
          suppliersToConfirm: [{ supplierId: "sup-bakery", name: "Leipomo Demo" }],
        }}
        order={order}
        approveUnconfirmedManual
      />,
    );
    const checks = screen.getByRole("heading", { name: "What to check" }).closest("section")!;
    expect(within(checks).getByText("Leipomo Demo must confirm stock. If you approve, the order is sent and waits for their confirmation: call or e-mail them.")).toBeVisible();
    expect((screen.getByRole("button", { name: /^Approve/ }) as HTMLButtonElement).disabled).toBe(disabledWithoutNotice);
  });

  it("does not promise to send unconfirmed stock when manual approval is off or unknown", () => {
    const request = {
      ...approval,
      suppliersToConfirm: [{ supplierId: "sup-bakery", name: "Leipomo Demo" }],
    };
    const first = render(<ApprovalCard request={request} order={confirmedOrder} approveUnconfirmedManual={false} />);
    expect(screen.getByText("Leipomo Demo must confirm stock before this order can be approved.")).toBeVisible();
    expect(screen.queryByText(/If you approve, the order is sent/)).toBeNull();
    first.unmount();

    render(<ApprovalCard request={request} order={confirmedOrder} />);
    expect(screen.getByText("Leipomo Demo must confirm stock before this order can be approved.")).toBeVisible();
  });

  it("shows the gateway's manual-supplier confirmation reason as sent under What to check", () => {
    const reason =
      "Töölö Bakery is a price list the kitchen entered: its stock is not known until the supplier confirms. You may approve it; the order then waits for the supplier's confirmation (call or e-mail them).";
    render(
      <ApprovalCard
        request={{ ...approval, reasons: [{ rule: reason, detail: "" }] }}
        order={orders.needsApproval}
      />,
    );

    const checks = screen.getByRole("heading", { name: "What to check" }).closest("section")!;
    expect(within(checks).getByText(reason)).toBeVisible();
  });

  it("searches addable products once the person stops typing", async () => {
    const user = userEvent.setup();
    const listAddableProducts = vi.fn().mockResolvedValue([]);
    render(
      <ApprovalCard
        request={approval}
        order={confirmedOrder}
        onChangeProposal={vi.fn()}
        listAddableProducts={listAddableProducts}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Show order lines" }));
    await waitFor(() => expect(listAddableProducts).toHaveBeenCalledTimes(1));
    listAddableProducts.mockClear();
    await user.type(screen.getByLabelText("Search products"), "Arla 1 L");
    expect(listAddableProducts).not.toHaveBeenCalled();
    await new Promise((resolve) => setTimeout(resolve, ADD_SEARCH_DEBOUNCE_MS * 2));
    expect(listAddableProducts).toHaveBeenCalledTimes(1);
    expect(listAddableProducts).toHaveBeenCalledWith("Arla 1 L");
  });

  it.each([999999, 9999999999, undefined, null])("blocks unknown stock %s with a visible reason", async (amount) => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const order = structuredClone(confirmedOrder);
    Object.assign(order.lines[0].offer, { availableAmount: amount });
    render(<ApprovalCard request={approval} order={order} onApprove={onApprove} />);
    expect(screen.getByText(/Waiting for supplier stock confirmation/)).toBeVisible();
    const approve = screen.getByRole("button", { name: /^Approve/ });
    expect(approve).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
    await user.click(approve);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("lists what to check and never says an order can go without approval", () => {
    render(<ApprovalCard request={approval} order={confirmedOrder} />);
    expect(screen.getByRole("heading", { name: "What to check" })).toBeVisible();
    expect(screen.getByText("3 % fat instead of 0 % in the first choice.")).toBeVisible();
    expect(screen.queryByText(/without approval/)).not.toBeInTheDocument();
  });

  it("shows missing allergen data under what to check", () => {
    const unknownAllergens = mapApproval({
      ...proposal,
      lines: [{ ...proposal.lines[0], reason_codes: ["ALLERGEN_DATA_MISSING"] }],
    });
    render(<ApprovalCard request={unknownAllergens} order={confirmedOrder} />);
    const check = screen.getByRole("heading", { name: "What to check" }).closest("section")!;
    expect(within(check).getByText("Allergen data missing")).toBeVisible();
    expect(
      within(check).getByText("The catalog has no allergen data for one or more products. Check the label."),
    ).toBeVisible();
  });

  it("blocks missing order details", () => {
    render(<ApprovalCard request={approval} />);
    expect(screen.getByText(/Order details are unavailable/)).toBeVisible();
    expect(screen.getByRole("button", { name: /^Approve/ })).toBeDisabled();
  });

  it("rechecks stock while the confirmation dialog is open", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const { rerender } = render(<ApprovalCard request={approval} order={confirmedOrder} onApprove={onApprove} />);
    await user.click(screen.getByRole("button", { name: /^Approve/ }));
    const order = structuredClone(confirmedOrder);
    order.lines[0].offer.availableAmount = 999999;
    rerender(<ApprovalCard request={approval} order={order} onApprove={onApprove} />);
    const yes = screen.getByRole("button", { name: /^Yes, approve/ });
    expect(yes).toBeDisabled();
    await user.click(yes);
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("shows Approved only after the gateway confirms", async () => {
    const user = userEvent.setup();
    let confirm!: () => void;
    const onApprove = vi.fn(() => new Promise<void>((resolve) => (confirm = resolve)));
    render(<ApprovalCard request={approval} order={confirmedOrder} onApprove={onApprove} />);

    await user.click(screen.getByRole("button", { name: /Approve €2,210\.41 incl VAT/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    const yes = within(dialog).getByRole("button", { name: "Yes, approve €2,210.41" });
    await user.click(yes);

    expect(onApprove).toHaveBeenCalledWith({
      approvalId: approval.id,
      approvalRef: approval.approvalRef,
      expectedTotalExVat: approval.totalExVat,
      expectedTotalInclVat: approval.totalInclVat,
    });
    expect(yes).toBeDisabled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    confirm();
    expect(await screen.findByRole("status")).toHaveTextContent("Approved: €1,947.50 ex VAT");
  });

  it("stays pending with an error when the gateway refuses the approval", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn(() => Promise.reject(new Error("expected_total mismatch")));
    render(<ApprovalCard request={approval} order={confirmedOrder} onApprove={onApprove} />);

    await user.click(screen.getByRole("button", { name: /Approve €2,210\.41 incl VAT/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €2,210.41" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Approval failed: expected_total mismatch");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve €2,210\.41 incl VAT/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
  });

  it("says a refused approval stays held when the gateway reports a recall", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn(() => Promise.reject(new ApiError("BLOCKED_BY_RECALL", "blocked by a recall")));
    render(<ApprovalCard request={approval} order={confirmedOrder} onApprove={onApprove} />);

    await user.click(screen.getByRole("button", { name: /Approve €2,210\.41 incl VAT/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €2,210.41" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Approval failed: This order is blocked by a recall. Reject it and approve the replacement order instead. The order stays held by the recall.",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent("The order is still pending");
  });

  it("stays pending with an error when the rejection fails", async () => {
    const user = userEvent.setup();
    const onReject = vi.fn(() => Promise.reject(new Error("network error")));
    render(<ApprovalCard request={approval} onReject={onReject} />);

    await user.click(screen.getByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("dialog", { name: "Reject this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Reject" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Rejection failed: network error");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
