import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { mapPriceListPhoto, mapPriceListRow } from "@/api/http-price-list";
import { ownProductBody } from "@/api/map-planning";
import { ApiError } from "@/api/types";

// The contract's example answer (docs/contract.md, "Read a supplier's price list from a photo").
const READ = {
  name: "Rye sourdough loaf 800 g",
  price_text: "4,40 €",
  price_unit_text: "kpl",
  pack_text: "800 g",
  status: "READ",
  reasons: [],
  draft: {
    name: "Rye sourdough loaf 800 g",
    supplier_id: "sup-bakery",
    unit: "ST",
    base_unit: "KG",
    pack_size_in_base_units: "0.8",
    unit_price_eur: "4.40",
    price_source: "price_list_photo",
    allergen_data: "UNKNOWN",
    allergens: [],
  },
  match: { product_id: "own-rye-loaf", name: "Rye sourdough loaf 800 g", unit_price_eur: "4.20", kind: "PRICE_CHANGED" },
};
const CHECK = {
  name: "Seed rolls",
  price_text: "0,95",
  price_unit_text: null,
  pack_text: null,
  status: "PLEASE_CHECK",
  reasons: ["PRICE_UNIT_MISSING"],
  draft: {
    name: "Seed rolls",
    supplier_id: "sup-bakery",
    unit: null,
    base_unit: null,
    pack_size_in_base_units: null,
    unit_price_eur: null,
    price_source: "price_list_photo",
    allergen_data: "UNKNOWN",
    allergens: [],
  },
  match: null,
};
const ANSWER = {
  model: "nemotron-3.5-super-vl",
  duration_ms: 5200,
  supplier_id: "sup-bakery",
  currency: "EUR",
  vat: "INCLUDED",
  truncated: false,
  rows: [READ, CHECK],
};

function gateway(answer: () => unknown) {
  const calls: { route: string; user: string | undefined; body: Record<string, unknown> | null }[] = [];
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

describe("Read a price list photo on the real gateway", () => {
  it("posts the photo to the supplier's route and maps the rows", async () => {
    const calls = gateway(() => ANSWER);
    const api = createHttpApi("/api");
    expect(api.live!.has("readPriceListPhoto")).toBe(true);
    const read = await api.readPriceListPhoto("sup-bakery", new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])]), "chef");
    expect(calls).toHaveLength(1);
    expect(calls[0].route).toBe("POST /api/v1/kitchens/demo-kitchen/suppliers/sup-bakery/price-list/photo");
    expect(calls[0].user).toBe("chef");
    expect(calls[0].body).toEqual({ image_base64: "/9j/4A==" });
    expect(read).toEqual({
      model: "nemotron-3.5-super-vl",
      durationMs: 5200,
      supplierId: "sup-bakery",
      currency: "EUR",
      vat: "INCLUDED",
      truncated: false,
      rows: [
        {
          printed: { name: "Rye sourdough loaf 800 g", price: "4,40 €", priceUnit: "kpl", pack: "800 g" },
          status: "READ",
          reasons: [],
          draft: { name: "Rye sourdough loaf 800 g", unit: "ST", baseUnit: "KG", packSize: 0.8, priceEur: 4.4 },
          match: { productId: "own-rye-loaf", name: "Rye sourdough loaf 800 g", priceEur: 4.2, kind: "PRICE_CHANGED" },
        },
        {
          printed: { name: "Seed rolls", price: "0,95", priceUnit: null, pack: null },
          status: "PLEASE_CHECK",
          reasons: ["PRICE_UNIT_MISSING"],
          draft: { name: "Seed rolls", unit: null, baseUnit: null, packSize: null, priceEur: null },
          match: null,
        },
      ],
    });
  });

  it("passes the busy and has-API refusals on as their codes", async () => {
    gateway(
      () =>
        new Response(JSON.stringify({ error: { code: "PRICE_LIST_BUSY", message: "busy" } }), { status: 429 }),
    );
    const api = createHttpApi("/api");
    await expect(api.readPriceListPhoto("sup-bakery", new Blob([new Uint8Array([1])]), "chef")).rejects.toMatchObject({
      code: "PRICE_LIST_BUSY",
    });
    gateway(
      () => new Response(JSON.stringify({ error: { code: "SUPPLIER_HAS_API", message: "api" } }), { status: 422 }),
    );
    await expect(api.readPriceListPhoto("sup-valio", new Blob([new Uint8Array([1])]), "chef")).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});

describe("mapPriceListRow", () => {
  it("keeps the unclear fields of a please-check row empty, even when the gateway sent them", () => {
    const row = mapPriceListRow({
      ...CHECK,
      reasons: ["PRICE_UNIT_MISSING", "PACK_UNCLEAR"],
      draft: { ...CHECK.draft, unit: "ST", unit_price_eur: "0.95", base_unit: "KG", pack_size_in_base_units: "1" },
    });
    expect(row.draft).toEqual({ name: "Seed rolls", unit: null, baseUnit: null, packSize: null, priceEur: null });
  });

  it("keeps the price of a row whose only doubt is the VAT", () => {
    const row = mapPriceListRow({ ...READ, status: "PLEASE_CHECK", reasons: ["VAT_UNKNOWN"] });
    expect(row.draft.priceEur).toBe(4.4);
  });

  it("refuses a row with an unknown status, and a zero price", () => {
    expect(() => mapPriceListRow({ ...READ, status: "GUESSED" })).toThrow("unexpected shape");
    expect(() => mapPriceListRow({ ...READ, draft: { ...READ.draft, unit_price_eur: "0" } })).toThrow("unexpected shape");
  });

  it("reads no VAT note and no currency as unknown, never assumed", () => {
    const read = mapPriceListPhoto({ ...ANSWER, vat: null, currency: null, rows: [] });
    expect(read.vat).toBeNull();
    expect(read.currency).toBeNull();
  });

  it("keeps a missing timing unknown, not zero", () => {
    const { duration_ms: _timing, ...untimed } = ANSWER;
    expect(mapPriceListPhoto(untimed).durationMs).toBeNull();
  });
});

describe("ownProductBody from a price-list row", () => {
  it("sends the measure the row names and the price source", () => {
    const body = ownProductBody(
      {
        name: "Rye loaf",
        unit: "ST",
        packSize: 0.8,
        baseUnit: "KG",
        priceEur: 4.4,
        supplierId: "sup-bakery",
        allergens: null,
        priceSource: "price_list_photo",
      },
      null,
    );
    expect(body).toMatchObject({
      unit: "ST",
      base_unit: "KG",
      pack_size_in_base_units: "0.8",
      unit_price_eur: "4.4",
      price_source: "price_list_photo",
      allergen_data: "UNKNOWN",
    });
  });

  it("sends no price source for a hand-typed product", () => {
    const body = ownProductBody(
      { name: "Rye loaf", unit: "KG", packSize: null, priceEur: 4.4, supplierId: "sup-bakery", allergens: null },
      null,
    );
    expect(body).not.toHaveProperty("price_source");
  });
});
