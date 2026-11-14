import { afterEach, describe, expect, it, vi } from "vitest";

import {
  decimalString,
  mapAutoApproveLearning,
  mapDemand,
  mapKitchenSettings,
  mapList,
  mapMenuPlan,
  mapOwnProduct,
  mapPlanProposal,
  mapRecipe,
  mapSharing,
  mapStock,
  mapSupplier,
  mapSupplierDemand,
  menuPlanBody,
  ownProductBody,
  planProposalBody,
  recipeBody,
  settingsBody,
  stockCountBody,
  supplierBody,
} from "@/api/map-planning";
import type { KitchenSettings } from "@/types";

afterEach(() => vi.restoreAllMocks());

describe("decimalString", () => {
  it("writes a number as a plain decimal string", () => {
    expect(decimalString(250)).toBe("250");
    expect(decimalString(0)).toBe("0");
    expect(decimalString(4.2)).toBe("4.2");
    expect(decimalString(97.5 / 100)).toBe("0.975");
    expect(decimalString(100)).toBe("100");
  });

  it("refuses what is not a number", () => {
    expect(() => decimalString(Number.NaN, "Price")).toThrow("Price must be a number.");
  });
});

describe("suppliers", () => {
  const row = {
    kitchen_id: "demo-kitchen",
    supplier_id: "sup-valio",
    name: "Valio Aimo",
    adapter: "valio_api",
    terms: {
      free_delivery_threshold_eur: "250",
      delivery_fee_eur: "29.50",
      order_days: ["MON", "WED", "SUN"],
      cutoff_time: "17:00",
      lead_time_days: 1,
      discount_tiers: [],
    },
  };

  it("maps the terms, weekdays as 1 Monday to 7 Sunday", () => {
    expect(mapSupplier(row)).toEqual({
      id: "sup-valio",
      name: "Valio Aimo",
      adapter: "valio_api",
      freeDeliveryThresholdEur: 250,
      deliveryFeeEur: 29.5,
      orderDays: [1, 3, 7],
      cutoffTime: "17:00",
      leadTimeDays: 1,
    });
  });

  it("keeps a term that is not set as null, never zero", () => {
    const bare = mapSupplier({ supplier_id: "s", name: "Fish", adapter: "csv", terms: { order_days: null } });
    expect(bare).toMatchObject({
      freeDeliveryThresholdEur: null,
      deliveryFeeEur: null,
      orderDays: null,
      cutoffTime: null,
      leadTimeDays: null,
    });
    expect(mapSupplier({ supplier_id: "s", name: "Fish", adapter: "csv" }).leadTimeDays).toBeNull();
  });

  it("refuses an adapter or a weekday it does not know", () => {
    expect(() => mapSupplier({ ...row, adapter: "fax" })).toThrow("unexpected shape");
    expect(() => mapSupplier({ ...row, terms: { order_days: ["FUNDAY"] } })).toThrow("unexpected shape");
  });

  it("writes decimals as strings and every term, null included", () => {
    expect(supplierBody(mapSupplier(row))).toEqual({
      name: "Valio Aimo",
      adapter: "valio_api",
      terms: {
        free_delivery_threshold_eur: "250",
        delivery_fee_eur: "29.5",
        order_days: ["MON", "WED", "SUN"],
        cutoff_time: "17:00",
        lead_time_days: 1,
      },
    });
    expect(
      supplierBody({
        name: "Fish",
        adapter: "csv",
        freeDeliveryThresholdEur: null,
        deliveryFeeEur: null,
        orderDays: null,
        cutoffTime: null,
        leadTimeDays: null,
      }).terms,
    ).toEqual({
      free_delivery_threshold_eur: null,
      delivery_fee_eur: null,
      order_days: null,
      cutoff_time: null,
      lead_time_days: null,
    });
  });

  it("skips a row that does not map and keeps the rest of the list", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const list = mapList({ suppliers: [row, { supplier_id: "bad" }] }, "suppliers", "supplier_id", mapSupplier);
    expect(list.map((supplier) => supplier.id)).toEqual(["sup-valio"]);
    expect(warn).toHaveBeenCalledOnce();
  });
});

describe("own products", () => {
  const row = {
    product_id: "own-1",
    kitchen_id: "demo-kitchen",
    name: "Salmon fillet",
    supplier_id: "sup-fish",
    unit: "KG",
    base_unit: "KG",
    pack_size_in_base_units: "2.5",
    unit_price_eur: "18.90",
    allergens: [
      { code: "AF", level: "CONTAINS" },
      { code: "ZZ", level: "MAY_CONTAIN" },
    ],
    allergen_data: "ENTERED",
  };
  const draft = {
    name: "Salmon fillet",
    unit: "KG",
    packSize: 2.5,
    priceEur: 18.9,
    supplierId: "sup-fish",
    allergens: [{ code: "AF", name: "Fish", presence: "CONTAINS" as const }],
  };

  it("maps the row; a code without a known name shows the code", () => {
    expect(mapOwnProduct(row)).toEqual({
      id: "own-1",
      name: "Salmon fillet",
      unit: "KG",
      packSize: 2.5,
      priceEur: 18.9,
      supplierId: "sup-fish",
      allergens: [
        { code: "AF", name: "Fish", presence: "CONTAINS" },
        { code: "ZZ", name: "ZZ", presence: "MAY_CONTAIN" },
      ],
    });
  });

  it("keeps unknown allergens, pack size and price as null", () => {
    const unknown = mapOwnProduct({
      ...row,
      allergens: [],
      allergen_data: "UNKNOWN",
      base_unit: null,
      pack_size_in_base_units: null,
      unit_price_eur: null,
    });
    expect(unknown).toMatchObject({ allergens: null, packSize: null, priceEur: null });
  });

  it("writes a new product with its pack in the product's own L or KG", () => {
    expect(ownProductBody(draft, null)).toEqual({
      name: "Salmon fillet",
      supplier_id: "sup-fish",
      unit: "KG",
      unit_price_eur: "18.9",
      allergen_data: "ENTERED",
      allergens: [{ code: "AF", level: "CONTAINS" }],
      base_unit: "KG",
      pack_size_in_base_units: "2.5",
    });
  });

  it("writes unknown allergens as UNKNOWN and an empty pack size as null", () => {
    expect(ownProductBody({ ...draft, allergens: null, packSize: null, priceEur: null }, null)).toMatchObject({
      allergen_data: "UNKNOWN",
      allergens: [],
      unit_price_eur: null,
      base_unit: null,
      pack_size_in_base_units: null,
    });
  });

  it("leaves an unchanged pack size out, so the stored measure stays", () => {
    const body = ownProductBody({ ...draft, id: "own-1", unit: "PCS" }, { ...row, unit: "PCS" });
    expect(body).not.toHaveProperty("base_unit");
    expect(body).not.toHaveProperty("pack_size_in_base_units");
  });

  it("gives a changed pack size of a piece product the stored measure", () => {
    const body = ownProductBody({ ...draft, id: "own-1", unit: "PCS", packSize: 3 }, { ...row, unit: "PCS" });
    expect(body).toMatchObject({ base_unit: "KG", pack_size_in_base_units: "3" });
  });

  it("refuses a pack size with no measure instead of guessing one", () => {
    expect(() => ownProductBody({ ...draft, unit: "PCS", packSize: 1 }, null)).toThrow("L or KG");
  });
});

describe("recipes", () => {
  const row = {
    recipe_id: "rec-1",
    name: "Salmon soup",
    portions: 10,
    ingredients: [
      { product_id: "own-1", qty_per_portion: "0.12", unit: "KG", yield_pct: "85" },
      { product_id: "462775", qty_per_portion: "0.1", unit: "L", yield_pct: null },
    ],
  };

  it("maps the ingredients; a product the gateway does not name shows its id", () => {
    expect(mapRecipe(row)).toEqual({
      id: "rec-1",
      name: "Salmon soup",
      items: [
        { productId: "own-1", productName: "own-1", unit: "KG", qtyPerPortion: 0.12 },
        { productId: "462775", productName: "462775", unit: "L", qtyPerPortion: 0.1 },
      ],
    });
  });

  it("uses a product name when the gateway sends one", () => {
    const named = { ...row, ingredients: [{ ...row.ingredients[0], product_name: "Salmon fillet" }] };
    expect(mapRecipe(named).items[0].productName).toBe("Salmon fillet");
  });

  it("writes quantities as strings and keeps the stored yield of each ingredient", () => {
    const recipe = mapRecipe(row);
    recipe.items[0].qtyPerPortion = 0.15;
    recipe.items.push({ productId: "900001", productName: "Oat drink", unit: "L", qtyPerPortion: 0.03 });
    expect(recipeBody(recipe, row)).toEqual({
      name: "Salmon soup",
      ingredients: [
        { product_id: "own-1", qty_per_portion: "0.15", unit: "KG", yield_pct: "85" },
        { product_id: "462775", qty_per_portion: "0.1", unit: "L" },
        { product_id: "900001", qty_per_portion: "0.03", unit: "L" },
      ],
    });
  });

  it("writes a new recipe without a yield", () => {
    const { id: _id, ...draft } = mapRecipe(row);
    expect((recipeBody(draft, null).ingredients as object[])[0]).toEqual({
      product_id: "own-1",
      qty_per_portion: "0.12",
      unit: "KG",
    });
  });
});

describe("menu plan", () => {
  const plan = {
    kitchen_id: "demo-kitchen",
    week: "2026-W47",
    days: [
      { date: "2026-11-16", meal: "lunch", recipe_id: "rec-1", covers: 160 },
      { date: "2026-11-16", meal: "lunch", recipe_id: "rec-2", covers: 0 },
    ],
  };

  it("maps the days, each with its own id", () => {
    const entries = mapMenuPlan(plan);
    expect(entries).toEqual([
      { id: "2026-11-16:lunch:0", date: "2026-11-16", meal: "Lunch", recipeId: "rec-1", covers: 160 },
      { id: "2026-11-16:lunch:1", date: "2026-11-16", meal: "Lunch", recipeId: "rec-2", covers: 0 },
    ]);
  });

  it("maps an empty week to no entries", () => {
    expect(mapMenuPlan({ kitchen_id: "demo-kitchen", week: "2026-W48", days: [] })).toEqual([]);
  });

  it("writes the whole week with the gateway's lower-case meals and no ids", () => {
    expect(menuPlanBody(mapMenuPlan(plan))).toEqual({ days: plan.days });
    expect(menuPlanBody([{ date: "2026-11-17", meal: " Dinner ", recipeId: "rec-1", covers: 12 }])).toEqual({
      days: [{ date: "2026-11-17", meal: "dinner", recipe_id: "rec-1", covers: 12 }],
    });
  });
});

describe("stock", () => {
  const body = {
    as_of: "2026-11-14T10:00:00+02:00",
    items: [
      {
        product_id: "462775",
        unit: "L",
        on_hand: "12.5",
        counted_at: "2026-11-13T08:00:00+00:00",
        on_order: "0",
        on_order_known: false,
        position: "12.5",
        next_delivery_date: null,
      },
      { product_id: "own-1", unit: "KG", on_hand: null, counted_at: "2026-11-13T08:00:00+00:00", on_order: "0" },
    ],
  };

  it("keeps on order unknown while the gateway cannot say, and a null count as not counted", () => {
    expect(mapStock(body)).toEqual([
      {
        productId: "462775",
        productName: "462775",
        unit: "L",
        onHand: 12.5,
        onOrder: null,
        countedAt: "2026-11-13T08:00:00+00:00",
        lastDelivery: null,
      },
      {
        productId: "own-1",
        productName: "own-1",
        unit: "KG",
        onHand: null,
        onOrder: null,
        countedAt: "2026-11-13T08:00:00+00:00",
        lastDelivery: null,
      },
    ]);
  });

  it("reads on order once the gateway says it is known", () => {
    const known = { items: [{ ...body.items[0], on_order: "4", on_order_known: true }] };
    expect(mapStock(known)[0].onOrder).toBe(4);
  });

  it("writes a count with the unit of each product, and null for not counted", () => {
    const units = new Map([
      ["462775", "L"],
      ["own-1", "KG"],
    ]);
    const counts = [
      { productId: "462775", onHand: 8 },
      { productId: "own-1", onHand: null },
    ];
    expect(stockCountBody(counts, units, "2026-11-14T08:00:00.000Z", "key-1")).toEqual({
      idempotency_key: "key-1",
      counted_at: "2026-11-14T08:00:00.000Z",
      source: "manual",
      counts: [
        { product_id: "462775", unit: "L", on_hand: "8" },
        { product_id: "own-1", unit: "KG", on_hand: null },
      ],
    });
  });

  it("refuses a count for a product with no known unit", () => {
    expect(() => stockCountBody([{ productId: "x", onHand: 1 }], new Map(), "2026-11-14T08:00:00Z", "k")).toThrow(
      "Stock product x was not found.",
    );
  });
});

describe("demand", () => {
  it("maps the gross need per product and day", () => {
    const body = {
      from: "2026-11-16",
      to: "2026-11-22",
      rows: [
        {
          product_id: "462775",
          date: "2026-11-16",
          unit: "L",
          covers: 160,
          gross_need: "16.000",
          why: "160 x 0.1 L (Salmon soup)",
          source: "menu_plan",
          net_need: null,
        },
      ],
      problems: [],
    };
    expect(mapDemand(body)).toEqual([
      {
        productId: "462775",
        productName: "462775",
        unit: "L",
        date: "2026-11-16",
        need: 16,
        why: "160 x 0.1 L (Salmon soup)",
      },
    ]);
  });
});

describe("the order for the menu plan", () => {
  const body = {
    proposal_id: "prop-plan-1",
    status: "READY",
    expected_total: "212.40",
    lines: [{ product_id: "462775" }, { product_id: "own-1" }],
    request: {
      requested_date: "2026-11-16",
      needs: [
        { product_id: "462775", quantity: "30", unit: "L", stock_counted: true },
        { product_id: "own-1", quantity: "48", unit: "PCS", stock_counted: false },
        { product_id: "own-2", quantity: "51.6", unit: "KG", stock_counted: false },
      ],
    },
    shortfalls: [{ product_id: "own-2", shortfall: "51.6", unit: "KG" }],
    mandate: { reason_codes: ["PARTIAL_STOCK", "OVER_LIMIT"] },
    excluded: [],
  };

  it("writes the window, the delivery date and the key, and no product or text", () => {
    expect(planProposalBody("2026-11-16", "2026-11-22", "2026-11-18", "key-1")).toEqual({
      from: "2026-11-16",
      to: "2026-11-22",
      requested_date: "2026-11-18",
      idempotency_key: "key-1",
    });
  });

  it("counts the lines, the needs, the uncounted products and the shortfalls", () => {
    expect(mapPlanProposal(body)).toEqual({
      id: "prop-plan-1",
      status: "READY",
      totalInclVat: 212.4,
      lineCount: 2,
      needCount: 3,
      uncountedCount: 2,
      shortfallCount: 1,
      reasonCodes: ["PARTIAL_STOCK", "OVER_LIMIT"],
    });
  });

  it("maps a refused proposal with no lines, no shortfall list and no reason codes", () => {
    const refused = { ...body, status: "REJECTED", expected_total: "0.00", lines: [], shortfalls: undefined, mandate: {} };
    expect(mapPlanProposal(refused)).toMatchObject({
      status: "REJECTED",
      totalInclVat: 0,
      lineCount: 0,
      shortfallCount: 0,
      reasonCodes: [],
    });
  });

  it("maps an auto-approved proposal", () => {
    expect(mapPlanProposal({ ...body, status: "APPROVED" })).toMatchObject({ status: "APPROVED", lineCount: 2 });
  });

  it("refuses a proposal without needs, with a total that is not a decimal string, or with an unknown status", () => {
    expect(() => mapPlanProposal({ ...body, request: {} })).toThrow(/unexpected shape/);
    expect(() => mapPlanProposal({ ...body, expected_total: 212.4 })).toThrow(/decimal string/);
    expect(() => mapPlanProposal({ ...body, status: "PLACED" })).toThrow(/unexpected shape/);
  });
});

describe("sharing", () => {
  it("is shared only when granted and not revoked", () => {
    const body = {
      sharing: [
        { supplier_id: "sup-valio", share_forecast: true, revoked_at: null },
        { supplier_id: "sup-fish", share_forecast: false, revoked_at: "2026-11-13T08:00:00+00:00" },
        { supplier_id: "sup-odd", share_forecast: true, revoked_at: "2026-11-13T08:00:00+00:00" },
      ],
    };
    expect(mapSharing(body)).toEqual([
      { supplierId: "sup-valio", shared: true },
      { supplierId: "sup-fish", shared: false },
      { supplierId: "sup-odd", shared: false },
    ]);
  });
});

describe("supplier demand", () => {
  const row = {
    product_id: "462775",
    product_name: "Lactose-free milk",
    date: "2026-11-16",
    unit: "L",
    demand: "120.5",
    kitchens: 2,
    by_kitchen: [
      { kitchen_id: "K01", kitchen_name: "Hotel Kuusi", demand: "100" },
      { kitchen_id: "K02", kitchen_name: null, demand: "20.5" },
    ],
    available: "90",
    shortage: "30.5",
    risk: "SHORT",
    suggested_buy: "31",
  };

  it("maps a row; a kitchen without a name shows its id", () => {
    expect(mapSupplierDemand({ rows: [row] })).toEqual([
      {
        productId: "462775",
        productName: "Lactose-free milk",
        unit: "L",
        date: "2026-11-16",
        forecastDemand: 120.5,
        kitchens: 2,
        byKitchen: [
          { kitchenId: "K01", kitchenName: "Hotel Kuusi", demand: 100 },
          { kitchenId: "K02", kitchenName: "K02", demand: 20.5 },
        ],
        available: 90,
        risk: "SHORT",
        suggestedBuy: 31,
      },
    ]);
  });

  it("keeps unknown availability unknown, and reads OK as covered", () => {
    const unknown = { ...row, product_name: null, available: null, shortage: null, risk: "UNKNOWN", suggested_buy: null };
    const [first, second, third] = mapSupplierDemand({
      rows: [unknown, { ...row, risk: "OK" }, { ...row, risk: "SOMETHING_NEW" }],
    });
    expect(first).toMatchObject({ productName: "462775", available: null, risk: "UNKNOWN", suggestedBuy: null });
    expect(second.risk).toBe("COVERED");
    expect(third.risk).toBe("UNKNOWN");
  });
});

describe("kitchen settings", () => {
  const stored = {
    service_level: { A: "0.975", B: "0.95", C: "0.9" },
    max_cover_days: { fresh_dairy: 5, fish: 2 },
    stockout_cap: 1.8,
    budget_warning_order_eur: "1500",
    budget_warning_week_eur: null,
    excluded_allergens: ["AP", "AN"],
  };
  const settings: KitchenSettings = {
    serviceLevelPercent: { A: 97.5, B: 95, C: 90 },
    maxDaysOfCover: [
      { category: "fresh_dairy", maxDays: 5 },
      { category: "fish", maxDays: 2 },
    ],
    stockOutDemandCap: 1.8,
    budgetWarningPerOrderExVat: 1500,
    budgetWarningPerWeekExVat: null,
    excludedAllergens: ["AP", "AN"],
  };

  it("maps fractions to percent and the cover table to rules", () => {
    expect(mapKitchenSettings(stored)).toEqual(settings);
    expect(mapKitchenSettings({ ...stored, stockout_cap: "2" }).stockOutDemandCap).toBe(2);
  });

  it("keeps what the kitchen never set as not set, never an invented default", () => {
    const empty = mapKitchenSettings({ excluded_allergens: null });
    expect(empty.serviceLevelPercent).toEqual({ A: Number.NaN, B: Number.NaN, C: Number.NaN });
    expect(empty.stockOutDemandCap).toBeNaN();
    expect(empty).toMatchObject({
      maxDaysOfCover: [],
      budgetWarningPerOrderExVat: null,
      budgetWarningPerWeekExVat: null,
      excludedAllergens: [],
    });
  });

  it("writes nothing when nothing changed, also for settings that were never set", () => {
    expect(settingsBody(settings, structuredClone(settings))).toEqual({});
    const empty = mapKitchenSettings({ excluded_allergens: null });
    expect(settingsBody(empty, structuredClone(empty))).toEqual({});
  });

  it("writes only the changed fields, decimals as strings", () => {
    const next: KitchenSettings = {
      serviceLevelPercent: { A: 98, B: 95, C: 90 },
      maxDaysOfCover: [
        { category: "fresh_dairy", maxDays: 4 },
        { category: "fish", maxDays: 2 },
        { category: " meat ", maxDays: 3 },
      ],
      stockOutDemandCap: 2,
      budgetWarningPerOrderExVat: null,
      budgetWarningPerWeekExVat: 6000.5,
      excludedAllergens: ["AN", "AP", "AS"],
    };
    expect(settingsBody(settings, next)).toEqual({
      service_level: { A: "0.98" },
      max_cover_days: { fresh_dairy: 4, meat: 3 },
      stockout_cap: "2",
      budget_warning_order_eur: null,
      budget_warning_week_eur: "6000.5",
      excluded_allergens: ["AN", "AP", "AS"],
    });
  });

  it("does not turn an unknown allergen policy into no exclusions", () => {
    const unknown = mapKitchenSettings({ ...stored, excluded_allergens: null });
    const body = settingsBody(unknown, { ...unknown, budgetWarningPerWeekExVat: 100 });
    expect(body).toEqual({ budget_warning_week_eur: "100" });
  });

  it("refuses to remove a cover rule the gateway would keep, and an emptied number", () => {
    expect(() => settingsBody(settings, { ...settings, maxDaysOfCover: [settings.maxDaysOfCover[0]] })).toThrow(
      "cannot remove a days-of-cover rule yet (fish)",
    );
    expect(() => settingsBody(settings, { ...settings, stockOutDemandCap: Number.NaN })).toThrow(
      "Stock-out demand cap must be a number.",
    );
  });
});

describe("auto-approve learning", () => {
  const body = {
    enabled: false,
    limit_eur: null,
    learning: {
      weeks: 1,
      weeks_needed: 4,
      decisions: 6,
      decisions_needed: 20,
      edit_rate: 0.333,
      max_edit_rate: 0.1,
      learning_done: false,
    },
  };

  it("maps the learning progress", () => {
    expect(mapAutoApproveLearning(body)).toEqual({
      weeks: 1,
      weeksNeeded: 4,
      decisions: 6,
      decisionsNeeded: 20,
      editRate: 0.333,
      maxEditRate: 0.1,
      enabled: false,
      limitEur: null,
      setBy: null,
    });
  });

  it("has no edit rate before the first decision, not 0 %", () => {
    const fresh = { learning: { ...body.learning, weeks: 0, decisions: 0, edit_rate: 0 } };
    expect(mapAutoApproveLearning(fresh).editRate).toBeNull();
  });
});
