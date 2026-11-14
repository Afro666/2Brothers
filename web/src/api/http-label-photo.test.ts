import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { mapLabelPhoto } from "@/api/http-label-photo";
import { ApiError } from "@/api/types";
import { LABEL_ANSWER } from "@/test/label-photo-fixture";

afterEach(() => vi.unstubAllGlobals());

describe("Label photo gateway boundary (#1175)", () => {
  it("sends one image and the product to the order-scoped route", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify(LABEL_ANSWER)));
    vi.stubGlobal("fetch", fetch);
    const api = createHttpApi("/api");
    const read = await api.readLabelPhoto("ORD-1042", "462775", new Blob([new Uint8Array([0xff, 0xd8])]), "chef");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]).toEqual(["/api/v1/kitchens/demo-kitchen/orders/ORD-1042/label/photo", expect.objectContaining({
      method: "POST", body: JSON.stringify({ image_base64: "/9g=", product_id: "462775" }), headers: expect.objectContaining({ "X-User": "chef" }),
    })]);
    expect(api.live?.has("readLabelPhoto")).toBe(true);
    expect(read).toEqual({
      model: "nemotron-3.5-super-vl", durationMs: 3100, orderId: "ORD-1042", productId: "462775", inOrder: true,
      outcome: "EXCLUDED_ALLERGEN", message: LABEL_ANSWER.message, productCheck: "CONFIRMED_BY_EAN",
      label: { productName: "Arla", ean: "6408430000000", contains: [{ word: "MAITO", code: "AM" }],
        mayContain: [{ word: "maapähkinää", code: "AP" }], unknownWords: [] },
      excludedHits: [{ code: "AP", level: "MAY_CONTAIN" }],
      differences: [{ code: "AP", kind: "LABEL_ADDS", text: "The label lists peanuts (may contain); the catalog does not." }],
      catalogAllergenData: "KNOWN", pleaseCheck: [],
    });
  });

  it("passes the gateway's error code on, so the page can say it in plain words", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ error: { code: "VISION_TIMEOUT", message: "The label could not be read; read it yourself" } }), { status: 504 })));
    await expect(createHttpApi("/api").readLabelPhoto("ORD-1042", "462775", new Blob(["x"]), "human"))
      .rejects.toMatchObject({ code: "VISION_TIMEOUT", status: 504 });
  });

  it("never turns a reason to check, or an excluded hit, into agreement", () => {
    const check = mapLabelPhoto({ ...LABEL_ANSWER, outcome: "AGREES", excluded_hits: [], please_check: ["WORD_UNKNOWN"] }, "ORD-1042", "462775");
    expect(check.outcome).toBe("PLEASE_CHECK");
    const hit = mapLabelPhoto({ ...LABEL_ANSWER, outcome: "AGREES" }, "ORD-1042", "462775");
    expect(hit.outcome).toBe("EXCLUDED_ALLERGEN");
  });

  it("keeps a missing duration unknown", () => {
    const { duration_ms: _drop, ...rest } = LABEL_ANSWER;
    expect(mapLabelPhoto(rest, "ORD-1042", "462775").durationMs).toBeNull();
  });

  it("rejects an answer for another order or product, or an unknown outcome", () => {
    const bad = (body: unknown, product = "462775") => {
      try { mapLabelPhoto(body, "ORD-1042", product); } catch (e) {
        expect(e).toBeInstanceOf(ApiError); expect((e as ApiError).code).toBe("INVALID_RESPONSE"); return;
      }
      throw new Error("expected INVALID_RESPONSE");
    };
    bad({ ...LABEL_ANSWER, order_id: "ORD-9" });
    bad(LABEL_ANSWER, "999");
    bad({ ...LABEL_ANSWER, outcome: "SAFE" });
    bad({ ...LABEL_ANSWER, catalog_allergen_data: "FREE_FROM" });
  });
});
