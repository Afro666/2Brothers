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

  it("is null when the note was dropped or is empty", async () => {
    for (const body of [
      { ...ANSWER, note: null, dropped: "NUMBER_NOT_IN_ROW" },
      { ...ANSWER, note: [], rows_used: 0 },
    ]) {
      gateway(body);
      expect(await createHttpApi("/api").getBuyingNote("2026-11-16", "2026-11-22", "en")).toBeNull();
    }
  });

  it("rejects gateway failures so the page can explain them", async () => {
    for (const [body, status] of [
      [{ error: { code: "SCOPE_REQUIRED", message: "no" } }, 403],
      [{ error: { code: "BUYING_NOTE_UNAVAILABLE", message: "down" } }, 502],
    ] as const) {
      gateway(body, status);
      await expect(createHttpApi("/api").getBuyingNote("2026-11-16", "2026-11-22", "en")).rejects.toMatchObject({
        code: body.error.code,
        status,
      });
    }
    vi.stubGlobal("fetch", async () => { throw new Error("offline"); });
    await expect(createHttpApi("/api").getBuyingNote("2026-11-16", "2026-11-22", "en")).rejects.toMatchObject({
      code: "NETWORK",
    });
  });

  it("keeps the wait named by a rate-limited answer", async () => {
    gateway({ error: { code: "BUYING_NOTE_RATE_LIMITED", message: "wait", retry_after_s: 2 } }, 429);
    const refused = await createHttpApi("/api").getBuyingNote("2026-11-16", "2026-11-22", "en")
      .catch((reason: unknown) => reason);
    expect(refused).toMatchObject({ code: "RATE_LIMITED", status: 429, retryAfterS: 2 });
  });

  it("rejects a malformed answer instead of hiding the failed note", async () => {
    for (const body of [
      { ...ANSWER, model: 3 },
      { ...ANSWER, note: [{ ...ANSWER.note[0], risk: "LOW" }] },
      { ...ANSWER, note: [{ ...ANSWER.note[0], text: "" }] },
      { ...ANSWER, note: [{ ...ANSWER.note[0], product_name: undefined }] },
      { ...ANSWER, note: "none" },
    ]) {
      gateway(body);
      await expect(createHttpApi("/api").getBuyingNote("2026-11-16", "2026-11-22", "en")).rejects.toThrow();
    }
  });

  it("maps without the supplier's window", () => {
    expect(mapBuyingNote({ model: "m", note: null })).toBeNull();
    expect(mapBuyingNote({ model: "m", note: [] })).toBeNull();
    expect(mapBuyingNote(ANSWER)?.lines).toHaveLength(2);
  });

  it("rejects the note when a line's date is not a day", async () => {
    gateway({ ...ANSWER, note: [{ ...ANSWER.note[0], date: "next week" }] });
    await expect(createHttpApi("/api").getBuyingNote("2026-11-16", "2026-11-22", "fi")).rejects.toThrow();
  });
});
