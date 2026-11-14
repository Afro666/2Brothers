import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ADD_SEARCH_DEBOUNCE_MS, ApprovalCard, earliestCutoff } from "@/components/purchasing/approval-card";
import { mapApproval } from "@/api/gateway-map";
import { ApiError } from "@/api/types";
import { formatDate, formatDateTime, formatTime } from "@/lib/format";
import { proposal } from "@/test/gateway-fixtures";
import { approval, orders } from "@/mocks/milk-case";

const confirmedOrder = {
  ...orders.needsApproval,
  lines: orders.needsApproval.lines.map((line) => ({
    ...line, offer: { ...line.offer, availableAmount: line.quantity },
  })),
};

describe("earliestCutoff", () => {
  const at = (closingTime: string | null, supplierName = "Valio") => ({ closingTime, supplierName });

  it("does not warn when more than two hours remain", () => {
    expect(earliestCutoff([at("2026-11-15T17:00:00+02:00")], new Date("2026-11-15T14:00:00+02:00"))).toMatchObject({
      warning: false,
      passed: false,
      minutesLeft: 180,
    });
  });

  it("warns with whole hours and minutes left when less than two hours remain", () => {
    expect(earliestCutoff([at("2026-11-15T17:00:00+02:00")], new Date("2026-11-15T15:40:00+02:00"))).toMatchObject({
      warning: true,
      minutesLeft: 80,
    });
  });

  it("reports a cut-off at or before now as passed", () => {
    expect(earliestCutoff([at("2026-11-15T17:00:00+02:00")], new Date("2026-11-15T17:00:00+02:00"))).toMatchObject({
      warning: true,
      passed: true,
      minutesLeft: 0,
    });
  });

  it("shows no cut-off when every value is null", () => {
    expect(earliestCutoff([at(null), at(null)], new Date("2026-11-15T17:00:00+02:00"))).toBeNull();
  });

  it("does not warn at exactly two hours left", () => {
    expect(earliestCutoff([at("2026-11-15T17:00:00+02:00")], new Date("2026-11-15T15:00:00+02:00"))).toMatchObject({
      warning: false,
      minutesLeft: 120,
    });
  });

  it("chooses the earliest supplier cut-off and counts the known lines", () => {
    expect(earliestCutoff([
      at("2026-11-15T17:00:00+02:00"),
      at("2026-11-15T15:00:00+02:00", "Töölö Bakery"),
      at(null),
    ], new Date("2026-11-15T12:00:00+02:00"))).toMatchObject({
      closingTime: "2026-11-15T15:00:00+02:00",
      supplierName: "Töölö Bakery",
      earliestOf: 2,
    });
  });

  it("uses absolute timestamps and Helsinki formatting across the change to winter time", () => {
    const cutoff = earliestCutoff([at("2026-10-25T05:00:00+02:00")], new Date("2026-10-25T03:30:00+02:00"))!;
    expect(cutoff.minutesLeft).toBe(90);
    expect(`${formatDate(cutoff.closingTime)} ${formatTime(cutoff.closingTime)}`).toBe("Sun 25 Oct 05:00");
  });
});

describe("ApprovalCard", () => {
  it("shows the earliest supplier cut-off next to the totals while waiting", () => {
    render(<ApprovalCard
      request={{
        ...approval,
        cutoffs: [
          { closingTime: "2026-11-15T17:00:00+02:00", supplierName: "Valio" },
          { closingTime: "2026-11-15T16:00:00+02:00", supplierName: "Töölö Bakery" },
        ],
      }}
      order={confirmedOrder}
      now={new Date("2026-11-15T14:40:00+02:00")}
    />);
    expect(screen.getByText("Approve before Sun 15 Nov 16:00 · Töölö Bakery's cut-off (earliest of 2) · 1 h 20 min left")).toBeVisible();
  });

  it("says less than a minute, not 0 min, in the last minute before the cut-off", () => {
    render(<ApprovalCard
      request={{ ...approval, cutoffs: [{ closingTime: "2026-11-15T17:00:00+02:00", supplierName: "Valio" }] }}
      order={confirmedOrder}
      now={new Date("2026-11-15T16:59:30+02:00")}
    />);
    expect(screen.getByText("Approve before Sun 15 Nov 17:00 · Valio's cut-off · Less than 1 min left")).toBeVisible();
  });

  it("names no supplier when no supplier block names the line", () => {
    render(<ApprovalCard
      request={{ ...approval, cutoffs: [{ closingTime: "2026-11-15T17:00:00+02:00", supplierName: null }] }}
      order={confirmedOrder}
      now={new Date("2026-11-15T12:00:00+02:00")}
    />);
    expect(screen.getByText("Approve before Sun 15 Nov 17:00")).toBeVisible();
  });

  it("warns when the cut-off has passed and shows nothing when all cut-offs are null", () => {
    const passed = render(<ApprovalCard
      request={{ ...approval, cutoffs: [{ closingTime: "2026-11-15T17:00:00+02:00", supplierName: "Valio" }] }}
      order={confirmedOrder}
      now={new Date("2026-11-15T17:00:00+02:00")}
    />);
    expect(screen.getByText("The cut-off has passed · Valio's cut-off")).toHaveClass("hatch", "text-warning");
    expect(screen.getByRole("button", { name: "Approve €2,210.41 incl VAT" })).toBeEnabled();
    passed.unmount();

    render(<ApprovalCard
      request={{ ...approval, cutoffs: [{ closingTime: null, supplierName: "Valio" }] }}
      order={confirmedOrder}
    />);
    expect(screen.queryByText(/Approve before|cut-off has passed/)).not.toBeInTheDocument();
  });

  it("hides the cut-off on a decided card", () => {
    render(<ApprovalCard
      request={{
        ...approval,
        status: "APPROVED",
        cutoffs: [{ closingTime: "2026-11-15T17:00:00+02:00", supplierName: "Valio" }],
      }}
      order={confirmedOrder}
    />);
    expect(screen.queryByText(/Approve before|cut-off has passed/)).not.toBeInTheDocument();
  });

  it("refreshes the countdown once a minute and clears its timer", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-15T15:40:00+02:00"));
    const clearInterval = vi.spyOn(window, "clearInterval");
    try {
      const card = render(<ApprovalCard
        request={{ ...approval, cutoffs: [{ closingTime: "2026-11-15T17:00:00+02:00", supplierName: "Valio" }] }}
        order={confirmedOrder}
      />);
      expect(screen.getByText(/1 h 20 min left/)).toBeVisible();
      act(() => vi.advanceTimersByTime(60_000));
      expect(screen.getByText(/1 h 19 min left/)).toBeVisible();
      card.unmount();
      expect(clearInterval).toHaveBeenCalled();
    } finally {
      clearInterval.mockRestore();
      vi.useRealTimers();
    }
  });

  it("starts compact: title and total show, the details open on Inspect (#1142)", async () => {
    render(<ApprovalCard request={{ ...approval, status: "REJECTED" }} order={confirmedOrder} />);
    expect(screen.getByText(approval.summary)).toBeInTheDocument();
    expect(screen.queryByText("What to check")).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Inspect" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(screen.getByText("What to check")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inspect" })).toHaveAttribute("aria-expanded", "true");
  });

  it("shows the delivery fee below the totals and keeps the gateway's approve total", () => {
    const feeRequest = { ...approval, totalExVat: 33.1, totalInclVat: 62.74, inclVat: 37.74 };
    const feeOrder = {
      ...confirmedOrder,
      totalExVat: 33.1,
      totalInclVat: 62.74,
      inclVat: 37.74,
      deliveryFee: 25,
      mov: { threshold: 300, current: 33.1, deliveryFee: 25 },
    };
    render(<ApprovalCard request={feeRequest} order={feeOrder} onApprove={vi.fn()} />);

    expect(screen.getByText("€37.74")).toBeVisible();
    expect(screen.getByText("Delivery fee €25.00 (free from €300.00 ex VAT)")).toBeVisible();
    expect(screen.getByRole("button", { name: "Approve €62.74 incl VAT" })).toBeEnabled();
  });

  it("replaces empty order totals with the number of products left out", () => {
    const emptyRequest = {
      ...approval,
      status: "REJECTED" as const,
      lineCount: 0,
      totalExVat: 0,
      totalInclVat: 0,
      inclVat: 0,
      reasons: Array.from({ length: 35 }, (_, index) => ({ rule: `${10000 + index}: no stock`, detail: "" })),
    };
    const emptyOrder = { ...confirmedOrder, lines: [], totalExVat: 0, totalInclVat: 0, inclVat: 0, deliveryFee: 0 };
    render(<ApprovalCard request={emptyRequest} order={emptyOrder} />);

    expect(screen.getByText("Nothing could be ordered: 35 products left out")).toBeVisible();
    expect(screen.getByText("35 products left out")).toBeVisible();
    expect(screen.queryByText("€0.00")).not.toBeInTheDocument();
  });

  it("does not invent a left-out count for an empty order without reasons", () => {
    const emptyRequest = { ...approval, lineCount: 0, totalExVat: 0, totalInclVat: 0, reasons: [] };
    render(<ApprovalCard request={emptyRequest} order={{ ...confirmedOrder, lines: [] }} />);

    expect(screen.getByText("Nothing could be ordered")).toBeVisible();
    expect(screen.queryByText(/0 products left out/)).not.toBeInTheDocument();
    expect(screen.queryByText("€0.00")).not.toBeInTheDocument();
  });

  it("shows who asked and when when both are known", () => {
    render(<ApprovalCard request={approval} order={confirmedOrder} />);
    expect(screen.getByText(
      `1 line · delivery ${formatDate(approval.deliveryDate)} · asked by Head chef, ${formatDateTime(approval.createdAt)}`,
    )).toBeVisible();
  });

  it("omits the request time when only the requester is known", () => {
    render(<ApprovalCard request={{ ...approval, createdAt: null }} order={confirmedOrder} />);
    expect(screen.getByText(
      `1 line · delivery ${formatDate(approval.deliveryDate)} · asked by Head chef`,
    )).toBeVisible();
  });

  it("omits unknown requester and request time instead of naming unknowns", () => {
    render(<ApprovalCard request={{ ...approval, requestedBy: null, createdAt: null }} order={confirmedOrder} />);
    const description = screen.getByText(`1 line · delivery ${formatDate(approval.deliveryDate)}`);
    expect(description).toBeVisible();
    expect(description).not.toHaveTextContent("unknown");
  });

  it("shows a known request time without an unknown requester", () => {
    render(<ApprovalCard request={{ ...approval, requestedBy: null }} order={confirmedOrder} />);
    expect(screen.getByText(
      `1 line · delivery ${formatDate(approval.deliveryDate)} · ${formatDateTime(approval.createdAt)}`,
    )).toBeVisible();
  });

  it.each([false, true])("names suppliers that must confirm without changing Approve when stock is unconfirmed: %s", async (unconfirmed) => {
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
      />,
    );
    expect(screen.getByText("Leipomo Demo must confirm")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Inspect" }));
    const checks = screen.getByRole("heading", { name: "What to check" }).closest("section")!;
    expect(within(checks).getByText("Leipomo Demo must confirm stock. If you approve, the order is sent and waits for their confirmation: call or e-mail them.")).toBeVisible();
    expect((screen.getByRole("button", { name: /^Approve/ }) as HTMLButtonElement).disabled).toBe(disabledWithoutNotice);
  });

  it("says the order is sent and waits for the supplier, with no kitchen setting (Aron, 2026-11-14)", async () => {
    const request = {
      ...approval,
      suppliersToConfirm: [{ supplierId: "sup-bakery", name: "Leipomo Demo" }],
    };
    render(<ApprovalCard request={request} order={confirmedOrder} />);
    await userEvent.click(screen.getByRole("button", { name: "Inspect" }));
    expect(screen.getByText("Leipomo Demo must confirm stock. If you approve, the order is sent and waits for their confirmation: call or e-mail them.")).toBeVisible();
    expect(screen.queryByText(/before this order can be approved/)).toBeNull();
  });

  it("shows the gateway's manual-supplier confirmation reason as sent under What to check", async () => {
    const reason =
      "Töölö Bakery is a price list the kitchen entered: its stock is not known until the supplier confirms. You may approve it; the order then waits for the supplier's confirmation (call or e-mail them).";
    render(
      <ApprovalCard
        request={{ ...approval, reasons: [{ rule: reason, detail: "" }] }}
        order={orders.needsApproval}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Inspect" }));
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
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    // The addable list is asked for only once Add products is open.
    expect(listAddableProducts).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Add products" }));
    await waitFor(() => expect(listAddableProducts).toHaveBeenCalledTimes(1));
    listAddableProducts.mockClear();
    await user.type(screen.getByLabelText("Search products"), "Arla 1 L");
    expect(listAddableProducts).not.toHaveBeenCalled();
    await new Promise((resolve) => setTimeout(resolve, ADD_SEARCH_DEBOUNCE_MS * 2));
    expect(listAddableProducts).toHaveBeenCalledTimes(1);
    expect(listAddableProducts).toHaveBeenCalledWith("Arla 1 L");
  });

  it.each([999999, 9999999999, undefined, null])("lets a person approve unknown stock %s and says the order waits", async (amount) => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const order = structuredClone(confirmedOrder);
    Object.assign(order.lines[0].offer, { availableAmount: amount });
    render(<ApprovalCard request={approval} order={order} onApprove={onApprove} />);
    // Compact: a chip says who must confirm; the full sentence is in Inspect and in the confirmation.
    expect(screen.getByText("Valio must confirm 1")).toBeVisible();
    expect(screen.queryByText(/approval is available once stock is confirmed/)).toBeNull();
    const approve = screen.getByRole("button", { name: /^Approve/ });
    expect(approve).toBeEnabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
    await user.click(approve);
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    expect(within(dialog).getByText("Some lines wait for the supplier's stock confirmation. You can still approve: the order is sent and marked as waiting for the supplier.")).toBeVisible();
    await user.click(within(dialog).getByRole("button", { name: /^Yes, approve/ }));
    expect(onApprove).toHaveBeenCalledTimes(1);
  });

  it("still holds approval when the order lines are unavailable", () => {
    render(<ApprovalCard request={approval} order={{ ...confirmedOrder, lines: [] }} />);
    const reason = "Order details are unavailable. Reload them before approving.";
    expect(screen.getByText(reason)).toBeVisible();
    const button = screen.getByRole("button", { name: "Approve" });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(reason);
  });

  it("lists what to check and never says an order can go without approval", async () => {
    render(<ApprovalCard request={approval} order={confirmedOrder} />);
    await userEvent.click(screen.getByRole("button", { name: "Inspect" }));
    expect(screen.getByRole("heading", { name: "What to check" })).toBeVisible();
    expect(screen.getByText("3 % fat instead of 0 % in the first choice.")).toBeVisible();
    expect(screen.queryByText(/without approval/)).not.toBeInTheDocument();
  });

  it("shows missing allergen data under what to check", async () => {
    const unknownAllergens = mapApproval({
      ...proposal,
      lines: [{ ...proposal.lines[0], reason_codes: ["ALLERGEN_DATA_MISSING"] }],
    });
    render(<ApprovalCard request={unknownAllergens} order={confirmedOrder} />);
    // Short at the top of the compact card, in full under Inspect.
    expect(screen.getByText("Allergen data missing", { selector: "li" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Inspect" }));
    const check = screen.getByRole("heading", { name: "What to check" }).closest("section")!;
    expect(within(check).getByText("Allergen data missing")).toBeVisible();
    expect(
      within(check).getByText("The catalog has no allergen data for one or more products. Check the label."),
    ).toBeVisible();
  });

  it("blocks missing order details", () => {
    render(<ApprovalCard request={approval} />);
    expect(screen.getByText(/Order details are unavailable/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
  });

  it("keeps an enabled total but omits it from a button disabled for a stated reason", () => {
    const reason = "Your account cannot approve or reject orders.";
    const { rerender } = render(<ApprovalCard request={approval} order={confirmedOrder} />);
    expect(screen.getByRole("button", { name: "Approve €2,210.41 incl VAT" })).toBeEnabled();
    rerender(<ApprovalCard request={approval} order={confirmedOrder} approvalBlockedReason={reason} />);
    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve).toBeDisabled();
    expect(approve).toHaveAccessibleDescription(reason);
    expect(screen.getByText("€2,210.41", { selector: "dd" })).toBeVisible();
  });

  it("rechecks the order while the confirmation dialog is open", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const { rerender } = render(<ApprovalCard request={approval} order={confirmedOrder} onApprove={onApprove} />);
    await user.click(screen.getByRole("button", { name: /^Approve/ }));
    // Stock that turns unconfirmed does not hold the yes (Aron, 2026-11-14): it only says so.
    const unknown = structuredClone(confirmedOrder);
    unknown.lines[0].offer.availableAmount = 999999;
    rerender(<ApprovalCard request={approval} order={unknown} onApprove={onApprove} />);
    expect(screen.getByRole("button", { name: /^Yes, approve/ })).toBeEnabled();
    expect(screen.getByText(/wait for the supplier's stock confirmation/)).toBeInTheDocument();
    // Lines that can no longer be shown do hold it.
    rerender(<ApprovalCard request={approval} order={{ ...confirmedOrder, lines: [] }} onApprove={onApprove} />);
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
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Approved and recorded: €1,947.50 ex VAT, €2,210.41 incl VAT. Nothing is sent to the supplier.",
    );
    expect(screen.queryByText(/The order may now be sent/)).not.toBeInTheDocument();
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

  it("shows a quantity suggestion without selecting or sending it", async () => {
    const user = userEvent.setup();
    const onChangeProposal = vi.fn().mockResolvedValue(undefined);
    const line = confirmedOrder.lines[0];
    render(
      <ApprovalCard
        request={approval}
        order={confirmedOrder}
        onChangeProposal={onChangeProposal}
        listAddableProducts={vi.fn().mockResolvedValue([])}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    const quantity = screen.getAllByRole("spinbutton", { name: /^Quantity for / })[0];
    await user.clear(quantity);
    await user.type(quantity, String(line.quantity - 1));

    const group = screen.getByRole("group", { name: `Reason for changing ${line.product.names.en}` });
    const suggestion = within(group).getByRole("button", { name: "Too much · suggested" });
    expect(suggestion).toHaveAttribute("aria-pressed", "false");
    expect(suggestion).toHaveClass("border-dashed", "min-h-11");
    expect(group).toHaveClass("flex-wrap");
    for (const chip of within(group).getAllByRole("button")) expect(chip).toHaveClass("min-h-11");

    await user.click(screen.getByRole("button", { name: `Update ${line.product.names.en}` }));
    expect(onChangeProposal).toHaveBeenCalledWith({
      type: "SET_QUANTITY",
      productId: line.product.id,
      quantity: line.quantity - 1,
    });
    await waitFor(() => expect(screen.queryByRole("group", { name: `Reason for changing ${line.product.names.en}` })).toBeNull());
  });

  it("sends a tapped suggestion and resets the chips after a successful quantity change", async () => {
    const user = userEvent.setup();
    const onChangeProposal = vi.fn().mockResolvedValue(undefined);
    const line = confirmedOrder.lines[0];
    render(
      <ApprovalCard
        request={approval}
        order={confirmedOrder}
        onChangeProposal={onChangeProposal}
        listAddableProducts={vi.fn().mockResolvedValue([])}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    const quantity = screen.getAllByRole("spinbutton", { name: /^Quantity for / })[0];
    await user.clear(quantity);
    await user.type(quantity, String(line.quantity - 10));
    const group = screen.getByRole("group", { name: `Reason for changing ${line.product.names.en}` });
    const suggestion = within(group).getByRole("button", { name: "Too much · suggested" });

    await user.click(suggestion);
    expect(suggestion).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: `Update ${line.product.names.en}` }));

    expect(onChangeProposal).toHaveBeenCalledWith({
      type: "SET_QUANTITY",
      productId: line.product.id,
      quantity: line.quantity - 10,
      reason: "TOO_MUCH",
    });
    await waitFor(() => expect(screen.queryByRole("group", { name: `Reason for changing ${line.product.names.en}` })).toBeNull());
  });

  it("sends Other with its note and enforces the 200 character limit", async () => {
    const user = userEvent.setup();
    const onChangeProposal = vi.fn().mockResolvedValue(undefined);
    const line = confirmedOrder.lines[0];
    render(
      <ApprovalCard
        request={approval}
        order={confirmedOrder}
        onChangeProposal={onChangeProposal}
        listAddableProducts={vi.fn().mockResolvedValue([])}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    const quantity = screen.getAllByRole("spinbutton", { name: /^Quantity for / })[0];
    await user.clear(quantity);
    await user.type(quantity, String(line.quantity + 1));
    const group = screen.getByRole("group", { name: `Reason for changing ${line.product.names.en}` });
    expect(within(group).getByRole("button", { name: "Too little · suggested" })).toHaveAttribute("aria-pressed", "false");
    await user.click(within(group).getByRole("button", { name: "Other" }));
    const note = screen.getByRole("textbox", { name: "Note (optional)" });
    expect(note).toHaveAttribute("maxLength", "200");
    expect(screen.getByText("0/200 characters")).toBeVisible();
    await user.type(note, "Event cancelled");
    expect(screen.getByText("15/200 characters")).toBeVisible();

    await user.click(screen.getByRole("button", { name: `Update ${line.product.names.en}` }));
    expect(onChangeProposal).toHaveBeenCalledWith({
      type: "SET_QUANTITY",
      productId: line.product.id,
      quantity: line.quantity + 1,
      reason: "OTHER",
      note: "Event cancelled",
    });
  });

  it("keeps a tapped chip and its note while the person corrects the quantity", async () => {
    const user = userEvent.setup();
    const onChangeProposal = vi.fn().mockResolvedValue(undefined);
    const line = confirmedOrder.lines[0];
    render(
      <ApprovalCard
        request={approval}
        order={confirmedOrder}
        onChangeProposal={onChangeProposal}
        listAddableProducts={vi.fn().mockResolvedValue([])}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    const quantity = screen.getAllByRole("spinbutton", { name: /^Quantity for / })[0];
    await user.clear(quantity);
    await user.type(quantity, String(line.quantity + 1));
    await user.click(screen.getByRole("button", { name: "Other" }));
    await user.type(screen.getByRole("textbox", { name: "Note (optional)" }), "Party");
    await user.type(quantity, "0");

    expect(screen.getByRole("button", { name: "Other" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("textbox", { name: "Note (optional)" })).toHaveValue("Party");
    await user.click(screen.getByRole("button", { name: `Update ${line.product.names.en}` }));
    expect(onChangeProposal).toHaveBeenCalledWith({
      type: "SET_QUANTITY",
      productId: line.product.id,
      quantity: Number(`${line.quantity + 1}0`),
      reason: "OTHER",
      note: "Party",
    });
  });

  it("never sends a note after the person switches away from Other", async () => {
    const user = userEvent.setup();
    const onChangeProposal = vi.fn().mockResolvedValue(undefined);
    const line = confirmedOrder.lines[0];
    render(
      <ApprovalCard
        request={approval}
        order={confirmedOrder}
        onChangeProposal={onChangeProposal}
        listAddableProducts={vi.fn().mockResolvedValue([])}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    const quantity = screen.getAllByRole("spinbutton", { name: /^Quantity for / })[0];
    await user.clear(quantity);
    await user.type(quantity, String(line.quantity + 1));
    const group = screen.getByRole("group", { name: `Reason for changing ${line.product.names.en}` });
    await user.click(within(group).getByRole("button", { name: "Other" }));
    await user.type(screen.getByRole("textbox", { name: "Note (optional)" }), "Do not send this");
    await user.click(within(group).getByRole("button", { name: "Budget" }));
    expect(within(group).getByRole("button", { name: "Other" })).toHaveAttribute("aria-pressed", "false");
    expect(within(group).getByRole("button", { name: "Budget" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: `Update ${line.product.names.en}` }));
    expect(onChangeProposal).toHaveBeenCalledWith({
      type: "SET_QUANTITY",
      productId: line.product.id,
      quantity: line.quantity + 1,
      reason: "BUDGET",
    });
  });

  it.each([["without", undefined], ["with", "IN_STOCK"]] as const)("removes a line %s a tapped reason", async (_word, reason) => {
    const user = userEvent.setup();
    const onChangeProposal = vi.fn().mockResolvedValue(undefined);
    const line = confirmedOrder.lines[0];
    render(
      <ApprovalCard
        request={approval}
        order={confirmedOrder}
        onChangeProposal={onChangeProposal}
        listAddableProducts={vi.fn().mockResolvedValue([])}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    await user.click(screen.getByRole("button", { name: `Remove ${line.product.names.en}` }));
    const group = screen.getByRole("group", { name: `Reason for changing ${line.product.names.en}` });
    expect(within(group).getByRole("button", { name: "Too much · suggested" })).toHaveAttribute("aria-pressed", "false");
    if (reason) await user.click(within(group).getByRole("button", { name: "Still in stock" }));

    await user.click(screen.getByRole("button", { name: `Remove line: ${line.product.names.en}` }));
    expect(onChangeProposal).toHaveBeenCalledWith({
      type: "REMOVE_LINE",
      productId: line.product.id,
      ...(reason ? { reason } : {}),
    });
  });

  it("keeps a line and clears a selected chip when it is toggled off", async () => {
    const user = userEvent.setup();
    const onChangeProposal = vi.fn().mockResolvedValue(undefined);
    const line = confirmedOrder.lines[0];
    render(
      <ApprovalCard
        request={approval}
        order={confirmedOrder}
        onChangeProposal={onChangeProposal}
        listAddableProducts={vi.fn().mockResolvedValue([])}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    await user.click(screen.getByRole("button", { name: `Remove ${line.product.names.en}` }));
    const group = screen.getByRole("group", { name: `Reason for changing ${line.product.names.en}` });
    const chip = within(group).getByRole("button", { name: "Too much · suggested" });
    await user.click(chip);
    await user.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: `Keep line: ${line.product.names.en}` }));
    expect(onChangeProposal).not.toHaveBeenCalled();
    expect(screen.queryByRole("group", { name: `Reason for changing ${line.product.names.en}` })).toBeNull();
  });

  it("keeps focus on Remove while its confirm is open and names each line's confirm", async () => {
    const user = userEvent.setup();
    const [first] = confirmedOrder.lines;
    const second = { ...first, product: { ...first.product, id: "999999", names: { ...first.product.names, en: "Cream 2 L" } } };
    render(
      <ApprovalCard
        request={approval}
        order={{ ...confirmedOrder, lines: [first, second] }}
        onChangeProposal={vi.fn().mockResolvedValue(undefined)}
        listAddableProducts={vi.fn().mockResolvedValue([])}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    const remove = screen.getByRole("button", { name: `Remove ${first.product.names.en}` });
    expect(remove).toHaveAttribute("aria-expanded", "false");
    await user.click(remove);
    expect(remove).toHaveFocus();
    expect(remove).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByRole("button", { name: `Remove ${second.product.names.en}` }));
    expect(screen.getByRole("button", { name: `Remove line: ${first.product.names.en}` })).toBeVisible();
    expect(screen.getByRole("button", { name: `Remove line: ${second.product.names.en}` })).toBeVisible();

    await user.click(screen.getByRole("button", { name: `Keep line: ${first.product.names.en}` }));
    expect(remove).toHaveFocus();
    expect(remove).toHaveAttribute("aria-expanded", "false");
  });

  it.each([
    ["NOT_PENDING", "This proposal is no longer waiting for approval."],
    ["LINE_NOT_FOUND", "That product is not on this proposal."],
    ["NOT_ADDABLE", "That product cannot be added to this proposal."],
    ["CLOSING_PASSED", "The order cut-off for this line has passed."],
    ["LINE_UNAVAILABLE", "This product cannot be ordered now."],
    ["EMPTY_PROPOSAL", "Every line would be removed: reject the proposal instead."],
    ["PROPOSAL_NOT_FOUND", "This proposal could not be found in this kitchen."],
    ["ROLE_REQUIRED", "Your role cannot change proposals."],
  ])("explains a refused %s change next to the controls without changing the basket", async (code, message) => {
    const user = userEvent.setup();
    const onChangeProposal = vi.fn().mockRejectedValue(new ApiError(code, code));
    render(
      <ApprovalCard
        request={approval}
        order={confirmedOrder}
        onChangeProposal={onChangeProposal}
        listAddableProducts={vi.fn().mockResolvedValue([])}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    const quantity = screen.getAllByRole("spinbutton", { name: /^Quantity for / })[0];
    const originalQuantity = (quantity as HTMLInputElement).valueAsNumber;

    await user.click(screen.getAllByRole("button", { name: /^Remove / })[0]);
    await user.click(screen.getByRole("button", { name: `Remove line: ${confirmedOrder.lines[0].product.names.en}` }));

    const orderSection = screen.getByRole("region", { name: "Order lines" });
    expect(await within(orderSection).findByRole("alert")).toHaveTextContent(message);
    expect(within(orderSection).getByRole("alert")).toHaveTextContent("The proposal is unchanged.");
    expect(quantity).toHaveValue(originalQuantity);
  });
});
