import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api";
import { mapReceipt } from "@/api/gateway-map";
import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("orders pages", () => {
  beforeEach(() => localStorage.clear());

  it("shows supplier confirmation notices by name and falls back to the supplier id", async () => {
    const api = createMockApi();
    const getOrder = api.getOrder;
    api.getOrder = async (id) => ({
      ...(await getOrder(id)),
      supplierMustConfirm: ["SUP-BAKERY", "sup-unknown"],
    });
    renderApp("/orders/ORD-1047", api);

    expect(
      await screen.findByText(
        "Waiting for Töölö Bakery to confirm. Call or e-mail them: this order was sent without a stock confirmation.",
      ),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Waiting for sup-unknown to confirm. Call or e-mail them: this order was sent without a stock confirmation.",
      ),
    ).toBeVisible();
  });

  it("names Valio Aimo when the kitchen has no supplier row for sup-valio", async () => {
    const api = createMockApi();
    const getOrder = api.getOrder;
    const listOrders = api.listOrders;
    api.listSuppliers = async () => [];
    api.getOrder = async (id) => ({ ...(await getOrder(id)), supplierMustConfirm: ["sup-valio"] });
    api.listOrders = async () =>
      (await listOrders()).map((order) =>
        order.id === "ORD-1047" ? { ...order, supplierMustConfirm: ["SUP-VALIO"] } : order,
      );
    renderApp("/orders/ORD-1047", api);

    expect(
      await screen.findByText(
        "Waiting for Valio Aimo to confirm. Call or e-mail them: this order was sent without a stock confirmation.",
      ),
    ).toBeVisible();
    expect(screen.queryByText(/sup-valio/i)).not.toBeInTheDocument();
    cleanup();

    renderApp("/orders", api);
    const row = await screen.findByRole("link", { name: /ORD-1047/ });
    expect(within(row).getByText("Call Valio Aimo to confirm")).toBeVisible();
  });

  it("badges the order history row without replacing its gateway status", async () => {
    renderApp("/orders");

    const row = await screen.findByRole("link", { name: /ORD-1047/ });
    expect(within(row).getByText("Arla 1 L lactose free fat free UHT milk drink × 51 ST")).toBeVisible();
    expect(within(row).getByText("Call Töölö Bakery to confirm")).toBeVisible();
    expect(within(row).getByText("Placed", { selector: "[data-status='PLACED']" })).toBeVisible();
    expect(within(row).queryByText("Runs out before next delivery")).not.toBeInTheDocument();
  });

  it("shows no supplier confirmation notice for a regular order", async () => {
    renderApp("/orders/ORD-1042");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Arla 1 L lactose free fat free UHT milk drink × 51 ST" }),
    ).toBeVisible();
    expect(screen.queryByText(/Waiting for .* to confirm\. Call or e-mail them/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Call .* to confirm/)).not.toBeInTheDocument();
  });

  it("uses the products as the title and a short selectable id as the receipt reference", async () => {
    const longId = "d2148e9a0b1c4d5e6f708192a3b4c5d6";
    const api = createMockApi();
    const getOrder = api.getOrder;
    api.getOrder = async () => ({ ...(await getOrder("ORD-1042")), id: longId });
    renderApp(`/orders/${longId}`, api);

    const title = "Arla 1 L lactose free fat free UHT milk drink × 51 ST";
    expect(await screen.findByRole("heading", { level: 1, name: title })).toBeVisible();
    expect(screen.getByRole("heading", { level: 2, name: title })).toBeVisible();
    const reference = screen.getByText("d2148e9a…", { selector: "code" });
    expect(reference).toHaveAttribute("title", longId);
    expect(reference).toHaveClass("select-text");
    expect(screen.queryByRole("heading", { name: longId })).not.toBeInTheDocument();
  });

  it("links from the order list to its detail and shows lines and filtered history", async () => {
    const user = userEvent.setup();
    renderApp("/orders");

    await user.click(await screen.findByRole("link", { name: /ORD-1042/ }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Arla 1 L lactose free fat free UHT milk drink × 51 ST" }),
    ).toBeInTheDocument();
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
    expect(within(block).getByText("Signed", { selector: ".stamp" })).toBeVisible();
    expect(within(block).getByText("Signed by the gateway. Anyone can check it with the public key.")).toBeVisible();
    expect(within(block).getByText("Approved by").nextElementSibling).toHaveTextContent("aron");
    expect(within(block).getByText("Signed total").nextElementSibling).toHaveTextContent("148.76");
    expect(within(block).getByText("Signed at").nextElementSibling).not.toHaveTextContent("unknown");
    expect(within(block).getByText("Supplier").nextElementSibling).toHaveTextContent("Nothing sent to the supplier yet");
    expect(within(block).getByText(/Valio's API has no order endpoint/)).toBeVisible();

    await user.click(within(block).getByRole("button", { name: "Copy receipt" }));
    expect(writeText).toHaveBeenCalledWith(receipt!.jws);
    // The sample is shaped like the gateway's: the real mapper reads the same claims back.
    expect(mapReceipt(receipt!.jws)).toEqual(receipt);
  });

  it("maps the supplier outcome claim and leaves it null when absent", async () => {
    const { receipt } = await createMockApi().getOrder("ORD-1042");
    expect(mapReceipt(receipt!.jws)?.supplierOutcome).toBe("NOT_SENT");

    const [header, payload, signature] = receipt!.jws.split(".");
    const claims = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    delete claims.supplier_outcome;
    const withoutClaim = [header, btoa(JSON.stringify(claims)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""), signature].join(".");
    expect(mapReceipt(withoutClaim)?.supplierOutcome).toBeNull();
  });

  it("maps the supplier note claim; an absent or empty note is null and renders nothing", async () => {
    const api = createMockApi();
    const order = await api.getOrder("ORD-1042");
    expect(mapReceipt(order.receipt!.jws)?.supplierNote).toMatch(/^Valio's API has no order endpoint/);

    const [header, payload, signature] = order.receipt!.jws.split(".");
    const claims = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    const encode = (value: unknown) => btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    expect(mapReceipt([header, encode({ ...claims, supplier_note: "" }), signature].join("."))?.supplierNote).toBeNull();
    delete claims.supplier_note;
    const withoutNote = [header, encode(claims), signature].join(".");
    expect(mapReceipt(withoutNote)?.supplierNote).toBeNull();

    vi.spyOn(api, "getOrder").mockResolvedValue({ ...order, receipt: mapReceipt(withoutNote) });
    renderApp("/orders/ORD-1042", api);
    const block = (await screen.findByRole("heading", { name: "Signed receipt" })).closest("section")!;
    expect(within(block).getByText("Supplier").nextElementSibling).toHaveTextContent("Nothing sent to the supplier yet");
    expect(within(block).queryByText(/Valio's API has no order endpoint/)).not.toBeInTheDocument();
  });

  it("says when a placed order has no signed receipt", async () => {
    renderApp("/orders/ORD-1046");

    const block = (await screen.findByRole("heading", { name: "Signed receipt" })).closest("section")!;
    expect(within(block).getByText("No signed receipt (this order is from before receipts, or signing was not possible)")).toBeVisible();
    expect(within(block).queryByRole("button", { name: "Copy receipt" })).not.toBeInTheDocument();
    expect(within(block).queryByText("Signed", { selector: ".stamp" })).not.toBeInTheDocument();
  });

  it("shows no receipt footer before an order has been placed", async () => {
    renderApp("/orders/ORD-1043");

    expect(await screen.findByRole("heading", { level: 1, name: /Valio Eila/ })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Signed receipt" })).not.toBeInTheDocument();
    expect(screen.queryByText("Copy receipt")).not.toBeInTheDocument();
  });

  it("describes the gateway's generic approver as a person", async () => {
    const api = createMockApi();
    const getOrder = api.getOrder;
    api.getOrder = async (id) => {
      const order = await getOrder(id);
      return { ...order, receipt: order.receipt ? { ...order.receipt, approvedBy: "human" } : order.receipt };
    };
    renderApp("/orders/ORD-1042", api);

    const block = (await screen.findByRole("heading", { name: "Signed receipt" })).closest("section")!;
    expect(within(block).getByText("Approved by").nextElementSibling).toHaveTextContent("a person");
  });

  it("keeps an unnamed approver unknown", async () => {
    const api = createMockApi();
    const getOrder = api.getOrder;
    api.getOrder = async (id) => {
      const order = await getOrder(id);
      return { ...order, receipt: order.receipt ? { ...order.receipt, approvedBy: null } : order.receipt };
    };
    renderApp("/orders/ORD-1042", api);

    const block = (await screen.findByRole("heading", { name: "Signed receipt" })).closest("section")!;
    expect(within(block).getByText("Approved by").nextElementSibling).toHaveTextContent("unknown");
  });

  it("uses the order's own incl-VAT total and shows its VAT and delivery fee", async () => {
    const api = createMockApi();
    const getOrder = api.getOrder;
    api.getOrder = async (id) => ({
      ...(await getOrder(id)),
      totalExVat: 1,
      vat: 2,
      deliveryFee: 3,
      totalInclVat: 999.99,
    });
    renderApp("/orders/ORD-1042", api);

    expect(await screen.findByText("VAT")).toBeVisible();
    expect(screen.getByText("VAT").nextElementSibling).toHaveTextContent("€2.00");
    expect(screen.getByText("Delivery fee").nextElementSibling).toHaveTextContent("€3.00");
    expect(screen.getByText("Total incl VAT").nextElementSibling).toHaveTextContent("€999.99");
  });

  it("omits urgency on a placed order but keeps it on a proposal", async () => {
    renderApp("/orders/ORD-1042");
    expect(await screen.findByRole("heading", { level: 1, name: /Arla 1 L/ })).toBeVisible();
    expect(screen.queryByText("Runs out before next delivery", { selector: "[data-urgency]" })).not.toBeInTheDocument();
  });

  it("order history keeps urgency on a waiting proposal and omits it on a placed order", async () => {
    renderApp("/orders", createMockApi());
    const placed = (await screen.findAllByText("Placed"))[0]!.closest("li")!;
    const waiting = screen.getAllByText("Needs approval")[0]!.closest("li")!;
    expect(placed.querySelector("[data-urgency]")).toBeNull();
    expect(waiting.querySelector("[data-urgency]")).not.toBeNull();
  });

  it("keeps urgency on a proposal", async () => {
    renderApp("/orders/ORD-1043");
    expect(await screen.findByRole("heading", { level: 1, name: /Valio Eila/ })).toBeVisible();
    expect(screen.getByText("Unknown: treat as urgent", { selector: "[data-urgency]" })).toBeVisible();
  });

  it("shows a product code only once when it is also the product name", async () => {
    const api = createMockApi();
    const getOrder = api.getOrder;
    api.getOrder = async (id) => {
      const order = await getOrder(id);
      const [line] = order.lines;
      return {
        ...order,
        lines: [{ ...line!, product: { ...line!.product, names: { en: line!.product.id } } }],
      };
    };
    renderApp("/orders/ORD-1042", api);

    const lines = await screen.findByRole("list", { name: "Lines" });
    const code = (await api.getOrder("ORD-1042")).lines[0]!.product.id;
    expect(within(lines).getAllByText(code, { exact: true })).toHaveLength(1);
  });

  it("names an unknown pack size once without removing the sales unit", async () => {
    const api = createMockApi();
    const getOrder = api.getOrder;
    api.getOrder = async (id) => {
      const order = await getOrder(id);
      const [line] = order.lines;
      return {
        ...order,
        lines: [
          {
            ...line!,
            product: { ...line!.product, salesUnit: "KG", baseUnitsPerSalesUnit: null },
          },
        ],
      };
    };
    renderApp("/orders/ORD-1042", api);

    const lines = await screen.findByRole("list", { name: "Lines" });
    expect(within(lines).getByText("pack size not in the catalog")).toHaveClass("unknown-value");
    expect(within(lines).getByText("pack size not in the catalog").parentElement).toHaveTextContent("KG");
    expect(within(lines).queryByText(/pack size unknown/)).not.toBeInTheDocument();
  });

  it("shows the API error for an unknown id", async () => {
    const api = createMockApi();
    const message = "Order ORD-missing was not found.";
    api.getOrder = async () => {
      throw new ApiError("NOT_FOUND", message);
    };
    renderApp("/orders/ORD-missing", api);

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("heading", { level: 1, name: "Order" })).toBeInTheDocument();
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
