import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api";
import { mapReceipt } from "@/api/gateway-map";
import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("orders pages", () => {
  beforeEach(() => localStorage.clear());

  it("links from the order list to its detail and shows lines and filtered history", async () => {
    const user = userEvent.setup();
    renderApp("/orders");

    await user.click(await screen.findByRole("link", { name: /ORD-1042/ }));
    expect(await screen.findByRole("heading", { level: 1, name: "Order ORD-1042" })).toBeInTheDocument();
    expect(screen.getAllByText("Arla 1 L lactose free fat free UHT milk drink").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("tab", { name: "History" }));
    expect(await screen.findByText("ORD-1042 placed for Mon 16 Nov")).toBeInTheDocument();
    expect(screen.queryByText("Asked the buyer to approve ORD-1043")).not.toBeInTheDocument();
  });

  it("shows the signed receipt of a placed order and copies the JWS", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const { receipt } = await api.getOrder("ORD-1042");
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    renderApp("/orders/ORD-1042", api);

    const block = (await screen.findByRole("heading", { name: "Signed receipt" })).closest("section")!;
    expect(within(block).getByText("Signed by the gateway. Anyone can check it with the public key.")).toBeVisible();
    expect(within(block).getByText("Approved by").nextElementSibling).toHaveTextContent("aron");
    expect(within(block).getByText("Signed total").nextElementSibling).toHaveTextContent("148.76");
    expect(within(block).getByText("Signed at").nextElementSibling).not.toHaveTextContent("unknown");

    await user.click(within(block).getByRole("button", { name: "Copy receipt" }));
    expect(writeText).toHaveBeenCalledWith(receipt!.jws);
    // The sample is shaped like the gateway's: the real mapper reads the same claims back.
    expect(mapReceipt(receipt!.jws)).toEqual(receipt);
  });

  it("says when a placed order has no signed receipt", async () => {
    renderApp("/orders/ORD-1046");

    const block = (await screen.findByRole("heading", { name: "Signed receipt" })).closest("section")!;
    expect(within(block).getByText("No signed receipt (this order is from before receipts, or signing was not possible)")).toBeVisible();
    expect(within(block).queryByRole("button", { name: "Copy receipt" })).not.toBeInTheDocument();
  });

  it("shows the API error for an unknown id", async () => {
    const api = createMockApi();
    const message = "Order ORD-missing was not found.";
    api.getOrder = async () => {
      throw new ApiError("NOT_FOUND", message);
    };
    renderApp("/orders/ORD-missing", api);

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("heading", { level: 1, name: "Order ORD-missing" })).toBeInTheDocument();
  });

  it("shows what is known and resolves a placed order only with its supplier reference", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    await api.signIn("buyer@demo.kitchen", "demo-kitchen-2026");
    const resolve = vi.spyOn(api, "resolveOrder");
    renderApp("/orders/ORD-1046", api);

    expect(await screen.findByRole("heading", { name: "Check this order with the supplier" })).toBeVisible();
    expect(screen.getByText("The app cannot ask the supplier whether this order arrived. Check by phone, e-mail or the supplier's portal, then record what happened. Neither choice resends the order.")).toBeVisible();
    expect(await screen.findByText("approve-unknown-1046")).toBeVisible();
    expect(screen.getByText("Supplier status").nextElementSibling).toHaveTextContent("unknown");
    expect(screen.getByRole("button", { name: "It was placed" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "It was not sent" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "It was placed" }));
    const dialog = await screen.findByRole("dialog", { name: "Confirm it was placed" });
    const reference = within(dialog).getByLabelText("Supplier order reference");
    await user.type(reference, "   ");
    await user.click(within(dialog).getByRole("button", { name: "Confirm placed" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("1 to 200 characters");
    expect(resolve).not.toHaveBeenCalled();

    await user.clear(reference);
    await user.type(reference, "VAL-2026-00123");
    await user.click(within(dialog).getByRole("button", { name: "Confirm placed" }));
    expect(resolve).toHaveBeenCalledWith(
      "ORD-1046",
      { resolution: "placed", supplierOrderRef: "VAL-2026-00123" },
      "Buyer",
    );
    expect(await screen.findByText("VAL-2026-00123")).toBeVisible();
    expect(await screen.findByText("Placed", { selector: "[data-status='PLACED']" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "It was placed" })).not.toBeInTheDocument();
  });

  it("records not_sent with a note and returns the proposal to the approval inbox", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    await api.signIn("buyer@demo.kitchen", "demo-kitchen-2026");
    const resolve = vi.spyOn(api, "resolveOrder");
    renderApp("/orders/ORD-1046", api);

    await user.click(await screen.findByRole("button", { name: "It was not sent" }));
    const dialog = await screen.findByRole("dialog", { name: "Confirm it was not sent" });
    await user.type(within(dialog).getByLabelText("Note (optional)"), "Valio sales desk: no such order");
    await user.click(within(dialog).getByRole("button", { name: "Confirm not sent" }));

    expect(resolve).toHaveBeenCalledWith(
      "ORD-1046",
      { resolution: "not_sent", note: "Valio sales desk: no such order" },
      "Buyer",
    );
    expect(await screen.findByText("Not sent", { selector: "[data-status='NOT_SENT']" })).toBeVisible();
    expect((await api.getApproval("APR-UNKNOWN-1046")).status).toBe("PENDING");
    expect(screen.queryByRole("button", { name: "It was not sent" })).not.toBeInTheDocument();
  });

  it("shows the role explanation to a viewer without loading or offering resolution actions", async () => {
    const viewer = createMockApi();
    await viewer.signIn("planner@demo.valio", "demo-kitchen-2026");
    const lookup = vi.spyOn(viewer, "getOrderResolution");
    renderApp("/orders/ORD-1046", viewer);
    expect(await screen.findByRole("alert")).toHaveTextContent("Your role cannot resolve orders");
    expect(lookup).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "It was placed" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "It was not sent" })).not.toBeInTheDocument();
  });

  it("shows the role explanation to a chef without loading or offering resolution actions", async () => {
    const chef = createMockApi();
    await chef.signIn("chef@demo.kitchen", "demo-kitchen-2026");
    const lookup = vi.spyOn(chef, "getOrderResolution");
    renderApp("/orders/ORD-1046", chef);
    expect(await screen.findByRole("alert")).toHaveTextContent("Your role cannot resolve orders");
    expect(lookup).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "It was placed" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "It was not sent" })).not.toBeInTheDocument();
  });

  it("does not offer resolution actions when resolvable is false", async () => {
    const api = createMockApi();
    api.getOrderResolution = async () => ({ ...(await createMockApi().getOrderResolution("ORD-1046")), resolvable: false });
    renderApp("/orders/ORD-1046", api);
    expect(await screen.findByText("approve-unknown-1046")).toBeVisible();
    expect(screen.queryByRole("button", { name: "It was placed" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "It was not sent" })).not.toBeInTheDocument();
  });

  it.each([
    ["HUMAN_SESSION_REQUIRED", "Only a signed-in person can check or resolve this order. Nothing was sent."],
    ["ROLE_REQUIRED", "Your role cannot resolve orders. Ask an approver to check with the supplier."],
  ])("shows the plain permission message for %s", async (code, message) => {
    const api = createMockApi();
    api.getOrderResolution = async () => {
      throw new ApiError(code, code);
    };
    renderApp("/orders/ORD-1046", api);
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByRole("button", { name: "It was placed" })).not.toBeInTheDocument();
  });

  it.each([
    ["ALREADY_RESOLVED", "Someone else already resolved this order another way. Reloading the latest details."],
    ["ORDER_NOT_RESOLVABLE", "This order is no longer waiting for resolution. Reloading the latest details."],
    ["INVALID_REQUEST", "Enter the supplier's order reference (1 to 200 characters). Nothing was recorded."],
  ])("shows the plain resolution error for %s", async (code, message) => {
    const user = userEvent.setup();
    const api = createMockApi();
    api.resolveOrder = async () => {
      throw new ApiError(code, code);
    };
    renderApp("/orders/ORD-1046", api);
    await user.click(await screen.findByRole("button", { name: "It was placed" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Supplier order reference"), "VAL-1");
    await user.click(within(dialog).getByRole("button", { name: "Confirm placed" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });
});
