import { describe, expect, it } from "vitest";

import type { Recipe } from "@/types";
import { catalogProductIdsInRecipes } from "@/pages/products/recipe-products";

const RECIPES: Recipe[] = [
  {
    id: "r1",
    name: "Pudding",
    items: [
      { productId: "463335", productName: "Milk", unit: "L", qtyPerPortion: 0.1 },
      { productId: "OWN-RYE", productName: "Rye", unit: "PCS", qtyPerPortion: 1 },
    ],
  },
  {
    id: "r2",
    name: "Soup",
    items: [{ productId: "463335", productName: "Milk", unit: "L", qtyPerPortion: 0.2 }],
  },
];

const OWN = [
  { id: "OWN-RYE", name: "Rye", unit: "PCS", packSize: null, priceEur: null, supplierId: "S", allergens: null },
];

describe("catalogProductIdsInRecipes", () => {
  it("collects each catalog id once and leaves own products out", () => {
    expect(catalogProductIdsInRecipes(RECIPES, OWN)).toEqual(["463335"]);
  });

  it("has nothing to load when every recipe uses own products", () => {
    const ownOnly = RECIPES.map((recipe) => ({ ...recipe, items: recipe.items.slice(1) }));
    expect(catalogProductIdsInRecipes(ownOnly, OWN)).toEqual([]);
  });
});
