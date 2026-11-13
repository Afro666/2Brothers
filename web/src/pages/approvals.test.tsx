import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

function withConfirmedStock() {
  const api = createMockApi();
  const getOrder = api.getOrder;
  api.getOrder = async (id) => {
    const order = structuredClone(await getOrder(id));
    order.lines.forEach((line) => { line.offer.availableAmount = line.quantity; });
    return order;
  };
  return api;
}

describe("ApprovalsPage", () => {
  it("keeps the milk proposal visible while awaiting stock confirmation", async () => {
    renderApp("/approvals", createMockApi());
    expect(await screen.findByRole("heading", { name: "Waiting for you (1)" })).toBeVisible();
    expect(await screen.findByText(/Waiting for supplier stock confirmation/)).toBeVisible();
    expect(screen.getByRole("button", { name: /^Approve/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
  });
  beforeEach(() => localStorage.clear());

  it("shows the pending approval and its total, then reloads it under Decided", async () => {
    const user = userEvent.setup();
    const api = withConfirmedStock();
    renderApp("/approvals", api);

    expect(await screen.findByRole("heading", { name: "Waiting for you (1)" })).toBeInTheDocument();
    expect(screen.getByText("€2,210.41")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Approve €2,210\.41 incl VAT/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €2,210.41" }));

    expect(await screen.findByRole("heading", { name: "Decided" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Waiting for you (0)" })).toBeInTheDocument();
    await waitFor(async () => {
      const events = await api.listAudit();
      expect(events.filter((event) => event.kind === "approval").at(-1)).toMatchObject({
        actor: "human",
        orderId: "ORD-1043",
        summary: "Approved ORD-1043",
      });
    });
  });

  it("keeps the approval waiting and shows the gateway error", async () => {
    const user = userEvent.setup();
    const api = withConfirmedStock();
    api.failNextApprove("TOTAL_MISMATCH", "The total moved.");
    renderApp("/approvals", api);

    await user.click(await screen.findByRole("button", { name: /Approve €2,210\.41 incl VAT/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €2,210.41" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The total moved.");
    expect(screen.getByRole("heading", { name: "Waiting for you (1)" })).toBeInTheDocument();
  });

  it("records a rejection reason in the audit log", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/approvals", api);

    await user.click(await screen.findByRole("button", { name: "Reject" }));
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

    const button = await screen.findByRole("button", { name: "Show order lines" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.click(button);

    expect(screen.getByRole("button", { name: "Hide order lines" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByText("Valio Eila 3 % lactose free milk drink 1 L").length).toBeGreaterThan(0);
  });
});
