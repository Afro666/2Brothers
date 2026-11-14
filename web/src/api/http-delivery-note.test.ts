import { afterEach, describe, expect, it, vi } from "vitest";
import { createHttpApi } from "@/api/http";
import { mapDeliveryNote } from "@/api/http-delivery-note";
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
});
