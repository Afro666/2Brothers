import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { mapBuyingNote } from "@/api/http-buying-note";

const ANSWER = {
  supplier_id: "sup-valio", from: "2026-11-16", to: "2026-11-22", lang: "en",
  model: "nemotron-3.5-super-vl", duration_ms: 2140, cached: false, rows_used: 2,
  note: [
    { product_id: "462775", product_name: "Valio Eila lactose-free milk 1 L", date: "2026-11-16", risk: "SHORT",
      text: "Forecast 2400 L from 6 kitchens against 1700 L available: buy 700 L more." },
    { product_id: "463335", product_name: "Washed potato 10 kg", date: "2026-11-17", risk: "UNKNOWN",
      text: "Availability unknown for 3 kitchens: ask the grower." },
  ],
  dropped: null,
};

afterEach(() => vi.unstubAllGlobals());

function gateway(body: unknown, status = 200) {
  const fetch = vi.fn(async (_url: string) => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

const path = "/api/v1/suppliers/sup-valio/demand/buying-note?from=2026-11-16&to=2026-11-22&lang=fi";

describe("Buying note gateway boundary", () => {
  it("maps a valid answer and asks for the window and language", async () => {
    const fetch = gateway(ANSWER);
    const note = await createHttpApi("/api").getBuyingNote("2026-11-16", "2026-11-22", "fi");
    expect(fetch.mock.calls[0]?.[0]).toBe(path);
    expect(note).toEqual({
      model: "nemotron-3.5-super-vl",
      lines: [
        { productId: "462775", productName: "Valio Eila lactose-free milk 1 L", date: "2026-11-16", risk: "SHORT",
          text: "Forecast 2400 L from 6 kitchens against 1700 L available: buy 700 L more." },
        { productId: "463335", productName: "Washed potato 10 kg", date: "2026-11-17", risk: "UNKNOWN",
          text: "Availability unknown for 3 kitchens: ask the grower." },
      ],
    });
  });

  it("is null when the note was dropped or is empty, and when the gateway refuses", async () => {
    for (const body of [
      { ...ANSWER, note: null, dropped: "NUMBER_NOT_IN_ROW" },
      { ...ANSWER, note: [], rows_used: 0 },
      { error: { code: "SCOPE_REQUIRED", message: "no" } },
      { error: { code: "BUYING_NOTE_UNAVAILABLE", message: "down" } },
    ]) {
      for (const status of [200, 403, 502]) {
        gateway(body, status);
        expect(await createHttpApi("/api").getBuyingNote("2026-11-16", "2026-11-22", "en")).toBeNull();
      }
    }
  });

  it("is null on a malformed answer or an unreachable gateway", async () => {
    for (const body of [
      { ...ANSWER, model: 3 },
      { ...ANSWER, note: [{ ...ANSWER.note[0], risk: "LOW" }] },
      { ...ANSWER, note: [{ ...ANSWER.note[0], text: "" }] },
      { ...ANSWER, note: [{ ...ANSWER.note[0], product_name: undefined }] },
      { ...ANSWER, note: "none" },
    ]) {
      gateway(body);
      expect(await createHttpApi("/api").getBuyingNote("2026-11-16", "2026-11-22", "en")).toBeNull();
    }
    vi.stubGlobal("fetch", async () => { throw new Error("offline"); });
    expect(await createHttpApi("/api").getBuyingNote("2026-11-16", "2026-11-22", "en")).toBeNull();
  });

  it("maps without the supplier's window", () => {
    expect(mapBuyingNote({ model: "m", note: null })).toBeNull();
    expect(mapBuyingNote({ model: "m", note: [] })).toBeNull();
    expect(mapBuyingNote(ANSWER)?.lines).toHaveLength(2);
  });

  it("hides the note when a line's date is not a day", async () => {
    gateway({ ...ANSWER, note: [{ ...ANSWER.note[0], date: "next week" }] });
    expect(await createHttpApi("/api").getBuyingNote("2026-11-16", "2026-11-22", "fi")).toBeNull();
  });
});
