import { type Json, object, rows, text } from "@/api/gateway-map";
import type { Api, MatchedBy, ProductSearchFilters, SearchedProduct, SearchedProducts } from "@/api/types";
import { ApiError } from "@/api/types";
import type { Allergen, PackUnit, Product, ProductLabel } from "@/types";

/** The gateway request of api/http.ts: a path under the base URL, the parsed JSON back. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

type CatalogApi = Pick<Api, "searchProducts" | "getProducts">;

/** `search_products` answers at most 50 rows (docs/contract.md "search_products"). */
const SEARCH_LIMIT = 50;
/** `GET /catalog/products?ids=` takes 1 to 200 codes. */
const IDS_PER_CALL = 200;

/** The gateway sends GS1 codes only; names from docs/contract.md "search_products". */
const ALLERGEN_NAMES: Record<string, string> = {
  AW: "Gluten",
  AC: "Crustaceans",
  AE: "Eggs",
  AF: "Fish",
  AP: "Peanuts",
  AY: "Soy",
  AM: "Milk",
  AN: "Nuts",
  BC: "Celery",
  BM: "Mustard",
  AS: "Sesame",
  AU: "Sulphites",
  NL: "Lupin",
  UM: "Molluscs",
  ML: "Lactose",
  UW: "Wheat",
  GO: "Oats",
};

/** The labels the UI knows how to show (`ProductLabel`); other labels are left out. */
const SHOWN_LABELS: readonly ProductLabel[] = ["EU_ORGANIC_FARMING", "GOODS_FROM_FINLAND_BLUE_SWAN", "FINNISH_HEART_SYMBOL"];

const TEMPERATURE_WORDS: Record<string, string> = { ambient: "Ambient", chilled: "Chilled", frozen: "Frozen" };

function invalid(what: string): never {
  throw new ApiError("INVALID_RESPONSE", `The gateway sent ${what} in an unexpected shape.`);
}

/** A number, or null when the gateway says unknown (null or missing). */
function nullableNumber(value: unknown, what: string): number | null {
  if (value == null) return null;
  const parsed = typeof value === "string" && value.trim() ? Number(value) : value;
  if (typeof parsed !== "number" || !Number.isFinite(parsed)) invalid(what);
  return parsed;
}

function codes(value: unknown, what: string): string[] {
  if (value == null) return [];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) invalid(what);
  return value as string[];
}

function optionalText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/**
 * `allergen_data_known: false` is unknown: null, never an empty list.
 * `undeclared` (the supplier's "not declared" level) has no place in `Allergen`, so it is left out.
 */
function allergensOf(row: Json): Allergen[] | null {
  if (row.allergen_data_known !== true) return null;
  const levels = object(row.allergens ?? {}, "product allergens");
  const of = (list: unknown, presence: Allergen["presence"], what: string) =>
    codes(list, what).map((code): Allergen => ({ code, name: ALLERGEN_NAMES[code] ?? code, presence }));
  return [
    ...of(levels.contains, "CONTAINS", "allergens.contains"),
    ...of(levels.may_contain, "MAY_CONTAIN", "allergens.may_contain"),
  ];
}

/** `temperature` is `ambient`, `chilled` or `frozen`; the label adds the range when the row has it. */
function temperatureOf(row: Json): Product["temperature"] {
  const word = typeof row.temperature === "string" ? TEMPERATURE_WORDS[row.temperature] : undefined;
  if (!word) return null;
  const min = nullableNumber(row.min_temperature_c, "min_temperature_c");
  const max = nullableNumber(row.max_temperature_c, "max_temperature_c");
  const signed = (value: number) => (value > 0 ? `+${value}` : String(value));
  const label = min !== null && max !== null ? `${word}, ${signed(min)} to ${signed(max)} °C` : word;
  // `temperatureCondition` is Valio's code; 0 when the row has none (the UI shows the label only).
  const code = typeof row.temperature_condition === "number" ? row.temperature_condition : 0;
  return { code, label };
}

/**
 * One product row of `search_products` or `GET /catalog/products` (docs/contract.md
 * "search_products: filters and the product row") to the web `Product`. Unknown stays null.
 */
export function mapCatalogProduct(value: unknown): Product {
  const row = object(value, "a product");
  const id = text(row.product_id, "a product_id");
  const rawNames = object(row.names ?? {}, "product names");
  const name = (key: string) => (typeof rawNames[key] === "string" && rawNames[key] ? (rawNames[key] as string) : undefined);
  const en = name("en") ?? name("fi") ?? name("sv") ?? id;
  const names: Product["names"] = { en };
  if (name("fi")) names.fi = name("fi");
  if (name("sv")) names.sv = name("sv");

  const units = (Array.isArray(row.units) ? row.units : []).map((item): PackUnit => {
    const unit = object(item, "a pack unit");
    const size = nullableNumber(unit.size_in_base_units, "size_in_base_units");
    if (size === null) invalid("a pack unit size");
    return { unitId: text(unit.unit, "a pack unit"), sizeInBaseUnits: size };
  });
  const salesUnit = optionalText(row.sales_unit);
  const net = row.net_content == null ? null : object(row.net_content, "net_content");
  // The unit prices compare in: L or KG from the net content, else KG when sold by weight.
  const baseUnit = typeof net?.unit === "string" ? net.unit : row.base_unit === "KG" ? "KG" : "";

  return {
    id,
    names,
    brand: optionalText(row.brand),
    vendorName: optionalText(row.vendor),
    category: optionalText(row.category),
    salesUnit,
    baseUnit,
    baseUnitsPerSalesUnit: units.find((unit) => unit.unitId === salesUnit)?.sizeInBaseUnits ?? null,
    units,
    // The product row has no nutrition data.
    fatPercent: null,
    temperature: temperatureOf(row),
    allergens: allergensOf(row),
    labels: codes(row.labels, "labels").filter((label): label is ProductLabel =>
      SHOWN_LABELS.includes(label as ProductLabel),
    ),
    co2KgPerKg: nullableNumber(row.carbon_kg_co2e_per_kg, "carbon_kg_co2e_per_kg"),
    deliveryReliability: nullableNumber(row.reliability, "reliability"),
  };
}

/** Maps each row on its own: a row that does not map is logged and skipped. */
function mapRows(body: unknown): Product[] {
  return rows(body, "products").flatMap((row) => {
    try {
      return [mapCatalogProduct(row)];
    } catch (error) {
      console.warn(`Skipped product ${String(row.product_id ?? "(no id)")}:`, error);
      return [];
    }
  });
}

const MATCHED_BY: readonly MatchedBy[] = ["words", "meaning", "both"];

/** Search rows with how each was found, and whether a search by meaning fell back to words. */
function mapSearchRows(body: unknown): SearchedProducts {
  const found: SearchedProducts = rows(body, "products").flatMap((row): SearchedProduct[] => {
    try {
      const product: SearchedProduct = mapCatalogProduct(row);
      const matchedBy = MATCHED_BY.find((value) => value === row.matched_by);
      if (matchedBy) product.matchedBy = matchedBy;
      return [product];
    } catch (error) {
      console.warn(`Skipped product ${String(row.product_id ?? "(no id)")}:`, error);
      return [];
    }
  });
  if (object(body, "a search answer").meaning_unavailable === true) found.meaningUnavailable = true;
  return found;
}

/** The web filters to the gateway's names (store/search.py `build_pipeline`). Unset stays unsent. */
function gatewayFilters(filters: ProductSearchFilters): Json {
  const out: Json = {};
  if (filters.excludedAllergens?.length) {
    out.exclude_allergens = filters.excludedAllergens;
    out.allergen_strictness = filters.strictAllergens ? "strict" : "declared";
  } else if (filters.strictAllergens) {
    out.allergen_strictness = "strict";
  }
  if (filters.requiredLabels?.length) out.require_labels = filters.requiredLabels;
  if (filters.temperature) out.temperature = filters.temperature;
  return out;
}

/**
 * A 404 without the gateway's `error` envelope is the framework's "no such route": a gateway
 * from before PR #1172 does not serve `GET /catalog/products`. A named 404 means the route exists.
 */
function routeNotServed(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404 && error.code === "GATEWAY_ERROR";
}

/**
 * Catalog search and products by code, on the gateway. `sampleProducts` answers `getProducts`
 * while the gateway does not serve its route yet, so the screens keep the sample rows they had.
 */
export function createCatalogHttp(
  call: GatewayCall,
  kitchen: string,
  sampleProducts?: Api["getProducts"],
): CatalogApi {
  return {
    async searchProducts(query, filters = {}) {
      const trimmed = query.trim();
      const sent = gatewayFilters(filters);
      // The gateway refuses a search with no query and no filter; strictness alone is not a filter.
      const hasFilter = Object.keys(sent).some((key) => key !== "allergen_strictness");
      if (!trimmed && !hasFilter) return [];
      // The "Search by meaning" switch: hybrid for this one search only (#1382).
      const mode = filters.byMeaning ? { mode: "hybrid" } : {};
      const body = await call("/tools/search_products", {
        method: "POST",
        body: JSON.stringify({ query: trimmed, filters: sent, limit: SEARCH_LIMIT, ...mode }),
      });
      return mapSearchRows(body);
    },
    async getProducts(ids) {
      const unique = [...new Set(ids.filter((id) => typeof id === "string" && id.trim()))];
      const groups: string[][] = [];
      for (let start = 0; start < unique.length; start += IDS_PER_CALL) {
        groups.push(unique.slice(start, start + IDS_PER_CALL));
      }
      let answers: unknown[];
      try {
        answers = await Promise.all(
          groups.map((group) => call(`${kitchen}/catalog/products?ids=${group.map(encodeURIComponent).join(",")}`)),
        );
      } catch (error) {
        if (!sampleProducts || !routeNotServed(error)) throw error;
        console.warn("The gateway does not serve GET /catalog/products yet (#1172): sample products shown.");
        return sampleProducts(unique);
      }
      return answers.flatMap(mapRows);
    },
  };
}
