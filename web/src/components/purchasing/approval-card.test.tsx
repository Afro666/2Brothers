import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApprovalCard } from "@/components/purchasing/approval-card";
import { approval } from "@/mocks/milk-case";

describe("ApprovalCard", () => {
  it("shows Approved only after the gateway confirms", async () => {
    const user = userEvent.setup();
    let confirm!: () => void;
    const onApprove = vi.fn(() => new Promise<void>((resolve) => (confirm = resolve)));
    render(<ApprovalCard request={approval} onApprove={onApprove} />);

    await user.click(screen.getByRole("button", { name: /Approve €2,210\.41 incl VAT/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    const yes = within(dialog).getByRole("button", { name: "Yes, approve €2,210.41" });
    await user.click(yes);

    expect(onApprove).toHaveBeenCalledWith({
      approvalId: approval.id,
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
    render(<ApprovalCard request={approval} onApprove={onApprove} />);

    await user.click(screen.getByRole("button", { name: /Approve €2,210\.41 incl VAT/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €2,210.41" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Approval failed: expected_total mismatch");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve €2,210\.41 incl VAT/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
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
