import { describe, expect, it } from "vitest";

import { recipeAllergens } from "@/pages/products/recipe-allergens";

describe("recipeAllergens", () => {
  it("keeps known allergens and marks missing data unknown", () => {
    const recipe = {
      id: "r",
      name: "Meal",
      items: [
        { productId: "known", productName: "Known", unit: "L", qtyPerPortion: 1 },
        { productId: "missing", productName: "Missing", unit: "L", qtyPerPortion: 1 },
      ],
    };
    const products = new Map([
      ["known", { allergens: [{ code: "AF", name: "Fish", presence: "CONTAINS" as const }] }],
      ["missing", { allergens: null }],
    ]);
    expect(recipeAllergens(recipe, products)).toEqual({
      allergens: [{ code: "AF", name: "Fish", presence: "CONTAINS" }],
      unknown: true,
    });
  });

  it("marks the recipe unknown when a product cannot be found", () => {
    const recipe = {
      id: "r",
      name: "Meal",
      items: [
        { productId: "known", productName: "Known", unit: "L", qtyPerPortion: 1 },
        { productId: "gone", productName: "Gone", unit: "L", qtyPerPortion: 1 },
      ],
    };
    const products = new Map([["known", { allergens: [] }]]);
    expect(recipeAllergens(recipe, products)).toEqual({ allergens: [], unknown: true });
  });

  it("prefers CONTAINS over MAY_CONTAIN for the same code", () => {
    const recipe = {
      id: "r",
      name: "Meal",
      items: [
        { productId: "may", productName: "May", unit: "L", qtyPerPortion: 1 },
        { productId: "yes", productName: "Yes", unit: "L", qtyPerPortion: 1 },
      ],
    };
    const products = new Map([
      ["may", { allergens: [{ code: "AM", name: "Milk", presence: "MAY_CONTAIN" as const }] }],
      ["yes", { allergens: [{ code: "AM", name: "Milk", presence: "CONTAINS" as const }] }],
    ]);
    expect(recipeAllergens(recipe, products).allergens).toEqual([{ code: "AM", name: "Milk", presence: "CONTAINS" }]);
  });
});
