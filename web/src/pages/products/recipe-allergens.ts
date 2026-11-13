import type { Allergen, Product, Recipe } from "@/types";

export interface RecipeAllergenSummary {
  allergens: Allergen[];
  unknown: boolean;
}

/** Unknown product data stays visible even when the rest of a recipe is known. */
export function recipeAllergens(
  recipe: Recipe,
  products: ReadonlyMap<string, Product | { allergens: Allergen[] | null }>,
): RecipeAllergenSummary {
  const rolled = new Map<string, Allergen>();
  let unknown = false;
  for (const item of recipe.items) {
    const product = products.get(item.productId);
    if (!product || product.allergens === null) {
      unknown = true;
      continue;
    }
    for (const allergen of product.allergens) {
      const previous = rolled.get(allergen.code);
      if (!previous || allergen.presence === "CONTAINS") rolled.set(allergen.code, allergen);
    }
  }
  return { allergens: [...rolled.values()], unknown };
}
