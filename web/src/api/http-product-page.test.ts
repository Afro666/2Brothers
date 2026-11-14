import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { mapProductPage } from "@/api/http-product-page";

const K = "/api/v1/kitchens/demo-kitchen";

/** The salmon page of docs/contract.md "Product page", with a second supplier. */
const SALMON = {
  product_id: "461903",
  product: {
    product_id: "461903",
    source: "valio",
    names: { en: "Salmon fillet A, ASC", fi: "Lohifilee A, ASC" },
    brand: "Kalavapriikki",
    sales_unit: "KG",
    base_unit: "KG",
    units: [{ unit: "KG", size_in_base_units: 1.0 }],
    net_content: { value: 1.0, unit: "KG" },
    allergen_data_known: true,
    allergens: { contains: ["AF"], may_contain: [] },
    temperature: "chilled",
    min_temperature_c: 0,
    max_temperature_c: 2,
    vat_code: "MEDIUM",
    vat_rate: "13.5",
    vat_source: "catalog",
  },
  about: {
    marketing_text: { en: "Salmon fillet." },
    key_ingredients: null,
    ingredients: [{ en: "Salmon", fi: "Lohi" }],
    storage_instructions: { en: "Keep at 0 to +2 °C." },
    preparation_instructions: null,
    usage_instructions: null,
    producer: "Kalavapriikki Oy",
    source: "Valio product data",
  },
  allergens: {
    known: true,
    contains: [{ code: "AF", name: "fish" }],
    may_contain: [],
    free_from: [{ code: "AW", name: null }],
    undeclared: [],
    no_declarable_allergens: false,
    source: "Valio product data, allergen classification",
  },
  nutrition: { basis: "g", per: "100", values: { kcal: "208", fat_g: "13" }, source: "Valio product data, nutritionalContent" },
  storage: { temperature: "chilled", min_temperature_c: 0, max_temperature_c: 2, source: "Valio product data" },
  origin: { country: "no", source: "Valio product data, countryOfOrigin" },
  vat: { code: "MEDIUM", rate: "13.5", source: "Valio product data, vatCode" },
  units: { sales_unit: "KG", base_unit: "KG", units: [], net_content: { value: 1.0, unit: "KG" }, source: "Valio product data" },
  live: {
    date: "2026-11-16",
    price_ex_vat: "24.85",
    price_incl_vat: "28.20",
    per: "KG",
    tax_rate: "13.5",
    comparison_price: "24.85",
    comparison_unit: "KG",
    stock: { available: "120", unknown: false, available_date: "2026-11-16", orderable: true, cutoff_passed: false, closing_time: "2026-11-15T13:00:00+02:00" },
    error: null,
    source: "Valio price and availability API",
  },
  recall: { status: "CLEAR", alerts: [], source: "this kitchen's recall alerts" },
  suppliers: [
    {
      supplier_id: "sup-valio", name: "Valio Aimo", adapter: "valio_api", product_id: "461903",
      product_name: "Salmon fillet A, ASC", price_ex_vat: "24.85", per: "KG", price_source: "Valio price API",
      vat_rate: "13.5", stock_known: true, net_content: { value: 1.0, unit: "KG" }, lead_time_days: 1,
      lead_time_source: "supplier_terms", order_days: ["MON", "TUE"], cutoff_time: "17:00",
      free_delivery_threshold_eur: "300.00", delivery_fee_eur: "25.00", terms_source: "supplier_terms",
    },
    {
      supplier_id: "sup-demo-fish", name: "Baltic Catch Fish Wholesale (demo)", adapter: "manual", product_id: "own-1",
      product_name: "Salmon fillet", price_ex_vat: "112.50", per: "KI", price_source: "entered",
      vat_rate: null, stock_known: false, net_content: { value: 5, unit: "KG" }, lead_time_days: null,
      lead_time_source: null, order_days: null, cutoff_time: null,
      free_delivery_threshold_eur: null, delivery_fee_eur: null, terms_source: null,
    },
  ],
  kitchen: {
    orders: [{ order_id: "o-1", created_at: "2026-11-09T08:00:00+00:00", quantity: "10", unit: "KG", total: "248.50", status: "PLACED" }],
    proposals_waiting: [{ proposal_id: "p-1", created_at: "2026-11-13T08:00:00+00:00", quantity: "10", unit: "KG", total: "248.50" }],
    stock: { on_hand: "3.2", unit: "KG", counted_at: "2026-11-13T10:00:00+00:00" },
    recipes: [{ recipe_id: "env-salmon_soup", name: "Salmon soup", qty_per_portion: "0.08", unit: "KG" }],
    demand: { from: "2026-11-15", to: "2026-11-28", unit: "KG", gross_need: "14.2", days: 9, source: "menu plan and forecast" },
  },
};

afterEach(() => vi.unstubAllGlobals());

describe("getProductPage on the gateway", () => {
  it("reads the product page route with the date and maps the answer", async () => {
    const urls: string[] = [];
    vi.stubGlobal("fetch", async (url: string) => {
      urls.push(url);
      return new Response(JSON.stringify(SALMON));
    });
    const api = createHttpApi("/api");
    expect(api.live!.has("getProductPage")).toBe(true);
    const page = await api.getProductPage("461903", "2026-11-16");

    expect(urls).toEqual([`${K}/catalog/products/461903?date=2026-11-16`]);
    expect(page.product.names.en).toBe("Salmon fillet A, ASC");
    expect(page.vat).toEqual({ code: "MEDIUM", rate: 13.5, source: "Valio product data, vatCode" });
    expect(page.allergens.contains).toEqual([{ code: "AF", name: "fish" }]);
    // A free-from code without a name keeps its code.
    expect(page.allergens.freeFrom).toEqual([{ code: "AW", name: "AW" }]);
    expect(page.live?.stock?.available).toBe(120);
    expect(page.nutrition?.values).toEqual({ kcal: 208, fat_g: 13 });
    expect(page.suppliers.map((s) => [s.name, s.pricePerMeasure, s.stockKnown])).toEqual([
      ["Valio Aimo", 24.85, true],
      ["Baltic Catch Fish Wholesale (demo)", 22.5, false],
    ]);
    expect(page.suppliers[1].vatRate).toBeNull();
    expect(page.suppliers[1].leadTimeDays).toBeNull();
    expect(page.kitchen.orders[0]).toMatchObject({ id: "o-1", quantity: 10, total: 248.5 });
    expect(page.kitchen.proposalsWaiting[0].id).toBe("p-1");
    expect(page.kitchen.demand?.grossNeed).toBe(14.2);
  });

  it("keeps unknown VAT, unknown stock and unknown allergens unknown, never 0 or none", () => {
    const page = mapProductPage({
      ...SALMON,
      product: { ...SALMON.product, allergen_data_known: false, allergens: {}, vat_code: null, vat_rate: null },
      allergens: { known: false, contains: [], may_contain: [], free_from: [], undeclared: [], no_declarable_allergens: false, source: null },
      vat: { code: null, rate: null, source: null },
      live: { ...SALMON.live, price_incl_vat: null, tax_rate: null, stock: { ...SALMON.live.stock, available: null, unknown: true } },
      nutrition: null,
      kitchen: { orders: [], proposals_waiting: [], stock: null, recipes: [], demand: null },
    });
    expect(page.vat.rate).toBeNull();
    expect(page.live?.priceInclVat).toBeNull();
    expect(page.live?.stock).toMatchObject({ available: null, unknown: true });
    expect(page.allergens.known).toBe(false);
    expect(page.product.allergens).toBeNull();
    expect(page.nutrition).toBeNull();
    expect(page.kitchen.stock).toBeNull();
  });

  it("keeps a Valio error on the page instead of failing it", () => {
    const page = mapProductPage({
      ...SALMON,
      live: { date: "2026-11-16", price_ex_vat: null, price_incl_vat: null, per: null, tax_rate: null, comparison_price: null, comparison_unit: null, stock: null, error: "VALIO_UNAVAILABLE", source: "Valio price and availability API" },
    });
    expect(page.live).toMatchObject({ error: "VALIO_UNAVAILABLE", priceExVat: null, stock: null });
  });

  it("passes a 404 PRODUCT_NOT_FOUND on as an error", async () => {
    vi.stubGlobal("fetch", async () =>
      new Response(JSON.stringify({ error: { code: "PRODUCT_NOT_FOUND", message: "no such product" } }), { status: 404 }),
    );
    await expect(createHttpApi("/api").getProductPage("999999")).rejects.toMatchObject({ code: "PRODUCT_NOT_FOUND" });
  });
});
