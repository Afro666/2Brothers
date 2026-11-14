import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createMockApi } from "@/api/mock";
import { mapDeliveryNote } from "@/api/http-delivery-note";
import { ApiError } from "@/api/types";
import { DELIVERY_NOTE, DEMO_DELIVERY_NOTE } from "@/test/delivery-note-fixture";
import { renderApp } from "@/test/render";

vi.mock("@/lib/shelf-photo", async (original) => ({ ...await original<typeof import("@/lib/shelf-photo")>(), downscalePhoto: vi.fn(async (file: Blob) => file) }));

describe("Delivery note on a placed order", () => {
  it("shows the shortfall, requires substitute review, and saves no stock before the count screen", async () => {
    const api = createMockApi();
    const read = vi.spyOn(api, "readDeliveryNote").mockResolvedValue(mapDeliveryNote(DELIVERY_NOTE, "ORD-1042"));
    const save = vi.spyOn(api, "submitStockCount");
    const user = userEvent.setup();
    renderApp("/orders/ORD-1042", api);
    const file = new File(["photo"], "note.jpg", { type: "image/jpeg" });
    await user.upload(await screen.findByLabelText("Choose a delivery note photo", { selector: "input" }), file);
    expect(await screen.findByText("Ordered: 51 ST; received: 36 ST; missing: 15 ST")).toBeVisible();
    expect(screen.getByText(/L2611A/)).toHaveTextContent("best before: unknown");
    expect(await screen.findByText("Valio Eila organic lactose free milk drink 1 L — Substitute")).toBeVisible();
    expect(screen.getByRole("button", { name: "Update counted stock" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "No, not received" }));
    const next = screen.getByRole("link", { name: "Update counted stock" });
    expect(next).toHaveAttribute("href", "/stock");
    expect(read).toHaveBeenCalledTimes(1); expect(save).not.toHaveBeenCalled();
    await user.click(next);
    expect(await screen.findByRole("heading", { level: 1, name: "Stock count" })).toBeVisible();
    expect(save).not.toHaveBeenCalled();
  });
  it("shows one total to claim and copies the claim as plain text, sending nothing (#1198)", async () => {
    const api = createMockApi();
    vi.spyOn(api, "readDeliveryNote").mockResolvedValue(mapDeliveryNote(DEMO_DELIVERY_NOTE, "ORD-1042"));
    vi.spyOn(api, "getProducts").mockResolvedValue([]);
    const user = userEvent.setup();     // it puts its own clipboard on navigator: spy on that one
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    renderApp("/orders/ORD-1042", api);
    await user.upload(await screen.findByLabelText("Choose a delivery note photo", { selector: "input" }), new File(["photo"], "note.jpg", { type: "image/jpeg" }));
    expect(await screen.findByText("3 cases short: €91.08 to claim from Valio Aimo")).toBeVisible();
    expect(screen.getByText("To claim: €62.02")).toBeVisible();
    expect(screen.getByText("To claim: €29.06")).toBeVisible();
    expect(screen.queryByText("A substitute you accept is not taken off this amount.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy the claim" }));
    expect(writeText).toHaveBeenCalledTimes(1);
    const text = writeText.mock.calls[0][0] as string;
    expect(text).toContain("Order: ORD-1042");
    expect(text).toContain("463982 (463982): Short delivery, ordered 3 KI, missing 2 KI, €31.01 each = €62.02");
    expect(text).toContain("460838 (460838): Missing, ordered 1 KI, missing 1 KI, €29.06 each = €29.06");
    expect(text).not.toContain("463335");                                  // a received line is no claim
    expect(text).toContain("Total to claim: €91.08 (ex VAT, at the order's prices)");
    expect(await screen.findByText("Claim copied. Nothing was sent to Valio Aimo.")).toBeVisible();
  });
  it("says which lines have no value and keeps them out of the total", async () => {
    const api = createMockApi();
    const answer = structuredClone(DELIVERY_NOTE);
    answer.claim = { ...answer.claim, not_valued: 1 };
    vi.spyOn(api, "readDeliveryNote").mockResolvedValue(mapDeliveryNote(answer, "ORD-1042"));
    renderApp("/orders/ORD-1042", api);
    await userEvent.upload(await screen.findByLabelText("Choose a delivery note photo", { selector: "input" }), new File(["photo"], "note.jpg", { type: "image/jpeg" }));
    expect(await screen.findByText("15 ST short: €16.50 to claim from Valio Aimo")).toBeVisible();
    expect(screen.getByText("1 more lines could not be valued; check them by hand.")).toBeVisible();
    expect(screen.getByText("A substitute you accept is not taken off this amount.")).toBeVisible();
  });
  it("falls back to the product id when the catalog lookup fails", async () => {
    const api = createMockApi();
    vi.spyOn(api, "readDeliveryNote").mockResolvedValue(mapDeliveryNote(DELIVERY_NOTE, "ORD-1042"));
    vi.spyOn(api, "getProducts").mockRejectedValue(new Error("NOT_SERVED"));
    renderApp("/orders/ORD-1042", api);
    await userEvent.upload(await screen.findByLabelText("Choose a delivery note photo", { selector: "input" }), new File(["photo"], "note.jpg", { type: "image/jpeg" }));
    expect(await screen.findByText("462921 — Substitute")).toBeVisible();
  });
  it("keeps failed reads actionable without inventing a receipt", async () => {
    const api = createMockApi();
    vi.spyOn(api, "readDeliveryNote").mockRejectedValue(new ApiError("VISION_TIMEOUT", "Vision timed out"));
    renderApp("/orders/ORD-1042", api);
    await userEvent.upload(await screen.findByLabelText("Choose a delivery note photo", { selector: "input" }), new File(["photo"], "note.jpg", { type: "image/jpeg" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Check the delivery by hand");
    expect(screen.queryByRole("link", { name: "Update counted stock" })).not.toBeInTheDocument();
  });
  it("does not allow viewers to invoke the paid vision reader", async () => {
    const api = createMockApi();
    const session = await api.getSession();
    api.getSession = async () => ({ ...session!, kind: "human", role: "viewer", canApprove: false });
    const read = vi.spyOn(api, "readDeliveryNote");
    renderApp("/orders/ORD-1042", api);
    await waitFor(() => expect(screen.getByText("A chef or approver can read a delivery note.")).toBeVisible());
    expect(screen.getByRole("button", { name: "Choose a delivery note photo" })).toBeDisabled();
    expect(read).not.toHaveBeenCalled();
  });
});
