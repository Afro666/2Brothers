import { type Json, decimal, object, rows, text } from "@/api/gateway-map";
import { mapMoney } from "@/api/map";
import { ApiError, type Draft, type StockCount } from "@/api/types";
import type {
  Allergen,
  AutoApproveLearning,
  DemandClass,
  DemandLine,
  KitchenSettings,
  MenuPlanEntry,
  OwnProduct,
  PlanProposal,
  Recipe,
  SharingConsent,
  ShortageRisk,
  StockItem,
  Supplier,
  SupplierAdapter,
  SupplierDemandRow,
} from "@/types";

/**
 * The kitchen planning routes (gateway/kitchen_routes.py, gateway/supplier_routes.py,
 * gateway/autoapprove.py) to the UI types, and the UI types back to request bodies.
 *
 * The gateway sends snake_case, decimals as strings and null for unknown. What it does not
 * send stays unknown here (null, or NaN for a settings number, which the settings form shows
 * as an empty field); it is never filled with zero or a guess. A product the gateway names
 * by its id only shows that id as its name.
 */

function invalid(what: string): never {
  throw new ApiError("INVALID_RESPONSE", `The gateway sent ${what} in an unexpected shape.`);
}

/** A JSON number (a count, a factor). Money and quantities are decimal strings: see `decimal`. */
function number(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) invalid(what);
  return value;
}

function list(value: unknown, what: string): unknown[] {
  if (!Array.isArray(value)) invalid(what);
  return value;
}

/** The name the gateway sent, or the id when it sent none. */
function nameOr(id: string, name: unknown): string {
  return typeof name === "string" && name ? name : id;
}

/**
 * A number as the decimal string the gateway reads; it refuses a binary float.
 * At most 6 decimals, so `97.5 / 100` goes out as "0.975".
 */
export function decimalString(value: number, label = "amount"): string {
  if (!Number.isFinite(value)) throw new ApiError("INVALID", `${label} must be a number.`);
  return value.toFixed(6).replace(/\.?0+$/, "");
}

const optionalDecimal = (value: number | null, label: string) => (value == null ? null : decimalString(value, label));

/** Maps each row on its own: a row that does not map is logged and skipped, not fatal for the list. */
export function mapList<T>(body: unknown, key: string, idKey: string, map: (row: unknown) => T): T[] {
  return rows(body, key).flatMap((row) => {
    try {
      return [map(row)];
    } catch (error) {
      console.warn(`Skipped a row of ${key}, ${String(row[idKey] ?? "(no id)")}:`, error);
      return [];
    }
  });
}

// ---- suppliers ------------------------------------------------------------------------

const WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
const ADAPTERS: readonly string[] = ["valio_api", "manual", "csv"] satisfies SupplierAdapter[];

/** One supplier row. A term that is not set is null, never a default. */
export function mapSupplier(body: unknown): Supplier {
  const row = object(body, "a supplier");
  const terms = row.terms == null ? {} : object(row.terms, "supplier terms");
  if (typeof row.adapter !== "string" || !ADAPTERS.includes(row.adapter)) invalid("a supplier adapter");
  return {
    id: text(row.supplier_id, "a supplier_id"),
    name: text(row.name, "a supplier name"),
    adapter: row.adapter as SupplierAdapter,
    freeDeliveryThresholdEur: decimal(terms.free_delivery_threshold_eur, "free_delivery_threshold_eur"),
    deliveryFeeEur: decimal(terms.delivery_fee_eur, "delivery_fee_eur"),
    orderDays:
      terms.order_days == null
        ? null
        : list(terms.order_days, "order_days").map((day) => {
            const index = WEEKDAYS.indexOf(day as string);
            if (index < 0) invalid("an order day");
            return index + 1;
          }),
    cutoffTime: terms.cutoff_time == null ? null : text(terms.cutoff_time, "cutoff_time"),
    leadTimeDays: terms.lead_time_days == null ? null : number(terms.lead_time_days, "lead_time_days"),
  };
}

/**
 * The body of `POST /suppliers` and `PUT /suppliers/{id}`. Every term the form has goes out,
 * null included, so clearing a term clears it. `discount_tiers` is left out: the gateway keeps
 * the stored ones.
 */
export function supplierBody(supplier: Draft<Supplier>): Json {
  return {
    name: supplier.name,
    adapter: supplier.adapter,
    terms: {
      free_delivery_threshold_eur: optionalDecimal(supplier.freeDeliveryThresholdEur, "Free delivery threshold"),
      delivery_fee_eur: optionalDecimal(supplier.deliveryFeeEur, "Delivery fee"),
      order_days:
        supplier.orderDays == null
          ? null
          : supplier.orderDays.map((day) => {
              const name = WEEKDAYS[day - 1];
              if (!name) throw new ApiError("INVALID", "An order day must be a weekday from 1 to 7.");
              return name;
            }),
      cutoff_time: supplier.cutoffTime,
      lead_time_days: supplier.leadTimeDays,
    },
  };
}

// ---- own products ---------------------------------------------------------------------

/** The gateway sends an allergen as its GS1 code only; these are the codes the product form offers. */
const ALLERGEN_NAMES: Record<string, string> = {
  AM: "Milk",
  AW: "Gluten cereals",
  AE: "Egg",
  AF: "Fish",
  AN: "Tree nuts",
  AP: "Peanuts",
  AS: "Sesame",
  AY: "Soy",
};

/** One own product. `allergen_data: "UNKNOWN"` is null (unknown), not an empty list. */
export function mapOwnProduct(body: unknown): OwnProduct {
  const row = object(body, "an own product");
  const allergens =
    row.allergen_data === "ENTERED"
      ? list(row.allergens, "own product allergens").map((item): Allergen => {
          const allergen = object(item, "an allergen");
          const code = text(allergen.code, "an allergen code");
          if (allergen.level !== "CONTAINS" && allergen.level !== "MAY_CONTAIN") invalid("an allergen level");
          return { code, name: ALLERGEN_NAMES[code] ?? code, presence: allergen.level };
        })
      : null;
  return {
    id: text(row.product_id, "a product_id"),
    name: text(row.name, "a product name"),
    unit: text(row.unit, "a product unit"),
    // The measure (`base_unit`: L or KG) has no place in the UI type yet.
    packSize: decimal(row.pack_size_in_base_units, "pack_size_in_base_units"),
    priceEur: decimal(row.unit_price_eur, "unit_price_eur"),
    supplierId: text(row.supplier_id, "a supplier_id"),
    allergens,
  };
}

/**
 * The body of `POST /products` and `PUT /products/{id}`. `stored` is the gateway's row on an
 * update, null on a create.
 *
 * The gateway keeps a pack size only with its measure (`base_unit`: L or KG), and the form has
 * the number alone. An unchanged pack size is left out, so the stored one stays. A new number
 * takes the product's unit when that is L or KG, else the stored measure; with neither the
 * save is refused, because a measure would be a guess.
 */
export function ownProductBody(product: Draft<OwnProduct>, stored: Json | null): Json {
  const body: Json = {
    name: product.name,
    supplier_id: product.supplierId,
    unit: product.unit,
    unit_price_eur: optionalDecimal(product.priceEur, "Price"),
    allergen_data: product.allergens == null ? "UNKNOWN" : "ENTERED",
    allergens: (product.allergens ?? []).map((allergen) => ({ code: allergen.code, level: allergen.presence })),
  };
  if (product.packSize == null) return { ...body, base_unit: null, pack_size_in_base_units: null };
  if (stored && decimal(stored.pack_size_in_base_units, "pack_size_in_base_units") === product.packSize) return body;
  const measure = product.unit === "L" || product.unit === "KG" ? product.unit : stored?.base_unit;
  if (measure !== "L" && measure !== "KG") {
    throw new ApiError(
      "INVALID",
      "The gateway keeps a pack size in L or KG only. Use L or KG as the unit, or leave the pack size empty.",
    );
  }
  return { ...body, base_unit: measure, pack_size_in_base_units: decimalString(product.packSize, "Pack size") };
}

// ---- recipes --------------------------------------------------------------------------

/** One recipe. The gateway names an ingredient by its product id only. */
export function mapRecipe(body: unknown): Recipe {
  const row = object(body, "a recipe");
  return {
    id: text(row.recipe_id, "a recipe_id"),
    name: text(row.name, "a recipe name"),
    items: list(row.ingredients ?? [], "recipe ingredients").map((item) => {
      const ingredient = object(item, "a recipe ingredient");
      const productId = text(ingredient.product_id, "an ingredient product_id");
      return {
        productId,
        productName: nameOr(productId, ingredient.product_name),
        unit: text(ingredient.unit, "an ingredient unit"),
        qtyPerPortion: mapMoney(ingredient.qty_per_portion, "qty_per_portion"),
      };
    }),
  };
}

/**
 * The body of `POST /recipes` and `PUT /recipes/{id}`. `stored` is the gateway's row on an
 * update, null on a create. The form has no yield, and a PUT replaces the ingredient list, so
 * each ingredient keeps the `yield_pct` it has at the gateway. `portions` is left out: the
 * gateway keeps the stored one.
 */
export function recipeBody(recipe: Draft<Recipe>, stored: Json | null): Json {
  const before = (Array.isArray(stored?.ingredients) ? stored.ingredients : []) as Json[];
  return {
    name: recipe.name,
    ingredients: recipe.items.map((item) => {
      const same = before.find((row) => row?.product_id === item.productId && row.unit === item.unit);
      return {
        product_id: item.productId,
        qty_per_portion: decimalString(item.qtyPerPortion, "Quantity per portion"),
        unit: item.unit,
        ...(same?.yield_pct != null ? { yield_pct: same.yield_pct } : {}),
      };
    }),
  };
}

// ---- menu plan ------------------------------------------------------------------------

/**
 * `GET/PUT /menu-plans/{week}`. The gateway keeps no id per entry, so the id is the entry's
 * place in the week. Its meals are lower case (`lunch`); the planner writes them as a name.
 */
export function mapMenuPlan(body: unknown): MenuPlanEntry[] {
  return rows(body, "days").map((day, index) => {
    const meal = text(day.meal, "a menu meal");
    return {
      id: `${text(day.date, "a menu date")}:${meal}:${index}`,
      date: day.date as string,
      meal: meal.charAt(0).toUpperCase() + meal.slice(1),
      recipeId: text(day.recipe_id, "a menu recipe_id"),
      covers: number(day.covers, "menu covers"),
    };
  });
}

/** The body of `PUT /menu-plans/{week}`: the whole week. The gateway knows breakfast, lunch, dinner and other. */
export function menuPlanBody(entries: Draft<MenuPlanEntry>[]): Json {
  return {
    days: entries.map((entry) => ({
      date: entry.date,
      meal: entry.meal.trim().toLowerCase(),
      recipe_id: entry.recipeId,
      covers: entry.covers,
    })),
  };
}

// ---- stock ----------------------------------------------------------------------------

/**
 * `GET /stock`. `on_order` counts only when the gateway says `on_order_known`; today it does
 * not, so it is unknown. The gateway has no last delivery date.
 */
export function mapStock(body: unknown): StockItem[] {
  return rows(body, "items").map((row) => {
    const productId = text(row.product_id, "a stock product_id");
    return {
      productId,
      productName: nameOr(productId, row.product_name),
      unit: text(row.unit, "a stock unit"),
      onHand: decimal(row.on_hand, "on_hand"),
      onOrder: row.on_order_known === true ? decimal(row.on_order, "on_order") : null,
      countedAt: typeof row.counted_at === "string" ? row.counted_at : null,
      lastDelivery: null,
    };
  });
}

/**
 * The body of `POST /stock-counts`. The gateway wants the unit of each count; it comes from
 * the stock list the person counted from (`units`: product id to unit). A null count goes
 * out as null: not counted, never zero.
 */
export function stockCountBody(
  counts: StockCount[],
  units: ReadonlyMap<string, string>,
  countedAt: string,
  idempotencyKey: string,
): Json {
  return {
    idempotency_key: idempotencyKey,
    counted_at: countedAt,
    source: "manual",
    counts: counts.map((count) => {
      const unit = units.get(count.productId);
      if (!unit) throw new ApiError("NOT_FOUND", `Stock product ${count.productId} was not found.`);
      return { product_id: count.productId, unit, on_hand: optionalDecimal(count.onHand, "A count") };
    }),
  };
}

// ---- demand ---------------------------------------------------------------------------

/** `GET /demand`: the gross need per product and day. `net_need` and `problems` have no place in the UI type yet. */
export function mapDemand(body: unknown): DemandLine[] {
  return rows(body, "rows").map((row) => {
    const productId = text(row.product_id, "a demand product_id");
    return {
      productId,
      productName: nameOr(productId, row.product_name),
      unit: text(row.unit, "a demand unit"),
      date: text(row.date, "a demand date"),
      need: mapMoney(row.gross_need, "gross_need"),
      why: typeof row.why === "string" ? row.why : "",
    };
  });
}

// ---- the order for the menu plan ------------------------------------------------------

/** The body of `POST /proposals` for a menu plan window: no products and no text. */
export function planProposalBody(from: string, to: string, requestedDate: string, idempotencyKey: string): Json {
  return { from, to, requested_date: requestedDate, idempotency_key: idempotencyKey };
}

/**
 * The proposal the gateway made for a menu plan window, as the counts the planner shows.
 * `stock_counted: false` on a need means the full need was proposed, not a guess.
 */
export function mapPlanProposal(body: unknown): PlanProposal {
  const proposal = object(body, "a proposal");
  const request = object(proposal.request, "a proposal's request");
  const needs = list(request.needs, "a proposal's needs").map((need) => object(need, "a need"));
  const mandate = proposal.mandate == null ? {} : object(proposal.mandate, "a proposal's mandate");
  const codes = mandate.reason_codes == null ? [] : list(mandate.reason_codes, "reason_codes");
  if (proposal.status !== "READY" && proposal.status !== "REJECTED") invalid("a proposal status");
  return {
    id: text(proposal.proposal_id, "proposal_id"),
    status: proposal.status,
    totalInclVat: mapMoney(proposal.expected_total, "expected_total"),
    lineCount: list(proposal.lines, "proposal lines").length,
    needCount: needs.length,
    uncountedCount: needs.filter((need) => need.stock_counted === false).length,
    shortfallCount: proposal.shortfalls == null ? 0 : list(proposal.shortfalls, "shortfalls").length,
    reasonCodes: codes.filter((code): code is string => typeof code === "string" && code !== ""),
  };
}

// ---- sharing --------------------------------------------------------------------------

/** `GET/PUT /sharing`. Shared means granted and not revoked. A supplier with no row is not in the list. */
export function mapSharing(body: unknown): SharingConsent[] {
  return rows(body, "sharing").map((row) => ({
    supplierId: text(row.supplier_id, "a sharing supplier_id"),
    shared: row.share_forecast === true && row.revoked_at == null,
  }));
}

// ---- supplier demand ------------------------------------------------------------------

const RISKS: Record<string, ShortageRisk> = { OK: "COVERED", SHORT: "SHORT", UNKNOWN: "UNKNOWN" };

/**
 * `GET /v1/suppliers/{id}/demand`. The gateway's `OK` is the UI's COVERED; it has no AT_RISK.
 * A risk the UI does not know is UNKNOWN, never covered.
 */
export function mapSupplierDemand(body: unknown): SupplierDemandRow[] {
  return rows(body, "rows").map((row) => {
    const productId = text(row.product_id, "a demand product_id");
    return {
      productId,
      productName: nameOr(productId, row.product_name),
      unit: text(row.unit, "a demand unit"),
      date: text(row.date, "a demand date"),
      forecastDemand: mapMoney(row.demand, "demand"),
      kitchens: number(row.kitchens, "kitchens"),
      byKitchen: list(row.by_kitchen ?? [], "by_kitchen").map((item) => {
        const kitchen = object(item, "a kitchen's demand");
        const kitchenId = text(kitchen.kitchen_id, "a kitchen_id");
        return {
          kitchenId,
          kitchenName: nameOr(kitchenId, kitchen.kitchen_name),
          demand: mapMoney(kitchen.demand, "a kitchen's demand"),
        };
      }),
      available: decimal(row.available, "available"),
      risk: (typeof row.risk === "string" ? RISKS[row.risk] : undefined) ?? "UNKNOWN",
      suggestedBuy: decimal(row.suggested_buy, "suggested_buy"),
    };
  });
}

// ---- kitchen settings -----------------------------------------------------------------

const DEMAND_CLASSES: DemandClass[] = ["A", "B", "C"];

/** A decimal string or a JSON number (the gateway stores the stock-out cap as a float); NaN when not set. */
function setting(value: unknown, label: string): number {
  if (value == null) return Number.NaN;
  return typeof value === "number" ? number(value, label) : mapMoney(value, label);
}

/**
 * `GET/PUT /settings`. The gateway sends only what the kitchen has set; for the rest the
 * engine's own default applies, and the gateway does not say what that is. So a service level
 * or a stock-out cap that is not set is NaN: the settings form shows an empty field, not a
 * number nobody chose. `excluded_allergens: null` (unknown) reads as an empty list here; see
 * `settingsBody` for why a save does not turn that into "no exclusions".
 */
export function mapKitchenSettings(body: unknown): KitchenSettings {
  const row = object(body, "the kitchen settings");
  const levels = row.service_level == null ? {} : object(row.service_level, "service_level");
  const cover = row.max_cover_days == null ? {} : object(row.max_cover_days, "max_cover_days");
  const level = (demandClass: DemandClass) => {
    const fraction = setting(levels[demandClass], "service_level");
    // 0.975 * 100 is not exactly 97.5 in binary; four decimals of a percent are enough.
    return Number.isNaN(fraction) ? fraction : Math.round(fraction * 1e6) / 1e4;
  };
  return {
    serviceLevelPercent: { A: level("A"), B: level("B"), C: level("C") },
    maxDaysOfCover: Object.entries(cover).map(([category, days]) => ({
      category,
      maxDays: number(days, "max_cover_days"),
    })),
    stockOutDemandCap: setting(row.stockout_cap, "stockout_cap"),
    budgetWarningPerOrderExVat: decimal(row.budget_warning_order_eur, "budget_warning_order_eur"),
    budgetWarningPerWeekExVat: decimal(row.budget_warning_week_eur, "budget_warning_week_eur"),
    excludedAllergens:
      row.excluded_allergens == null
        ? []
        : list(row.excluded_allergens, "excluded_allergens").map((code) => text(code, "an allergen code")),
  };
}

/**
 * The body of `PUT /settings`: only the fields the person changed, from `before` (what the
 * gateway has now) to `after` (the form). An empty object means nothing changed.
 *
 * Sending only the changes keeps what is unknown unknown: a level that was never set stays
 * with the engine's default, and an allergen policy the gateway calls unknown does not become
 * "no exclusions" because the form shows no ticked box. The gateway merges `max_cover_days`,
 * so it cannot remove a category: that is refused here, before anything is saved.
 */
export function settingsBody(before: KitchenSettings, after: KitchenSettings): Json {
  const body: Json = {};
  const changedNumber = (was: number, now: number, label: string): boolean => {
    if (Object.is(was, now)) return false;
    if (!Number.isFinite(now)) throw new ApiError("INVALID", `${label} must be a number.`);
    return true;
  };

  const levels: Json = {};
  for (const demandClass of DEMAND_CLASSES) {
    const now = after.serviceLevelPercent[demandClass];
    if (changedNumber(before.serviceLevelPercent[demandClass], now, `Service level ${demandClass}`)) {
      levels[demandClass] = decimalString(now / 100);
    }
  }
  if (Object.keys(levels).length > 0) body.service_level = levels;

  const was = new Map(before.maxDaysOfCover.map((rule) => [rule.category, rule.maxDays]));
  const now = new Map(after.maxDaysOfCover.map((rule) => [rule.category.trim(), rule.maxDays]));
  const removed = [...was.keys()].filter((category) => !now.has(category));
  if (removed.length > 0) {
    throw new ApiError(
      "NOT_SERVED",
      `The gateway cannot remove a days-of-cover rule yet (${removed.join(", ")}). Nothing was saved.`,
    );
  }
  const cover: Json = {};
  for (const [category, days] of now) if (was.get(category) !== days) cover[category] = days;
  if (Object.keys(cover).length > 0) body.max_cover_days = cover;

  if (changedNumber(before.stockOutDemandCap, after.stockOutDemandCap, "Stock-out demand cap")) {
    body.stockout_cap = decimalString(after.stockOutDemandCap);
  }
  if (before.budgetWarningPerOrderExVat !== after.budgetWarningPerOrderExVat) {
    body.budget_warning_order_eur = optionalDecimal(after.budgetWarningPerOrderExVat, "Per-order budget warning");
  }
  if (before.budgetWarningPerWeekExVat !== after.budgetWarningPerWeekExVat) {
    body.budget_warning_week_eur = optionalDecimal(after.budgetWarningPerWeekExVat, "Weekly budget warning");
  }
  const codes = (settings: KitchenSettings) => [...new Set(settings.excludedAllergens)].sort().join(",");
  if (codes(before) !== codes(after)) body.excluded_allergens = [...new Set(after.excludedAllergens)];
  return body;
}

// ---- earned auto-approve --------------------------------------------------------------

/**
 * `GET /auto-approve`: its `learning` object. The gateway sends an edit rate of 0 when nothing
 * has been decided yet; with no decisions the rate is unknown, not 0 %.
 */
export function mapAutoApproveLearning(body: unknown): AutoApproveLearning {
  const learning = object(object(body, "auto-approve").learning, "auto-approve learning");
  const decisions = number(learning.decisions, "decisions");
  return {
    weeks: number(learning.weeks, "weeks"),
    weeksNeeded: number(learning.weeks_needed, "weeks_needed"),
    decisions,
    decisionsNeeded: number(learning.decisions_needed, "decisions_needed"),
    editRate: decisions === 0 || learning.edit_rate == null ? null : number(learning.edit_rate, "edit_rate"),
    maxEditRate: number(learning.max_edit_rate, "max_edit_rate"),
  };
}
