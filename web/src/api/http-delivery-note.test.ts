import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpApi } from "@/api/http";
import { mapDeliveryNote } from "@/api/http-delivery-note";
import { ApiError } from "@/api/types";
import { DELIVERY_NOTE } from "@/test/delivery-note-fixture";

afterEach(() => vi.unstubAllGlobals());
describe("Delivery note gateway boundary", () => {
  it("sends one image to the order-scoped route and preserves missing quantities", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify(DELIVERY_NOTE)));
    vi.stubGlobal("fetch", fetch);
    const api = createHttpApi("/api");
    const read = await api.readDeliveryNote("ORD-1042", new Blob([new Uint8Array([0xff, 0xd8])]), "human");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]).toEqual(["/api/v1/kitchens/demo-kitchen/orders/ORD-1042/delivery-note/photo", expect.objectContaining({
      method: "POST", body: JSON.stringify({ image_base64: "/9g=" }), headers: expect.objectContaining({ "X-User": "human" }),
    })]);
    expect(api.live?.has("readDeliveryNote")).toBe(true);
    expect(read.lines[0]).toMatchObject({ received: 36, missing: 15, baseUnit: "ST" });
  });
  it("keeps unknown quantities unknown even if a bad response includes numeric placeholders", () => {
    const r = structuredClone(DELIVERY_NOTE);
    r.lines[0].status = "UNKNOWN";
    r.lines[0].received = "0"; r.lines[0].missing = "51";
    expect(mapDeliveryNote(r, "ORD-1042").lines[0]).toMatchObject({ received: null, missing: null });
  });
  it("does not let an omitted approval flag turn a substitute into a confirmed receipt", () => {
    const r = structuredClone(DELIVERY_NOTE); r.not_ordered[0].needs_approval = false;
    expect(mapDeliveryNote(r, "ORD-1042").notOrdered[0].needsApproval).toBe(true);
  });
  it("accepts extras without a replacement and keeps an empty lot unknown", () => {
    const r = { ...DELIVERY_NOTE, not_ordered: [{ ...DELIVERY_NOTE.not_ordered[0], status: "EXTRA", replaces: undefined, lot: "" }] };
    expect(mapDeliveryNote(r, "ORD-1042").notOrdered[0]).toMatchObject({ replaces: "none", lot: "unknown", needsApproval: false });
  });
  it("rejects a reply for another order or an unexpected saved mutation", () => {
    expect(() => mapDeliveryNote(DELIVERY_NOTE, "another-order")).toThrow();
    expect(() => mapDeliveryNote({ ...DELIVERY_NOTE, saved: true }, "ORD-1042")).toThrow();
  });
  const invalidResponse = (fn: () => unknown) => {
    try { fn(); } catch (e) { expect(e).toBeInstanceOf(ApiError); expect((e as ApiError).code).toBe("INVALID_RESPONSE"); return; }
    throw new Error("expected INVALID_RESPONSE");
  };
  it("maps a valid gateway answer to a DeliveryNoteRead", () => {
    expect(mapDeliveryNote(DELIVERY_NOTE, "ORD-1042")).toEqual({
      orderId: "ORD-1042", model: "nemotron-3.5-super-vl", durationMs: 5120, orderRef: "ORD-DEMO-0001", deliveryDate: "2026-11-16", complete: false,
      lines: [{ productId: "462775", status: "SHORT", ordered: 51, received: 36, missing: 15, baseUnit: "ST",
        lots: [{ lot: "L2611A", bestBefore: "unknown", quantity: 3, unit: "KI" }] }],
      notOrdered: [{ productId: "462921", status: "SUBSTITUTE", replaces: "462775", quantity: 2, unit: "KI", received: 10, baseUnit: "ST",
        lot: "L2611B", bestBefore: "2026-11-28", needsApproval: true }],
    });
  });
  it("throws ApiError INVALID_RESPONSE on a wrong order, a saved answer or an unknown status", () => {
    invalidResponse(() => mapDeliveryNote(DELIVERY_NOTE, "another-order"));
    invalidResponse(() => mapDeliveryNote({ ...DELIVERY_NOTE, saved: true }, "ORD-1042"));
    const line = structuredClone(DELIVERY_NOTE); line.lines[0].status = "DAMAGED";
    invalidResponse(() => mapDeliveryNote(line, "ORD-1042"));
    const other = structuredClone(DELIVERY_NOTE); other.not_ordered[0].status = "GIFT";
    invalidResponse(() => mapDeliveryNote(other, "ORD-1042"));
  });
  it("maps the quantity 'unknown' to null", () => {
    const r = structuredClone(DELIVERY_NOTE); r.lines[0].lots[0].quantity = "unknown"; r.lines[0].ordered = "unknown";
    const read = mapDeliveryNote(r, "ORD-1042");
    expect(read.lines[0].ordered).toBeNull();
    expect(read.lines[0].lots[0].quantity).toBeNull();
  });
  it("is complete only when every line is RECEIVED and nothing else came", () => {
    const r = structuredClone(DELIVERY_NOTE);
    r.complete = true; r.lines[0].status = "RECEIVED"; r.lines[0].received = "51"; r.lines[0].missing = "0";
    expect(mapDeliveryNote(r, "ORD-1042").complete).toBe(false);
    expect(mapDeliveryNote({ ...r, not_ordered: [] }, "ORD-1042").complete).toBe(true);
    const short = structuredClone(r); short.not_ordered = []; short.lines[0].status = "SHORT";
    expect(mapDeliveryNote(short, "ORD-1042").complete).toBe(false);
  });
});
