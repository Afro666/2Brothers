import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import type { KitchenSettings } from "@/types";

const K = "/api/v1/kitchens/demo-kitchen";
type Handler = (body: Record<string, unknown>) => unknown;
interface Call {
  route: string;
  headers: Record<string, string>;
  body: Record<string, unknown>;
}

/** A fake gateway: `"POST /path"` -> the JSON it answers. Returns the calls it received. */
function gateway(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    const route = `${init.method ?? "GET"} ${url}`;
    const body = init.body ? JSON.parse(init.body as string) : {};
    calls.push({ route, headers: init.headers as Record<string, string>, body });
    const answer = routes[route]
      ? routes[route](body)
      : new Response(JSON.stringify({ error: { code: "NO_ROUTE", message: route } }), { status: 404 });
    return answer instanceof Response ? answer : new Response(JSON.stringify(answer));
  });
  return calls;
}

const routesOf = (calls: Call[]) => calls.map((call) => call.route);

const supplierRow = {
  supplier_id: "sup-bakery",
  name: "Bakery",
  adapter: "manual",
  terms: {
    free_delivery_threshold_eur: "80",
    delivery_fee_eur: null,
    order_days: ["MON"],
    cutoff_time: "14:00",
    lead_time_days: 2,
    discount_tiers: [],
  },
};
const supplier = {
  name: "Bakery",
  adapter: "manual" as const,
  freeDeliveryThresholdEur: 80,
  deliveryFeeEur: null,
  orderDays: [1],
  cutoffTime: "14:00",
  leadTimeDays: 2,
};
const productRow = {
  product_id: "own-1",
  name: "Rye bread",
  supplier_id: "sup-bakery",
  unit: "PCS",
  base_unit: "KG",
  pack_size_in_base_units: "0.5",
  unit_price_eur: "4.20",
  allergens: [{ code: "AW", level: "CONTAINS" }],
  allergen_data: "ENTERED",
};
const recipeRow = {
  recipe_id: "rec-1",
  name: "Soup",
  portions: 1,
  ingredients: [{ product_id: "own-1", qty_per_portion: "0.1", unit: "PCS", yield_pct: "90" }],
};
const stockBody = {
  as_of: "2026-11-14T10:00:00+02:00",
  items: [{ product_id: "own-1", unit: "PCS", on_hand: "3", counted_at: null, on_order: "0", on_order_known: false }],
};
const settingsRow = {
  service_level: { A: "0.975" },
  stockout_cap: 1.8,
  budget_warning_order_eur: "1500",
  excluded_allergens: null,
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.useRealTimers();
});

describe("planning methods of createHttpApi", () => {
  it("marks every planning method as live", () => {
    const live = createHttpApi("/api").live!;
    for (const method of [
      "listSuppliers",
      "saveSupplier",
      "deleteSupplier",
      "listOwnProducts",
      "saveOwnProduct",
      "deleteOwnProduct",
      "listRecipes",
      "saveRecipe",
      "deleteRecipe",
      "getMenuPlan",
      "saveMenuPlan",
      "getStock",
      "submitStockCount",
      "getDemand",
      "getSharing",
      "setSharing",
      "getSupplierDemand",
      "getKitchenSettings",
      "saveKitchenSettings",
      "getAutoApproveLearning",
    ] as const) {
      expect(live.has(method), method).toBe(true);
    }
  });

  it("lists, creates, replaces and deletes suppliers", async () => {
    const calls = gateway({
      [`GET ${K}/suppliers`]: () => ({ suppliers: [supplierRow] }),
      [`POST ${K}/suppliers`]: () => supplierRow,
      [`PUT ${K}/suppliers/sup%2Fbakery`]: () => ({ ...supplierRow, supplier_id: "sup/bakery" }),
      [`DELETE ${K}/suppliers/sup-bakery`]: () => ({ deleted: true }),
    });
    const api = createHttpApi("/api");
    expect(await api.listSuppliers()).toEqual([{ id: "sup-bakery", ...supplier }]);
    expect((await api.saveSupplier(supplier)).id).toBe("sup-bakery");
    expect((await api.saveSupplier({ ...supplier, id: "sup/bakery" })).id).toBe("sup/bakery");
    await expect(api.deleteSupplier("sup-bakery")).resolves.toBeUndefined();
    expect(routesOf(calls)).toEqual([
      `GET ${K}/suppliers`,
      `POST ${K}/suppliers`,
      `PUT ${K}/suppliers/sup%2Fbakery`,
      `DELETE ${K}/suppliers/sup-bakery`,
    ]);
    const terms = {
      free_delivery_threshold_eur: "80",
      delivery_fee_eur: null,
      order_days: ["MON"],
      cutoff_time: "14:00",
      lead_time_days: 2,
    };
    expect(calls[1].body).toEqual({ name: "Bakery", adapter: "manual", terms });
    expect(calls[2].body).toEqual({ name: "Bakery", adapter: "manual", terms });
    expect(calls.every((call) => !("Authorization" in call.headers))).toBe(true);
  });

  it("passes the gateway's refusal on", async () => {
    gateway({
      [`DELETE ${K}/suppliers/gone`]: () =>
        new Response(JSON.stringify({ error: { code: "NOT_FOUND", message: "no such entry in suppliers" } }), {
          status: 404,
        }),
    });
    await expect(createHttpApi("/api").deleteSupplier("gone")).rejects.toMatchObject({
      code: "NOT_FOUND",
      message: "no such entry in suppliers",
    });
  });

  it("lists, creates, replaces and deletes own products", async () => {
    const calls = gateway({
      [`GET ${K}/products`]: () => ({ products: [productRow] }),
      [`GET ${K}/products/own-1`]: () => productRow,
      [`POST ${K}/products`]: () => productRow,
      [`PUT ${K}/products/own-1`]: () => ({ ...productRow, name: "Rye loaf" }),
      [`DELETE ${K}/products/own-1`]: () => ({ deleted: true }),
    });
    const api = createHttpApi("/api");
    const [product] = await api.listOwnProducts();
    expect(product).toMatchObject({ id: "own-1", unit: "PCS", packSize: 0.5, priceEur: 4.2 });
    const { id: _id, ...draft } = product;
    await api.saveOwnProduct({ ...draft, unit: "KG", packSize: 2, allergens: null });
    expect((await api.saveOwnProduct({ ...product, name: "Rye loaf" })).name).toBe("Rye loaf");
    await api.deleteOwnProduct("own-1");
    expect(routesOf(calls)).toEqual([
      `GET ${K}/products`,
      `POST ${K}/products`,
      `GET ${K}/products/own-1`,
      `PUT ${K}/products/own-1`,
      `DELETE ${K}/products/own-1`,
    ]);
    expect(calls[1].body).toEqual({
      name: "Rye bread",
      supplier_id: "sup-bakery",
      unit: "KG",
      unit_price_eur: "4.2",
      allergen_data: "UNKNOWN",
      allergens: [],
      base_unit: "KG",
      pack_size_in_base_units: "2",
    });
    // The pack size did not change: it is not sent, so the gateway keeps its KG measure.
    expect(calls[3].body).toEqual({
      name: "Rye loaf",
      supplier_id: "sup-bakery",
      unit: "PCS",
      unit_price_eur: "4.2",
      allergen_data: "ENTERED",
      allergens: [{ code: "AW", level: "CONTAINS" }],
    });
  });

  it("lists, creates, replaces and deletes recipes", async () => {
    const calls = gateway({
      [`GET ${K}/recipes`]: () => ({ recipes: [recipeRow] }),
      [`GET ${K}/recipes/rec-1`]: () => recipeRow,
      [`POST ${K}/recipes`]: () => recipeRow,
      [`PUT ${K}/recipes/rec-1`]: () => recipeRow,
      [`DELETE ${K}/recipes/rec-1`]: () => ({ deleted: true }),
    });
    const api = createHttpApi("/api");
    const [recipe] = await api.listRecipes();
    expect(recipe).toEqual({
      id: "rec-1",
      name: "Soup",
      items: [{ productId: "own-1", productName: "own-1", unit: "PCS", qtyPerPortion: 0.1 }],
    });
    await api.saveRecipe({ name: "Soup", items: recipe.items });
    await api.saveRecipe(recipe);
    await api.deleteRecipe("rec-1");
    expect(routesOf(calls)).toEqual([
      `GET ${K}/recipes`,
      `POST ${K}/recipes`,
      `GET ${K}/recipes/rec-1`,
      `PUT ${K}/recipes/rec-1`,
      `DELETE ${K}/recipes/rec-1`,
    ]);
    expect(calls[1].body).toEqual({
      name: "Soup",
      ingredients: [{ product_id: "own-1", qty_per_portion: "0.1", unit: "PCS" }],
    });
    // The stored yield goes back with the ingredient: the form does not have it.
    expect(calls[3].body).toEqual({
      name: "Soup",
      ingredients: [{ product_id: "own-1", qty_per_portion: "0.1", unit: "PCS", yield_pct: "90" }],
    });
  });

  it("reads and replaces the menu plan of one week", async () => {
    const days = [{ date: "2026-11-16", meal: "lunch", recipe_id: "rec-1", covers: 160 }];
    const calls = gateway({
      [`GET ${K}/menu-plans/2026-W47`]: () => ({ kitchen_id: "demo-kitchen", week: "2026-W47", days }),
      [`PUT ${K}/menu-plans/2026-W47`]: (body) => ({ kitchen_id: "demo-kitchen", week: "2026-W47", days: body.days }),
    });
    const api = createHttpApi("/api");
    const entries = await api.getMenuPlan("2026-W47");
    expect(entries).toEqual([
      { id: "2026-11-16:lunch:0", date: "2026-11-16", meal: "Lunch", recipeId: "rec-1", covers: 160 },
    ]);
    const saved = await api.saveMenuPlan("2026-W47", [
      ...entries,
      { date: "2026-11-17", meal: "Dinner", recipeId: "rec-1", covers: 40 },
    ]);
    expect(saved.map((entry) => entry.meal)).toEqual(["Lunch", "Dinner"]);
    expect(calls[1].route).toBe(`PUT ${K}/menu-plans/2026-W47`);
    expect(calls[1].body).toEqual({
      days: [...days, { date: "2026-11-17", meal: "dinner", recipe_id: "rec-1", covers: 40 }],
    });
  });

  it("reads the stock and submits a count with a key, a time with a zone, the source and the units", async () => {
    vi.useFakeTimers({ now: new Date("2026-11-14T08:00:00Z") });
    const calls = gateway({
      [`GET ${K}/stock`]: () => stockBody,
      [`POST ${K}/stock-counts`]: () => ({ stock_count_id: "demo-kitchen:k", stored: 1 }),
    });
    const api = createHttpApi("/api");
    expect(await api.getStock()).toEqual([
      {
        productId: "own-1",
        productName: "own-1",
        unit: "PCS",
        onHand: 3,
        onOrder: null,
        countedAt: null,
        lastDelivery: null,
      },
    ]);
    expect(await api.submitStockCount([{ productId: "own-1", onHand: null }], "chef")).toHaveLength(1);
    const post = calls.find((call) => call.route === `POST ${K}/stock-counts`)!;
    expect(post.body).toEqual({
      idempotency_key: expect.stringMatching(/^[0-9a-f]{32}$/),
      counted_at: "2026-11-14T08:00:00.000Z",
      source: "manual",
      counts: [{ product_id: "own-1", unit: "PCS", on_hand: null }],
    });
    expect(post.headers).toMatchObject({ "X-User": "chef" });
    expect(routesOf(calls)).toEqual([`GET ${K}/stock`, `GET ${K}/stock`, `POST ${K}/stock-counts`, `GET ${K}/stock`]);
  });

  it("retries a failed count with the same key, and a later count with a new one", async () => {
    let fail = true;
    const calls = gateway({
      [`GET ${K}/stock`]: () => stockBody,
      [`POST ${K}/stock-counts`]: () => {
        if (!fail) return { stock_count_id: "demo-kitchen:k", stored: 1 };
        fail = false;
        return new Response(JSON.stringify({ error: { code: "UNAVAILABLE", message: "try again" } }), { status: 503 });
      },
    });
    const api = createHttpApi("/api");
    const counts = [{ productId: "own-1", onHand: 5 }];
    await expect(api.submitStockCount(counts, "human")).rejects.toMatchObject({ code: "UNAVAILABLE" });
    await api.submitStockCount(counts, "human");
    await api.submitStockCount(counts, "human");
    const keys = calls.filter((call) => call.route.startsWith("POST")).map((call) => call.body.idempotency_key);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
  });

  it("reads the demand of a date window", async () => {
    const calls = gateway({
      [`GET ${K}/demand?from=2026-11-16&to=2026-11-22`]: () => ({
        from: "2026-11-16",
        to: "2026-11-22",
        rows: [
          { product_id: "own-1", date: "2026-11-16", unit: "PCS", gross_need: "16", why: "160 x 0.1 PCS (Soup)" },
        ],
        problems: [],
      }),
    });
    const lines = await createHttpApi("/api").getDemand("2026-11-16", "2026-11-22");
    expect(lines).toEqual([
      {
        productId: "own-1",
        productName: "own-1",
        unit: "PCS",
        date: "2026-11-16",
        need: 16,
        why: "160 x 0.1 PCS (Soup)",
      },
    ]);
    expect(calls).toHaveLength(1);
  });

  it("reads and changes forecast sharing as the person", async () => {
    const calls = gateway({
      [`GET ${K}/sharing`]: () => ({ sharing: [] }),
      [`PUT ${K}/sharing`]: () => ({
        sharing: [{ supplier_id: "sup-valio", share_forecast: true, revoked_at: null }],
      }),
    });
    const api = createHttpApi("/api");
    expect(await api.getSharing()).toEqual([]);
    expect(await api.setSharing("sup-valio", true, "human")).toEqual([{ supplierId: "sup-valio", shared: true }]);
    expect(calls[1].body).toEqual({ supplier_id: "sup-valio", share_forecast: true });
    expect(calls[1].headers).toMatchObject({ "X-User": "human" });
  });

  it("reads the supplier demand view of the supplier VITE_GATEWAY_SUPPLIER_ID names", async () => {
    vi.stubEnv("VITE_GATEWAY_SUPPLIER_ID", "sup/dairy");
    const calls = gateway({
      "GET /api/v1/suppliers/sup%2Fdairy/demand?from=2026-11-16&to=2026-11-22": () => ({
        supplier_id: "sup/dairy",
        kitchens_sharing: 0,
        rows: [],
      }),
    });
    expect(await createHttpApi("/api").getSupplierDemand("2026-11-16", "2026-11-22")).toEqual([]);
    expect(calls).toHaveLength(1);
  });

  it("reads the supplier demand view of sup-valio by default", async () => {
    vi.stubEnv("VITE_GATEWAY_SUPPLIER_ID", "");
    const calls = gateway({
      "GET /api/v1/suppliers/sup-valio/demand?from=2026-11-16&to=2026-11-22": () => ({
        supplier_id: "sup-valio",
        kitchens_sharing: 1,
        rows: [
          {
            product_id: "462775",
            product_name: "Milk",
            date: "2026-11-16",
            unit: "L",
            demand: "120",
            kitchens: 1,
            by_kitchen: [{ kitchen_id: "K01", kitchen_name: "Hotel Kuusi", demand: "120" }],
            available: null,
            shortage: null,
            risk: "UNKNOWN",
            suggested_buy: null,
          },
        ],
      }),
    });
    const [row] = await createHttpApi("/api").getSupplierDemand("2026-11-16", "2026-11-22");
    expect(row).toMatchObject({ productName: "Milk", forecastDemand: 120, available: null, risk: "UNKNOWN" });
    expect(calls).toHaveLength(1);
  });

  it("reads the settings and saves only what changed, decimals as strings", async () => {
    const calls = gateway({
      [`GET ${K}/settings`]: () => settingsRow,
      [`PUT ${K}/settings`]: () => ({ ...settingsRow, service_level: { A: "0.98" }, budget_warning_order_eur: null }),
    });
    const api = createHttpApi("/api");
    const settings = await api.getKitchenSettings();
    expect(settings.serviceLevelPercent.A).toBe(97.5);
    expect(settings.serviceLevelPercent.B).toBeNaN();
    const next: KitchenSettings = {
      ...settings,
      serviceLevelPercent: { ...settings.serviceLevelPercent, A: 98 },
      budgetWarningPerOrderExVat: null,
    };
    const saved = await api.saveKitchenSettings(next, "human");
    expect(saved.serviceLevelPercent.A).toBe(98);
    expect(saved.budgetWarningPerOrderExVat).toBeNull();
    expect(routesOf(calls)).toEqual([`GET ${K}/settings`, `GET ${K}/settings`, `PUT ${K}/settings`]);
    // Not sent: the levels nobody set, and the allergen policy the gateway calls unknown.
    expect(calls[2].body).toEqual({ service_level: { A: "0.98" }, budget_warning_order_eur: null });
    expect(calls[2].headers).toMatchObject({ "X-User": "human" });
  });

  it("sends no settings request when nothing changed", async () => {
    const calls = gateway({ [`GET ${K}/settings`]: () => settingsRow });
    const api = createHttpApi("/api");
    const settings = await api.getKitchenSettings();
    expect(await api.saveKitchenSettings(settings, "human")).toEqual(settings);
    expect(calls.every((call) => call.route === `GET ${K}/settings`)).toBe(true);
  });

  it("reads the auto-approve learning progress", async () => {
    const calls = gateway({
      [`GET ${K}/auto-approve`]: () => ({
        enabled: false,
        limit_eur: null,
        learning: {
          weeks: 2,
          weeks_needed: 4,
          decisions: 8,
          decisions_needed: 20,
          edit_rate: 0.125,
          max_edit_rate: 0.1,
          learning_done: false,
        },
      }),
    });
    expect(await createHttpApi("/api").getAutoApproveLearning()).toEqual({
      weeks: 2,
      weeksNeeded: 4,
      decisions: 8,
      decisionsNeeded: 20,
      editRate: 0.125,
      maxEditRate: 0.1,
    });
    expect(calls).toHaveLength(1);
  });
});
