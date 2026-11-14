import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { blobToBase64, mapShelfPhoto } from "@/api/http-shelf";

const COUNTED = {
  row: "COUNTED",
  product_id: "463038",
  product_name: "Valio Eila 10 L novobox",
  label: "Valio Eila 10 L novobox",
  confidence: "high",
  packs: 2,
  pack_size: "10",
  count: "20",
  unit: "L",
};
const UNSURE = { ...COUNTED, row: "PLEASE_COUNT", product_id: "463335", confidence: "low", packs: null, count: null };
const UNMATCHED = {
  row: "UNMATCHED",
  product_id: null,
  product_name: null,
  label: "Arla L m",
  confidence: "low",
  packs: null,
  pack_size: null,
  count: null,
  unit: null,
};
const ANSWER = { model: "nemotron-3.5-super-vl", duration_ms: 2150, saved: false, rows: [COUNTED, UNSURE, UNMATCHED] };

function gateway(answer: () => unknown) {
  const calls: { route: string; user: string | undefined; body: unknown }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    calls.push({
      route: `${init.method ?? "GET"} ${url}`,
      user: (init.headers as Record<string, string>)["X-User"],
      body: init.body ? JSON.parse(init.body as string) : null,
    });
    const body = answer();
    return body instanceof Response ? body : new Response(JSON.stringify(body));
  });
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("Count from a photo on the real gateway", () => {
  it("posts the photo as base64 JSON and maps the rows", async () => {
    const calls = gateway(() => ANSWER);
    const api = createHttpApi("/api");
    expect(api.live!.has("readShelfPhoto")).toBe(true);
    const read = await api.readShelfPhoto(new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])]), "human");
    expect(calls).toEqual([
      { route: "POST /api/v1/kitchens/demo-kitchen/stock/photo", user: "human", body: { image_base64: "/9j/4A==" } },
    ]);
    expect(read.model).toBe("nemotron-3.5-super-vl");
    expect(read.durationMs).toBe(2150);
    expect(read.rows[0]).toEqual({
      kind: "COUNTED",
      productId: "463038",
      productName: "Valio Eila 10 L novobox",
      label: "Valio Eila 10 L novobox",
      confidence: "high",
      packs: 2,
      packSize: 10,
      count: 20,
      unit: "L",
    });
    expect(read.rows[1]).toMatchObject({ kind: "PLEASE_COUNT", productId: "463335", packs: null, count: null });
    expect(read.rows[2]).toMatchObject({ kind: "UNMATCHED", productId: null, count: null, unit: null });
  });

  it("never lets a number through on a row that is not COUNTED", () => {
    const read = mapShelfPhoto({
      ...ANSWER,
      rows: [
        { ...UNSURE, packs: 3, count: "30" },
        { ...UNMATCHED, packs: 1, count: "1", product_id: "464179", unit: "L" },
      ],
    });
    expect(read.rows.map((row) => [row.kind, row.packs, row.count])).toEqual([
      ["PLEASE_COUNT", null, null],
      ["UNMATCHED", null, null],
    ]);
    expect(read.rows[1].productId).toBeNull();
  });

  it("refuses an answer it cannot trust", () => {
    const refused = (rows: unknown[]) => () => mapShelfPhoto({ ...ANSWER, rows });
    expect(refused([{ ...COUNTED, count: null }])).toThrow(/unexpected shape/);
    expect(refused([{ ...COUNTED, count: "-2" }])).toThrow(/unexpected shape/);
    expect(refused([{ ...COUNTED, packs: "2" }])).toThrow(/unexpected shape/);
    expect(refused([{ ...COUNTED, product_id: null }])).toThrow(/unexpected shape/);
    expect(refused([{ ...COUNTED, row: "GUESSED" }])).toThrow(/unexpected shape/);
    expect(() => mapShelfPhoto({ model: "nemotron-3.5-super-vl" })).toThrow(/unexpected shape/);
    expect(mapShelfPhoto({ ...ANSWER, rows: [] }).rows).toEqual([]);
  });

  it("passes the gateway's error code and sentence on", async () => {
    gateway(
      () =>
        new Response(JSON.stringify({ error: { code: "VISION_NOT_CONFIGURED", message: "no vision model" } }), {
          status: 503,
        }),
    );
    await expect(createHttpApi("/api").readShelfPhoto(new Blob(["x"]), "human")).rejects.toMatchObject({
      code: "VISION_NOT_CONFIGURED",
      message: "no vision model",
      status: 503,
    });
  });

  it("encodes a large photo in pieces", async () => {
    const bytes = new Uint8Array(100_000).map((_, index) => index % 251);
    const decoded = Uint8Array.from(atob(await blobToBase64(new Blob([bytes]))), (char) => char.charCodeAt(0));
    expect(decoded).toEqual(bytes);
  });
});
