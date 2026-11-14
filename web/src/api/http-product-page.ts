import { type Json, object, text } from "@/api/gateway-map";
import { mapCatalogProduct } from "@/api/http-catalog";
import type { Product } from "@/types";

/** The gateway request of api/http.ts: a path under the base URL, the parsed JSON back. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

/** Texts per language as the catalog has them (`en`, `fi`, `sv`); null when it has none. */
export type Texts = Partial<Record<"en" | "fi" | "sv", string>> | null;

export interface ProductPageAllergen {
  code: string;
  /** The gateway's name for the code; the code itself when it has none. */
  name: string;
}

export type NutrientKey = "kcal" | "protein_g" | "fat_g" | "saturated_fat_g" | "carbs_g" | "sugar_g" | "fibre_g" | "salt_g";

export interface ProductPageSupplier {
  supplierId: string;
  name: string;
  /** `valio_api` for Valio, `manual` for a supplier a person orders from by hand. */
  adapter: string | null;
  productId: string;
  productName: string | null;
  priceExVat: number | null;
  /** The unit the price is for (KG, ST, KI …). */
  per: string | null;
  priceSource: string | null;
  vatRate: number | null;
  /** False: nobody confirmed stock; a person must approve. */
  stockKnown: boolean;
  netContent: { value: number; unit: string } | null;
  /** Price per kg or litre (price / net content); null when either is unknown. */
  pricePerMeasure: number | null;
  measureUnit: string | null;
  leadTimeDays: number | null;
  leadTimeSource: string | null;
  orderDays: string[];
  cutoffTime: string | null;
  freeDeliveryThresholdEur: number | null;
  deliveryFeeEur: number | null;
}

export interface ProductPageLine {
  id: string;
  createdAt: string | null;
  quantity: number | null;
  unit: string | null;
  total: number | null;
  status?: string | null;
}

/** `GET /catalog/products/{product_id}` (docs/contract.md "Product page"). Unknown stays null. */
export interface ProductPage {
  productId: string;
  product: Product;
  /** Catalog products only: an own product has no catalog texts. */
  about: {
    marketingText: Texts;
    keyIngredients: Texts;
    ingredients: Texts[];
    storageInstructions: Texts;
    preparationInstructions: Texts;
    usageInstructions: Texts;
    producer: string | null;
    source: string;
  } | null;
  allergens: {
    /** False: unknown. Empty lists then never mean free from. */
    known: boolean;
    contains: ProductPageAllergen[];
    mayContain: ProductPageAllergen[];
    freeFrom: ProductPageAllergen[];
    noDeclarableAllergens: boolean;
    source: string | null;
  };
  /** Per 100 g or 100 ml; null when the label has no usable table. A missing nutrient is absent, not 0. */
  nutrition: { basis: string; values: Partial<Record<NutrientKey, number>>; source: string | null } | null;
  storage: { temperature: string | null; minC: number | null; maxC: number | null; source: string | null };
  origin: { country: string | null; source: string | null };
  vat: { code: string | null; rate: number | null; source: string | null };
  /** Valio's live price and stock for `date`; null for an own product. */
  live: {
    date: string | null;
    priceExVat: number | null;
    priceInclVat: number | null;
    per: string | null;
    taxRate: number | null;
    comparisonPrice: number | null;
    comparisonUnit: string | null;
    stock: {
      /** null with `unknown: true`: Valio does not say. */
      available: number | null;
      unknown: boolean;
      availableDate: string | null;
      orderable: boolean;
      cutoffPassed: boolean | null;
      closingTime: string | null;
    } | null;
    /** `SUPPLIER_BUSY` or `VALIO_UNAVAILABLE` when Valio did not answer. */
    error: string | null;
    source: string | null;
  } | null;
  recall: { status: "CLEAR" | "BLOCKED_BY_RECALL"; alerts: { eventId: string; title: string | null; match: string | null }[] };
  /** Valio first, then the same product from other suppliers, cheapest per kg or litre. */
  suppliers: ProductPageSupplier[];
  kitchen: {
    orders: ProductPageLine[];
    proposalsWaiting: ProductPageLine[];
    stock: { onHand: number | null; unit: string | null; countedAt: string | null } | null;
    recipes: { recipeId: string; name: string; qtyPerPortion: number | null; unit: string | null }[];
    demand: { from: string; to: string; unit: string | null; grossNeed: number | null; days: number; source: string | null } | null;
  };
}

/** A decimal string or number; null when unknown or not a number. */
function num(value: unknown): number | null {
  if (value == null || value === "") return null;
  const parsed = typeof value === "string" ? Number(value) : value;
  return typeof parsed === "number" && Number.isFinite(parsed) ? parsed : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function list(value: unknown): Json[] {
  return Array.isArray(value) ? value.filter((item): item is Json => !!item && typeof item === "object") : [];
}

function texts(value: unknown): Texts {
  if (!value || typeof value !== "object") return null;
  const row = value as Json;
  const out: Partial<Record<"en" | "fi" | "sv", string>> = {};
  for (const key of ["en", "fi", "sv"] as const) {
    const item = str(row[key]);
    if (item) out[key] = item;
  }
  return Object.keys(out).length ? out : null;
}

function allergens(value: unknown): ProductPageAllergen[] {
  return list(value).flatMap((row) => {
    const code = str(row.code);
    return code ? [{ code, name: str(row.name) ?? code }] : [];
  });
}

function lines(value: unknown, idKey: string): ProductPageLine[] {
  return list(value).map((row) => ({
    id: String(row[idKey] ?? ""),
    createdAt: str(row.created_at),
    quantity: num(row.quantity),
    unit: str(row.unit),
    total: num(row.total),
    status: str(row.status),
  }));
}

function supplier(row: Json): ProductPageSupplier {
  const content = row.net_content && typeof row.net_content === "object" ? (row.net_content as Json) : null;
  const value = num(content?.value);
  const netContent = value && str(content?.unit) ? { value, unit: str(content?.unit)! } : null;
  const priceExVat = num(row.price_ex_vat);
  return {
    supplierId: text(row.supplier_id, "a supplier_id"),
    name: str(row.name) ?? String(row.supplier_id),
    adapter: str(row.adapter),
    productId: String(row.product_id ?? ""),
    productName: str(row.product_name),
    priceExVat,
    per: str(row.per),
    priceSource: str(row.price_source),
    vatRate: num(row.vat_rate),
    stockKnown: row.stock_known === true,
    netContent,
    pricePerMeasure: priceExVat != null && netContent ? priceExVat / netContent.value : null,
    measureUnit: netContent?.unit ?? null,
    leadTimeDays: num(row.lead_time_days),
    leadTimeSource: str(row.lead_time_source),
    orderDays: Array.isArray(row.order_days) ? row.order_days.filter((day): day is string => typeof day === "string") : [],
    cutoffTime: str(row.cutoff_time),
    freeDeliveryThresholdEur: num(row.free_delivery_threshold_eur),
    deliveryFeeEur: num(row.delivery_fee_eur),
  };
}

/** The product page answer to the web shape. Unknown stays null; it is never 0 or "none". */
export function mapProductPage(value: unknown): ProductPage {
  const body = object(value, "a product page");
  const product = mapCatalogProduct(body.product);
  const about = body.about && typeof body.about === "object" ? (body.about as Json) : null;
  const allergenRow = object(body.allergens ?? {}, "product page allergens");
  const nutrition = body.nutrition && typeof body.nutrition === "object" ? (body.nutrition as Json) : null;
  const storage = object(body.storage ?? {}, "product page storage");
  const origin = object(body.origin ?? {}, "product page origin");
  const vat = object(body.vat ?? {}, "product page VAT");
  const live = body.live && typeof body.live === "object" ? (body.live as Json) : null;
  const stock = live?.stock && typeof live.stock === "object" ? (live.stock as Json) : null;
  const recall = object(body.recall ?? {}, "product page recall");
  const kitchen = object(body.kitchen ?? {}, "product page kitchen");
  const kitchenStock = kitchen.stock && typeof kitchen.stock === "object" ? (kitchen.stock as Json) : null;
  const demand = kitchen.demand && typeof kitchen.demand === "object" ? (kitchen.demand as Json) : null;
  const values: Partial<Record<NutrientKey, number>> = {};
  for (const [key, amount] of Object.entries((nutrition?.values as Json | undefined) ?? {})) {
    const parsed = num(amount);
    if (parsed != null) values[key as NutrientKey] = parsed;
  }
  return {
    productId: text(body.product_id, "a product_id"),
    product,
    about: about && {
      marketingText: texts(about.marketing_text),
      keyIngredients: texts(about.key_ingredients),
      ingredients: (Array.isArray(about.ingredients) ? about.ingredients : []).map(texts).filter((item) => item !== null),
      storageInstructions: texts(about.storage_instructions),
      preparationInstructions: texts(about.preparation_instructions),
      usageInstructions: texts(about.usage_instructions),
      producer: str(about.producer),
      source: str(about.source) ?? "",
    },
    allergens: {
      known: allergenRow.known === true,
      contains: allergens(allergenRow.contains),
      mayContain: allergens(allergenRow.may_contain),
      freeFrom: allergens(allergenRow.free_from),
      noDeclarableAllergens: allergenRow.no_declarable_allergens === true,
      source: str(allergenRow.source),
    },
    nutrition: nutrition && { basis: str(nutrition.basis) ?? "g", values, source: str(nutrition.source) },
    storage: {
      temperature: str(storage.temperature),
      minC: num(storage.min_temperature_c),
      maxC: num(storage.max_temperature_c),
      source: str(storage.source),
    },
    origin: { country: str(origin.country), source: str(origin.source) },
    vat: { code: str(vat.code), rate: num(vat.rate), source: str(vat.source) },
    live: live && {
      date: str(live.date),
      priceExVat: num(live.price_ex_vat),
      priceInclVat: num(live.price_incl_vat),
      per: str(live.per),
      taxRate: num(live.tax_rate),
      comparisonPrice: num(live.comparison_price),
      comparisonUnit: str(live.comparison_unit),
      stock: stock && {
        available: stock.unknown === true ? null : num(stock.available),
        unknown: stock.unknown === true,
        availableDate: str(stock.available_date),
        orderable: stock.orderable === true,
        cutoffPassed: typeof stock.cutoff_passed === "boolean" ? stock.cutoff_passed : null,
        closingTime: str(stock.closing_time),
      },
      error: str(live.error),
      source: str(live.source),
    },
    recall: {
      status: recall.status === "BLOCKED_BY_RECALL" ? "BLOCKED_BY_RECALL" : "CLEAR",
      alerts: list(recall.alerts).map((row) => ({ eventId: String(row.event_id ?? ""), title: str(row.title), match: str(row.match) })),
    },
    suppliers: list(body.suppliers).map(supplier),
    kitchen: {
      orders: lines(kitchen.orders, "order_id"),
      proposalsWaiting: lines(kitchen.proposals_waiting, "proposal_id"),
      stock: kitchenStock && { onHand: num(kitchenStock.on_hand), unit: str(kitchenStock.unit), countedAt: str(kitchenStock.counted_at) },
      recipes: list(kitchen.recipes).map((row) => ({
        recipeId: String(row.recipe_id ?? ""),
        name: str(row.name) ?? String(row.recipe_id ?? ""),
        qtyPerPortion: num(row.qty_per_portion),
        unit: str(row.unit),
      })),
      demand: demand && {
        from: str(demand.from) ?? "",
        to: str(demand.to) ?? "",
        unit: str(demand.unit),
        grossNeed: num(demand.gross_need),
        days: num(demand.days) ?? 0,
        source: str(demand.source),
      },
    },
  };
}

/** One product's page on the gateway. A 404 is `PRODUCT_NOT_FOUND`, passed on as an error. */
export function createProductPageHttp(call: GatewayCall, kitchen: string) {
  return {
    async getProductPage(productId: string, date?: string): Promise<ProductPage> {
      const query = date ? `?date=${encodeURIComponent(date)}` : "";
      return mapProductPage(await call(`${kitchen}/catalog/products/${encodeURIComponent(productId)}${query}`));
    },
  };
}
