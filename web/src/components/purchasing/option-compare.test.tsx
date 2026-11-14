import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { ApprovalCard } from "@/components/purchasing/approval-card";
import { OptionCompare } from "@/components/purchasing/option-compare";
import { confirmedDemoApproval, confirmedDemoOrder, milkOptions } from "@/mocks/milk-case";
import { renderApp } from "@/test/render";
import type { ProposalOption } from "@/types";

const [optionA, optionB, optionC] = milkOptions;

function row(letter: string) {
  return screen.getByRole("heading", { name: new RegExp(`^Option ${letter}:`) }).closest("li") as HTMLElement;
}

function fact(letter: string, label: string) {
  return within(row(letter)).getByText(label).nextElementSibling as HTMLElement;
}

/** Option A with confirmed stock: a basket a person may choose that the proposal does not hold yet. */
const choosable: ProposalOption = { ...optionA, stockConfirmed: true };

describe("OptionCompare", () => {
  it("shows unknown values as unknown, never as zero and never as recommended", () => {
    const unknown: ProposalOption = {
      ...optionA,
      lines: [{ ...optionA.lines[0], unitPrice: null }],
      cutoffPassed: null,
      cutoffAt: null,
      deliveryReliability: null,
      co2KgPerKg: null,
      labels: null,
      recommended: true,
    };
    render(<OptionCompare options={[unknown]} onChoose={vi.fn()} onApprove={vi.fn()} />);
    for (const label of [
      "Price ex VAT",
      "Stock",
      "Order cut-off",
      "Delivery reliability",
      "CO2 (product-group average)",
      "Labels",
    ]) {
      expect(fact("A", label)).toHaveTextContent(/^unknown$/);
    }
    expect(screen.queryByText("Recommended by the Buyer")).toBeNull();
    expect(within(row("A")).queryByRole("button")).toBeNull();
    expect(within(row("A")).getByText(/Cannot be approved now: Stock is not confirmed/)).toBeVisible();
  });

  it("shows a missed cut-off with its time and offers no approval for it", () => {
    render(<OptionCompare options={milkOptions} onChoose={vi.fn()} onApprove={vi.fn()} />);
    expect(fact("B", "Order cut-off")).toHaveTextContent(/^missed \(closed Thu,? 12 Nov,? 15:00\)$/);
    expect(fact("B", "Stock")).toHaveTextContent("confirmed");
    expect(within(row("B")).getByText(/Cannot be approved now: The order cut-off has passed/)).toBeVisible();
    expect(within(row("B")).queryByRole("button")).toBeNull();
  });

  it("shows the milk story: price, total, labels, the engine's sentence and the API's recommendation", () => {
    render(<OptionCompare options={milkOptions} onChoose={vi.fn()} onApprove={vi.fn()} />);
    expect(fact("A", "Price ex VAT")).toHaveTextContent("€2.05 per L");
    expect(fact("A", "Total")).toHaveTextContent("€2,326.75 incl VAT");
    expect(fact("A", "Delivery reliability")).toHaveTextContent("unknown");
    expect(fact("B", "Labels")).toHaveTextContent("Organic (EU)");
    expect(fact("C", "Order cut-off")).toHaveTextContent(/^met \(order by Sun,? 15 Nov,? 17:00\)$/);
    expect(fact("C", "CO2 (product-group average)")).toHaveTextContent("1.3 kg CO2e/kg");
    expect(within(row("C")).getByText(optionC.tradeOff)).toBeVisible();
    expect(within(row("C")).getByText("Part now, the rest later")).toBeVisible();
    expect(within(row("C")).getByText("Recommended by the Buyer")).toBeVisible();
    expect(within(row("A")).queryByText("Recommended by the Buyer")).toBeNull();
    expect(within(row("B")).getByText(optionB.tradeOff)).toBeVisible();
  });

  it("opens the existing approval for the proposed basket without choosing again", async () => {
    const user = userEvent.setup();
    const onChoose = vi.fn();
    const onApprove = vi.fn();
    render(<OptionCompare options={milkOptions} onChoose={onChoose} onApprove={onApprove} />);
    await user.click(screen.getByRole("button", { name: "Choose option C: approve €148.76 incl VAT" }));
    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(onChoose).not.toHaveBeenCalled();
  });

  it("chooses another option first and opens the approval only once that basket is the proposal", async () => {
    const user = userEvent.setup();
    const onChoose = vi.fn(() => Promise.resolve());
    const onApprove = vi.fn();
    const { rerender } = render(
      <OptionCompare options={[choosable, optionC]} onChoose={onChoose} onApprove={onApprove} />,
    );
    await user.click(screen.getByRole("button", { name: "Choose option A: approve €2,326.75 incl VAT" }));
    expect(onChoose).toHaveBeenCalledWith(choosable.id);
    expect(onApprove).not.toHaveBeenCalled();

    rerender(
      <OptionCompare
        options={[
          { ...choosable, chosen: true },
          { ...optionC, chosen: false },
        ]}
        onChoose={onChoose}
        onApprove={onApprove}
      />,
    );
    await waitFor(() => expect(onApprove).toHaveBeenCalledTimes(1));
  });

  it("does not open the approval when the chosen basket comes back with unconfirmed stock", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const { rerender } = render(
      <OptionCompare options={[choosable]} onChoose={() => Promise.resolve()} onApprove={onApprove} />,
    );
    await user.click(screen.getByRole("button", { name: /^Choose option A/ }));
    rerender(<OptionCompare options={[{ ...optionA, chosen: true }]} onChoose={vi.fn()} onApprove={onApprove} />);
    expect(await screen.findByText(/Cannot be approved now: Stock is not confirmed/)).toBeVisible();
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("frees the buttons again when the new options do not hold the chosen basket", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const { rerender } = render(
      <OptionCompare options={[choosable]} onChoose={() => Promise.resolve()} onApprove={onApprove} />,
    );
    await user.click(screen.getByRole("button", { name: /^Choose option A/ }));
    expect(screen.getByRole("button", { name: /^Choose option A/ })).toBeDisabled();
    rerender(<OptionCompare options={[{ ...choosable }]} onChoose={vi.fn()} onApprove={onApprove} />);
    await waitFor(() => expect(screen.getByRole("button", { name: /^Choose option A/ })).toBeEnabled());
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("says so when choosing fails, and approves nothing", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    render(
      <OptionCompare
        options={[choosable]}
        onChoose={() => Promise.reject(new Error("The gateway does not serve this yet."))}
        onApprove={onApprove}
      />,
    );
    await user.click(screen.getByRole("button", { name: /^Choose option A/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not choose this option: The gateway does not serve this yet.. Nothing was changed or approved.",
    );
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("offers no way to switch baskets when the API cannot", () => {
    render(<OptionCompare options={[choosable, optionC]} onApprove={vi.fn()} />);
    expect(within(row("A")).queryByRole("button")).toBeNull();
    expect(within(row("B")).getByRole("button", { name: /^Choose option B/ })).toBeEnabled();
  });
});

describe("ApprovalCard with options", () => {
  const request = { ...confirmedDemoApproval, options: [choosable, optionC] };

  it("chooses an option, then approves the re-simulated total through the existing dialog", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const onChooseOption = vi.fn(() => Promise.resolve());
    const { rerender } = render(
      <ApprovalCard
        request={request}
        order={confirmedDemoOrder}
        onApprove={onApprove}
        onChooseOption={onChooseOption}
      />,
    );
    await user.click(screen.getByRole("button", { name: /^Choose option A/ }));
    expect(onChooseOption).toHaveBeenCalledWith(choosable.id);
    expect(screen.queryByRole("dialog")).toBeNull();

    const chosen = {
      ...request,
      totalExVat: 2050,
      totalInclVat: 2326.75,
      options: [
        { ...choosable, chosen: true },
        { ...optionC, chosen: false },
      ],
    };
    rerender(
      <ApprovalCard
        request={chosen}
        order={confirmedDemoOrder}
        onApprove={onApprove}
        onChooseOption={onChooseOption}
      />,
    );
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    expect(onApprove).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €2,326.75" }));
    expect(onApprove).toHaveBeenCalledWith({
      approvalId: request.id,
      expectedTotalExVat: 2050,
      expectedTotalInclVat: 2326.75,
    });
  });

  it("keeps approval blocked while the order's stock is unconfirmed, whatever the option says", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn();
    const order = structuredClone(confirmedDemoOrder);
    order.lines[0].offer.availableAmount = 999999;
    render(<ApprovalCard request={request} order={order} onApprove={onApprove} />);
    await user.click(screen.getByRole("button", { name: /^Choose option B/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    const yes = within(dialog).getByRole("button", { name: /^Yes, approve/ });
    expect(yes).toBeDisabled();
    await user.click(yes);
    expect(onApprove).not.toHaveBeenCalled();
  });
});

describe("Approvals page: the milk options", () => {
  it("shows three options and approves the chosen one through the Api", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const approve = vi.spyOn(api, "approve");
    renderApp("/approvals", api);

    expect(await screen.findByRole("heading", { name: /^Option A: 1,000 L Valio Eila 3 %/ })).toBeVisible();
    expect(fact("A", "Stock")).toHaveTextContent(/^unknown$/);
    expect(within(row("A")).queryByRole("button")).toBeNull();
    expect(fact("B", "Order cut-off")).toHaveTextContent(/^missed/);
    expect(within(row("B")).queryByRole("button")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Choose option C: approve €148.76 incl VAT" }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    expect(approve).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €148.76" }));

    await waitFor(() =>
      expect(approve).toHaveBeenCalledWith(
        { approvalId: confirmedDemoApproval.id, expectedTotalExVat: 131.07, expectedTotalInclVat: 148.76 },
        "human",
      ),
    );
    expect(await screen.findByRole("heading", { name: "Decided" })).toBeVisible();
    expect((await api.getOrder(confirmedDemoOrder.id)).status).toBe("PLACED");
  });
});
