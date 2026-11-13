import type { OwnProduct, ProductCode, Recipe } from "@/types";

/** The unique ids of catalog products that the kitchen's recipes use; own products are left out. */
export function catalogProductIdsInRecipes(
  recipes: readonly Recipe[],
  ownProducts: readonly OwnProduct[],
): ProductCode[] {
  const ownIds = new Set(ownProducts.map((product) => product.id));
  const ids = new Set<ProductCode>();
  for (const recipe of recipes) {
    for (const item of recipe.items) {
      if (!ownIds.has(item.productId)) ids.add(item.productId);
    }
  }
  return [...ids];
}
