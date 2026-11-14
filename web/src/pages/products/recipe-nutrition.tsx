import { useApi } from "@/api";
import type { NutrientValues, RecipeNutrition } from "@/api/types";
import { ProductThumb } from "@/components/purchasing/product-thumb";
import { formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useAsync } from "@/lib/use-async";
import type { Recipe } from "@/types";

export const MACROS: [keyof NutrientValues, string][] = [
  ["proteinG", "protein {amount} g"],
  ["fatG", "fat {amount} g"],
  ["carbsG", "carbs {amount} g"],
  ["saltG", "salt {amount} g"],
];

/** Thumbnails shown before the missing-nutrition text; the rest become a "+N" chip. */
const MAX_THUMBS = 3;

/** What a recipe card shows: still loading, not available, or the gateway's row. */
export type RecipeNutritionState = "loading" | "error" | RecipeNutrition;

/**
 * Loads the nutrition of every recipe in one request (`GET /recipes/nutrition`, #1101) and gives
 * each card its row. `active` is the Recipes tab being open: no call is made before that.
 */
export function useRecipesNutrition(recipes: Recipe[], active: boolean): (recipe: Recipe) => RecipeNutritionState {
  const api = useApi();
  const asked = active && recipes.length > 0;
  // The numbers change with the ingredients, so a saved edit loads them again.
  const ingredients = JSON.stringify(
    recipes.map((recipe) => [recipe.id, recipe.items.map((item) => [item.productId, item.unit, item.qtyPerPortion])]),
  );
  const state = useAsync(() => (asked ? api.getRecipesNutrition() : Promise.resolve(null)), [api, asked, ingredients]);
  const rows = state.status === "ready" && state.data ? new Map(state.data.map((row) => [row.recipeId, row])) : null;
  // A recipe the answer leaves out (added after the read began) shows "not available", never 0.
  return (recipe) => (state.status === "error" ? "error" : rows ? (rows.get(recipe.id) ?? "error") : "loading");
}

/**
 * One portion's energy and macros under a recipe, from the products' own nutrition tables.
 * A value the labels do not give is left out, never shown as 0. Loading and a failed call are
 * one quiet line each, so the recipe card always shows.
 */
export function RecipeNutritionLine({ nutrition }: { nutrition: RecipeNutritionState }) {
  const t = useT();
  const quiet = "text-sm text-muted-foreground";

  if (nutrition === "loading") return <p className={quiet}>{t("Counting nutrition…")}</p>;
  if (nutrition === "error") return <p className={quiet}>{t("Nutrition is not available right now.")}</p>;

  if (!nutrition.plausible) {
    return <p className="text-sm text-warning">{t("This looks wrong: check the units in this recipe.")}</p>;
  }
  const total = nutrition.knownIngredients + nutrition.unknown.length;
  const missing =
    nutrition.unknown.length > 0 ? (
      <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        <span className="flex shrink-0 items-center gap-0.5">
          {nutrition.unknown.slice(0, MAX_THUMBS).map((product) => (
            <ProductThumb key={product.productId} en={product.productName} size="sm" className="size-5" />
          ))}
          {nutrition.unknown.length > MAX_THUMBS ? (
            // The text after it names every product, so a screen reader skips the count.
            <span aria-hidden data-more className="rounded-full bg-muted px-1.5 text-[0.65rem] leading-5">
              +{nutrition.unknown.length - MAX_THUMBS}
            </span>
          ) : null}
        </span>
        <span className="min-w-0 break-words">
          {t("No nutrition table: {products}", {
            products: nutrition.unknown.map((product) => product.productName).join(", "),
          })}
        </span>
      </p>
    ) : null;
  const { kcal } = nutrition.perPortion;
  if (kcal == null) {
    return (
      <div className="space-y-0.5">
        <p className={quiet}>{t("Nutrition not known")}</p>
        {missing}
      </div>
    );
  }
  const macros = MACROS.flatMap(([key, label]) => {
    const amount = nutrition.perPortion[key];
    return amount == null ? [] : [t(label, { amount: formatNumber(amount) })];
  });
  return (
    <div className="space-y-0.5">
      <p className="text-sm tabular-nums">
        {t("{kcal} kcal per portion", { kcal: formatNumber(kcal) })}
        {nutrition.complete ? null : (
          <span className="text-muted-foreground">
            {" · "}
            {t("counted from {known} of {total} ingredients", {
              known: formatNumber(nutrition.knownIngredients),
              total: formatNumber(total),
            })}
          </span>
        )}
      </p>
      {macros.length > 0 ? <p className="text-xs tabular-nums text-muted-foreground">{macros.join(" · ")}</p> : null}
      {missing}
    </div>
  );
}
