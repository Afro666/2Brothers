import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createMockApi } from "@/api/mock";
import { mapDeliveryNote } from "@/api/http-delivery-note";
import { ApiError } from "@/api/types";
import { DELIVERY_NOTE } from "@/test/delivery-note-fixture";
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
    expect(screen.getByRole("button", { name: "Update counted stock" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "No, not received" }));
    const next = screen.getByRole("link", { name: "Update counted stock" });
    expect(next).toHaveAttribute("href", "/stock");
    expect(read).toHaveBeenCalledTimes(1); expect(save).not.toHaveBeenCalled();
    await user.click(next);
    expect(await screen.findByRole("heading", { level: 1, name: "Stock count" })).toBeVisible();
    expect(save).not.toHaveBeenCalled();
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
