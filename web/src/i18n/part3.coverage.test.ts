import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { DIRECTION_SR, TIER_LABEL } from "@/components/purchasing/offer-compare";
import { LABEL_META } from "@/components/purchasing/chips";
import { collectFinnishDictionaries } from "@/lib/i18n";
import { ALLERGENS as CATALOG_ALLERGENS, TEMPERATURE_LABELS } from "@/pages/catalog";
import { KITCHEN_TYPES } from "@/pages/onboarding";
import { ALLERGENS as PRODUCT_ALLERGENS } from "@/pages/products";
import { ADAPTER_LABEL, DAY_LABEL } from "@/pages/suppliers";

const TRANSLATED_FILES = [
  "pages/planner.tsx",
  "pages/stock.tsx",
  "pages/products.tsx",
  "pages/products/product-picker.tsx",
  "pages/catalog.tsx",
  "pages/suppliers.tsx",
  "pages/onboarding.tsx",
  "components/purchasing/shelf-photo-count.tsx",
  "components/purchasing/product-card.tsx",
  "components/purchasing/offer-compare.tsx",
  "components/purchasing/chips.tsx",
  "components/purchasing/label-evidence.tsx",
  "components/purchasing/kitchen-logo.tsx",
];

const SUPPLIER_VALIDATION_MESSAGES = [
  "Enter a time in HH:MM format.",
  "Enter a valid time.",
  "Enter a valid amount.",
  "Value cannot be negative.",
  "Enter a whole number.",
];

const PRODUCT_FACT_TEXT = [
  "Temperature",
  "CO2 per kg",
  "Product-group estimate",
  "Delivery reliability",
  "Delivered vs ordered",
];

describe("part 3 Finnish coverage", () => {
  it("has a Finnish entry for every literal and dynamic label in the translated files", () => {
    const files = import.meta.glob("./fi/*.ts", { eager: true }) as Record<
      string,
      { default: Record<string, string> }
    >;
    const dictionary = collectFinnishDictionaries(files);
    const missing: string[] = [];
    for (const file of TRANSLATED_FILES) {
      const source = readFileSync(resolve(process.cwd(), "src", file), "utf8");
      for (const match of source.matchAll(/\bt\("((?:\\.|[^"\\])*)"/g)) {
        const text = JSON.parse(`"${match[1]}"`) as string;
        if (!Object.prototype.hasOwnProperty.call(dictionary, text)) missing.push(`${file}: ${text}`);
      }
    }
    const dynamicTexts = [
      ...Object.values(TIER_LABEL),
      ...Object.values(DIRECTION_SR).filter(Boolean),
      ...Object.values(LABEL_META).map((meta) => meta.text),
      ...Object.values(TEMPERATURE_LABELS),
      ...Object.values(ADAPTER_LABEL),
      ...Object.values(DAY_LABEL),
      ...KITCHEN_TYPES.map((type) => type.label),
      ...CATALOG_ALLERGENS.map((allergen) => allergen.name),
      ...PRODUCT_ALLERGENS.map(([, name]) => name),
      ...SUPPLIER_VALIDATION_MESSAGES,
      ...PRODUCT_FACT_TEXT,
    ];
    for (const text of dynamicTexts) {
      if (!Object.prototype.hasOwnProperty.call(dictionary, text)) missing.push(`dynamic: ${text}`);
    }
    expect(missing).toEqual([]);
  });
});
