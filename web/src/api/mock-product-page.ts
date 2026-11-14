import type { ProductPage, ProductPageSupplier } from "@/api/http-product-page";
import { ApiError } from "@/api/types";
import { products } from "@/mocks/milk-case";
import type { Product } from "@/types";

/**
 * Sample product pages for the mock API (docs/contract.md "Product page"). Invented figures,
 * no supplier data. The milk products use the milk-case sample rows; the salmon is a page of
 * its own, so a fish product with a supplier comparison can be seen without the gateway.
 * Arla's 10 L novobox has no VAT code and no allergen data: both say "unknown".
 */
const CATALOG = "Valio product data";
const LIVE = "Valio price and availability API";
const DATE = "2026-11-16";

const salmon: Product = {
  id: "461903",
  names: { en: "Salmon fillet A, ASC, skin on", fi: "Lohifilee A, ASC, nahallinen" },
  brand: "Kalavapriikki",
  vendorName: "Kalavapriikki Oy",
  category: "Fresh fish",
  salesUnit: "KG",
  baseUnit: "KG",
  baseUnitsPerSalesUnit: 1,
  units: [{ unitId: "KG", sizeInBaseUnits: 1 }],
  fatPercent: null,
  temperature: { code: 2, label: "Chilled, 0 to +2 °C" },
  allergens: [{ code: "AF", name: "Fish", presence: "CONTAINS" }],
  labels: [],
  co2KgPerKg: 11.9,
  deliveryReliability: 0.96,
};

function valio(product: Product, price: number | null, vat: number | null, stockKnown: boolean): ProductPageSupplier {
  const content = product.baseUnitsPerSalesUnit;
  return {
    supplierId: "sup-valio",
    name: "Valio Aimo",
    adapter: "valio_api",
    productId: product.id,
    productName: product.names.en,
    priceExVat: price,
    per: product.salesUnit,
    priceSource: price == null ? null : LIVE,
    vatRate: vat,
    stockKnown,
    netContent: content ? { value: content, unit: product.baseUnit } : null,
    pricePerMeasure: price != null && content ? price / content : null,
    measureUnit: content ? product.baseUnit : null,
    leadTimeDays: 1,
    leadTimeSource: "supplier_terms",
    orderDays: ["MON", "TUE", "WED", "THU", "FRI"],
    cutoffTime: "17:00",
    freeDeliveryThresholdEur: 300,
    deliveryFeeEur: 29,
  };
}

function manual(
  supplierId: string,
  name: string,
  price: number,
  per: string,
  content: number,
  terms: { lead: number; days: string[]; threshold: number; fee: number },
): ProductPageSupplier {
  return {
    supplierId,
    name,
    adapter: "manual",
    productId: `${supplierId}-461903`,
    productName: "Salmon fillet, farmed",
    priceExVat: price,
    per,
    priceSource: "entered",
    vatRate: 13.5,
    stockKnown: false,
    netContent: { value: content, unit: "KG" },
    pricePerMeasure: price / content,
    measureUnit: "KG",
    leadTimeDays: terms.lead,
    leadTimeSource: "supplier_terms",
    orderDays: terms.days,
    cutoffTime: "12:00",
    freeDeliveryThresholdEur: terms.threshold,
    deliveryFeeEur: terms.fee,
  };
}

const noKitchen: ProductPage["kitchen"] = { orders: [], proposalsWaiting: [], stock: null, recipes: [], demand: null };

function page(product: Product, extra: Partial<ProductPage>): ProductPage {
  const known = product.allergens !== null;
  return {
    productId: product.id,
    product,
    about: null,
    supplierId: null,
    allergens: {
      known,
      contains: (product.allergens ?? []).filter((a) => a.presence === "CONTAINS").map(({ code, name }) => ({ code, name })),
      mayContain: (product.allergens ?? []).filter((a) => a.presence === "MAY_CONTAIN").map(({ code, name }) => ({ code, name })),
      freeFrom: [],
      noDeclarableAllergens: false,
      source: known ? `${CATALOG}, allergen classification` : null,
    },
    nutrition: null,
    storage: { temperature: "chilled", minC: 2, maxC: 6, source: CATALOG },
    origin: { country: "fi", source: `${CATALOG}, countryOfOrigin` },
    vat: { code: "MEDIUM", rate: 13.5, source: `${CATALOG}, vatCode` },
    live: {
      date: DATE,
      priceExVat: 1.15,
      priceInclVat: 1.31,
      per: product.salesUnit,
      taxRate: 13.5,
      comparisonPrice: 1.15,
      comparisonUnit: "L",
      stock: { available: 640, unknown: false, availableDate: DATE, orderable: true, cutoffPassed: false, closingTime: "2026-11-15T13:00:00+02:00" },
      error: null,
      source: LIVE,
    },
    recall: { status: "CLEAR", alerts: [] },
    suppliers: [valio(product, 1.15, 13.5, true)],
    kitchen: noKitchen,
    ...extra,
  };
}

function pages(): Record<string, ProductPage> {
  const milkAbout = (en: string): ProductPage["about"] => ({
    marketingText: { en },
    keyIngredients: null,
    ingredients: [{ en: "Lactose free skimmed milk", fi: "Laktoositon rasvaton maito" }],
    storageInstructions: { en: "Store at +2 to +6 °C. Once opened, use within 4 days." },
    preparationInstructions: null,
    usageInstructions: null,
    producer: "Valio Oy",
    source: CATALOG,
  });
  return {
    [salmon.id]: page(salmon, {
      about: {
        marketingText: { en: "Norwegian ASC-certified salmon fillet, trimmed A cut with skin, pin bones removed." },
        keyIngredients: { en: "Salmon 100 %" },
        ingredients: [{ en: "Salmon (Salmo salar)", fi: "Lohi (Salmo salar)" }],
        storageInstructions: { en: "Keep at 0 to +2 °C. Use within 2 days of delivery." },
        preparationInstructions: { en: "Oven 180 °C, 12 to 15 minutes, to a core of +55 °C." },
        usageInstructions: null,
        producer: "Kalavapriikki Oy",
        source: CATALOG,
      },
      allergens: {
        known: true,
        contains: [{ code: "AF", name: "fish" }],
        mayContain: [],
        freeFrom: [{ code: "AW", name: "gluten" }, { code: "AM", name: "milk" }],
        noDeclarableAllergens: false,
        source: `${CATALOG}, allergen classification`,
      },
      nutrition: {
        basis: "g",
        values: { kcal: 208, fat_g: 13.4, saturated_fat_g: 2.4, carbs_g: 0, sugar_g: 0, protein_g: 20.4, salt_g: 0.1 },
        source: `${CATALOG}, nutritionalContent`,
      },
      storage: { temperature: "chilled", minC: 0, maxC: 2, source: CATALOG },
      origin: { country: "no", source: `${CATALOG}, countryOfOrigin` },
      live: {
        date: DATE,
        priceExVat: 24.85,
        priceInclVat: 28.2,
        per: "KG",
        taxRate: 13.5,
        comparisonPrice: 24.85,
        comparisonUnit: "KG",
        stock: { available: 120, unknown: false, availableDate: DATE, orderable: true, cutoffPassed: false, closingTime: "2026-11-15T13:00:00+02:00" },
        error: null,
        source: LIVE,
      },
      suppliers: [
        valio(salmon, 24.85, 13.5, true),
        manual("sup-demo-fish", "Baltic Catch Fish Wholesale (demo)", 112.5, "KI", 5, {
          lead: 1,
          days: ["MON", "WED", "FRI"],
          threshold: 150,
          fee: 18,
        }),
        manual("sup-demo-pantry", "Northern Pantry Wholesale (demo)", 236, "KI", 10, {
          lead: 2,
          days: ["TUE", "THU"],
          threshold: 400,
          fee: 35,
        }),
      ],
      kitchen: {
        orders: [{ id: "ORD-1042", createdAt: "2026-11-09T08:12:00+02:00", quantity: 12, unit: "KG", total: 298.2, status: "PLACED" }],
        proposalsWaiting: [],
        stock: { onHand: 3.2, unit: "KG", countedAt: "2026-11-13T15:40:00+02:00" },
        recipes: [{ recipeId: "env-salmon_soup", name: "Salmon soup", qtyPerPortion: 0.08, unit: "KG" }],
        demand: { from: "2026-11-15", to: "2026-11-28", unit: "KG", grossNeed: 14.2, days: 9, source: "menu plan and forecast" },
      },
    }),
    [products.arlaUht1l.id]: page(products.arlaUht1l, {
      about: milkAbout("UHT milk drink for kitchens: keeps unopened at room temperature."),
      storage: { temperature: "ambient", minC: null, maxC: null, source: CATALOG },
      kitchen: {
        ...noKitchen,
        orders: [{ id: "ORD-1042", createdAt: "2026-11-13T20:40:00+02:00", quantity: 114, unit: "ST", total: 131.07, status: "PLACED" }],
      },
    }),
    [products.eila3pct1l.id]: page(products.eila3pct1l, {
      about: milkAbout("Lactose free milk drink, 3 % fat."),
      kitchen: {
        ...noKitchen,
        proposalsWaiting: [{ id: "APR-311", createdAt: "2026-11-13T20:40:00+02:00", quantity: 1500, unit: "ST", total: 1947.5 }],
        stock: { onHand: 48, unit: "ST", countedAt: "2026-11-13T15:40:00+02:00" },
        recipes: [{ recipeId: "rec-porridge", name: "Oat porridge", qtyPerPortion: 0.15, unit: "L" }],
      },
    }),
    [products.arlaEsl10l.id]: page(products.arlaEsl10l, {
      // Valio sends the producer's id and the allergen codes with their English names.
      supplierId: "10400",
      allergens: {
        known: true,
        contains: [{ code: "AM", name: "milk" }],
        mayContain: [],
        freeFrom: [["AC", "crustaceans"], ["AE", "eggs"], ["AF", "fish"], ["AN", "nuts"], ["AP", "peanuts"], ["AS", "sesame"], ["AU", "sulphites"], ["AW", "gluten"], ["AY", "soy"], ["BC", "celery"], ["BM", "mustard"], ["NL", "lupin"], ["UM", "molluscs"]].map(
          ([code, name]) => ({ code, name }),
        ),
        noDeclarableAllergens: false,
        source: `${CATALOG}, allergen classification`,
      },
      vat: { code: null, rate: null, source: null },
      origin: { country: null, source: null },
      live: {
        date: DATE,
        priceExVat: 14.9,
        priceInclVat: null,
        per: "ST",
        taxRate: null,
        comparisonPrice: 1.49,
        comparisonUnit: "L",
        stock: { available: null, unknown: true, availableDate: null, orderable: true, cutoffPassed: true, closingTime: "2026-11-13T12:00:00+02:00" },
        error: null,
        source: LIVE,
      },
      suppliers: [valio(products.arlaEsl10l, 14.9, null, false)],
      about: milkAbout("Novobox for kitchens: a 10 L box for tap or dispenser."),
    }),
  };
}

/** The mock `getProductPage`: a sample page for every mock product, 404 for any other code. */
export async function getProductPageMock(productId: string): Promise<ProductPage> {
  const known = pages()[productId];
  if (known) return known;
  const product = (Object.values(products) as Product[]).find((item) => item.id === productId);
  if (!product) throw new ApiError("PRODUCT_NOT_FOUND", `No product ${productId}.`);
  return page(product, {});
}
