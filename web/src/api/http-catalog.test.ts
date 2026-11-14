import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { mapCatalogProduct } from "@/api/http-catalog";
import { products } from "@/mocks/milk-case";

const K = "/api/v1/kitchens/demo-kitchen";

/** A fake gateway: `"POST /path"` -> the JSON it answers. Returns the calls it received. */
function gateway(routes: Record<string, (body: Record<string, unknown>) => unknown>) {
  const calls: { route: string; body: Record<string, unknown> }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    const route = `${init.method ?? "GET"} ${url}`;
    const body = init.body ? JSON.parse(init.body as string) : {};
    calls.push({ route, body });
    const answer = routes[route]
      ? routes[route](body)
      : new Response(JSON.stringify({ error: { code: "NO_ROUTE", message: route } }), { status: 404 });
    return answer instanceof Response ? answer : new Response(JSON.stringify(answer));
  });
  return calls;
}

/** One product row as store/products.py `flatten` writes it (without `raw`), plus the search fields. */
const MILK = {
  product_id: "463335",
  source: "valio",
  supplier_id: "sup-valio",
  names: { fi: "Valio laktoositon kevytmaitojuoma 1 l", en: "Valio lactose free semi-skimmed milk drink 1 l" },
  brand: "Valio",
  category: "01010",
  vendor: "Valio Oy",
  country: "fi",
  base_unit: "ST",
  sales_unit: "KI",
  lot_size: null,
  units: [
    { unit: "ST", size_in_base_units: 1, gtin: "6408430000111" },
    { unit: "KI", size_in_base_units: 12, gtin: "6408430000128" },
  ],
  net_content: { value: 1, unit: "L" },
  net_content_source: "synkka",
  allergens: { contains: ["AM"], may_contain: ["AW"], undeclared: ["AY"] },
  allergen_data_known: true,
  no_declarable_allergens: false,
  free_from: ["ML"],
  claims: ["FREE_FROM_LACTOSE"],
  lactose_free: true,
  labels: ["GOODS_FROM_FINLAND_BLUE_SWAN", "SOME_LABEL_THE_UI_DOES_NOT_SHOW"],
  temperature: "chilled",
  temperature_condition: 3,
  min_temperature_c: 2,
  max_temperature_c: 6,
  reliability: 0.97,
  carbon_kg_co2e_per_kg: 1.2,
  substitutions: [],
  score: 7.5,
  match_reasons: ["size 1 L matches"],
};

/** Allergen data unknown, no brand, no English name, no temperature: the gaps stay unknown. */
const UNKNOWN = {
  ...MILK,
  product_id: "400001",
  names: { fi: "Kaurajuoma" },
  brand: null,
  vendor: null,
  allergens: { contains: [], may_contain: [], undeclared: [] },
  allergen_data_known: false,
  labels: [],
  temperature: null,
  temperature_condition: null,
  reliability: null,
  carbon_kg_co2e_per_kg: null,
  units: [],
  net_content: null,
};

afterEach(() => vi.unstubAllGlobals());

describe("Catalog search on the real gateway", () => {
  it("marks searchProducts and getProducts as live, so the Catalog page shows no Sample data badge", () => {
    const live = createHttpApi("/api").live!;
    expect(live.has("searchProducts")).toBe(true);
    expect(live.has("getProducts")).toBe(true);
  });

  it("posts the query and the gateway's filter names, and maps the rows", async () => {
    const calls = gateway({ "POST /api/tools/search_products": () => ({ products: [MILK], search: "text" }) });
    const found = await createHttpApi("/api").searchProducts("milk", {
      excludedAllergens: ["AM", "AE"],
      strictAllergens: true,
      requiredLabels: ["EU_ORGANIC_FARMING"],
      temperature: "chilled",
    });
    expect(calls).toEqual([
      {
        route: "POST /api/tools/search_products",
        body: {
          query: "milk",
          filters: {
            exclude_allergens: ["AM", "AE"],
            allergen_strictness: "strict",
            require_labels: ["EU_ORGANIC_FARMING"],
            temperature: "chilled",
          },
          limit: 50,
        },
      },
    ]);
    expect(found.map((product) => product.id)).toEqual(["463335"]);
  });

  it("sends no filter the person did not set, and declared strictness when not strict", async () => {
    const calls = gateway({ "POST /api/tools/search_products": () => ({ products: [], search: "text" }) });
    await createHttpApi("/api").searchProducts("butter");
    await createHttpApi("/api").searchProducts("butter", { excludedAllergens: ["AM"], strictAllergens: false });
    expect(calls.map((call) => call.body.filters)).toEqual([{}, { exclude_allergens: ["AM"], allergen_strictness: "declared" }]);
  });

  it("does not call the gateway for an empty search: the gateway needs a query or a filter", async () => {
    const calls = gateway({});
    expect(await createHttpApi("/api").searchProducts("  ")).toEqual([]);
    expect(calls).toEqual([]);
  });

  it("searches with filters alone when the query is empty", async () => {
    const calls = gateway({ "POST /api/tools/search_products": () => ({ products: [MILK], search: "text" }) });
    await createHttpApi("/api").searchProducts("", { temperature: "frozen" });
    expect(calls[0].body).toMatchObject({ query: "", filters: { temperature: "frozen" } });
  });

  it("passes a gateway error on, never the sample products", async () => {
    gateway({
      "POST /api/tools/search_products": () =>
        new Response(JSON.stringify({ error: { code: "INVALID_REQUEST", message: "unknown allergen" } }), { status: 422 }),
    });
    await expect(createHttpApi("/api").searchProducts("milk")).rejects.toMatchObject({ code: "INVALID_REQUEST" });
  });

  it("searches by meaning only when asked, and keeps how each row was found (#1382)", async () => {
    const calls = gateway({
      "POST /api/tools/search_products": () => ({
        products: [
          { ...MILK, matched_by: "meaning" },
          { ...MILK, product_id: "463336", matched_by: "both" },
          { ...MILK, product_id: "463337", matched_by: "something else" },
        ],
        search: "hybrid",
      }),
    });
    const found = await createHttpApi("/api").searchProducts("dairy-free drink", { byMeaning: true });
    await createHttpApi("/api").searchProducts("dairy-free drink");
    expect(calls[0].body).toMatchObject({ query: "dairy-free drink", filters: {}, mode: "hybrid" });
    expect(calls[1].body).not.toHaveProperty("mode");
    expect(found.map((product) => product.matchedBy)).toEqual(["meaning", "both", undefined]);
    expect(found.meaningUnavailable).toBeUndefined();
  });

  it("says when the gateway used words because the meaning search was not available", async () => {
    gateway({
      "POST /api/tools/search_products": () => ({
        products: [{ ...MILK, matched_by: "words" }],
        search: "text",
        meaning_unavailable: true,
      }),
    });
    const found = await createHttpApi("/api").searchProducts("dairy-free drink", { byMeaning: true });
    expect(found.meaningUnavailable).toBe(true);
    expect(found.map((product) => product.matchedBy)).toEqual(["words"]);
  });

  it("skips a row that does not map and keeps the rest", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    gateway({ "POST /api/tools/search_products": () => ({ products: [{ names: {} }, MILK], search: "text" }) });
    expect((await createHttpApi("/api").searchProducts("milk")).map((product) => product.id)).toEqual(["463335"]);
  });
});

describe("Products by code on the real gateway", () => {
  it("asks the catalog route for the codes and keeps the gateway's order", async () => {
    const calls = gateway({
      [`GET ${K}/catalog/products?ids=400001,463335`]: () => ({ products: [UNKNOWN, MILK] }),
    });
    const found = await createHttpApi("/api").getProducts(["400001", "463335"]);
    expect(calls.map((call) => call.route)).toEqual([`GET ${K}/catalog/products?ids=400001,463335`]);
    expect(found.map((product) => product.id)).toEqual(["400001", "463335"]);
  });

  // #1263: no sample rows any more. A 404 with no `error` envelope (a proxy mis-route) is an error.
  it("fails on a 404 with no error envelope, never answers with sample products", async () => {
    // FastAPI's own 404, no `error` envelope.
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 }));
    await expect(createHttpApi("/api").getProducts([products.arlaUht1l.id])).rejects.toMatchObject({
      code: "GATEWAY_ERROR",
      status: 404,
    });
  });

  it("fails when the gateway cannot be reached, never answers with sample products", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(createHttpApi("/api").getProducts([products.arlaUht1l.id])).rejects.toMatchObject({
      code: "NETWORK",
    });
  });

  it("still fails on a 404 the gateway names (the route is served)", async () => {
    gateway({});
    await expect(createHttpApi("/api").getProducts(["463335"])).rejects.toMatchObject({ code: "NO_ROUTE" });
  });

  it("does not call the gateway for no codes", async () => {
    const calls = gateway({});
    expect(await createHttpApi("/api").getProducts([])).toEqual([]);
    expect(calls).toEqual([]);
  });

  it("asks in groups of 200, the route's limit, and drops repeated codes", async () => {
    const ids = Array.from({ length: 250 }, (_, index) => String(500000 + index));
    const calls = gateway({});
    vi.stubGlobal("fetch", async (url: string) => {
      const asked = decodeURIComponent(url.split("ids=")[1]).split(",");
      calls.push({ route: `GET ${url}`, body: {} });
      return new Response(JSON.stringify({ products: asked.map((code) => ({ ...MILK, product_id: code })) }));
    });
    const found = await createHttpApi("/api").getProducts([...ids, ids[0]]);
    expect(calls).toHaveLength(2);
    expect(found.map((product) => product.id)).toEqual(ids);
  });
});

describe("mapCatalogProduct", () => {
  it("maps a full row to the web Product", () => {
    expect(mapCatalogProduct(MILK)).toEqual({
      id: "463335",
      names: { en: "Valio lactose free semi-skimmed milk drink 1 l", fi: "Valio laktoositon kevytmaitojuoma 1 l" },
      brand: "Valio",
      vendorName: "Valio Oy",
      category: "01010",
      salesUnit: "KI",
      baseUnit: "L",
      baseUnitsPerSalesUnit: 12,
      units: [
        { unitId: "ST", sizeInBaseUnits: 1 },
        { unitId: "KI", sizeInBaseUnits: 12 },
      ],
      fatPercent: null,
      temperature: { code: 3, label: "Chilled, +2 to +6 °C" },
      allergens: [
        { code: "AM", name: "Milk", presence: "CONTAINS" },
        { code: "AW", name: "Gluten", presence: "MAY_CONTAIN" },
      ],
      labels: ["GOODS_FROM_FINLAND_BLUE_SWAN"],
      co2KgPerKg: 1.2,
      deliveryReliability: 0.97,
    });
  });

  it("keeps unknown as null: allergen data unknown is null, never an empty list", () => {
    const product = mapCatalogProduct(UNKNOWN);
    expect(product.allergens).toBeNull();
    expect(product.temperature).toBeNull();
    expect(product.baseUnitsPerSalesUnit).toBeNull();
    expect(product.co2KgPerKg).toBeNull();
    expect(product.deliveryReliability).toBeNull();
    expect(product.names).toEqual({ en: "Kaurajuoma", fi: "Kaurajuoma" });
    expect(product.brand).toBe("");
    expect(product.vendorName).toBe("");
  });

  it("maps known allergen data with nothing listed to an empty list (known: none declared)", () => {
    const product = mapCatalogProduct({
      ...MILK,
      allergens: { contains: [], may_contain: [], undeclared: [] },
      no_declarable_allergens: true,
    });
    expect(product.allergens).toEqual([]);
  });

  it("keeps a temperature without a range or a code", () => {
    expect(
      mapCatalogProduct({ ...MILK, temperature: "frozen", temperature_condition: null, min_temperature_c: null })
        .temperature,
    ).toEqual({ code: 0, label: "Frozen" });
  });

  it("refuses a row without a product code", () => {
    expect(() => mapCatalogProduct({ ...MILK, product_id: undefined })).toThrow();
  });
});
