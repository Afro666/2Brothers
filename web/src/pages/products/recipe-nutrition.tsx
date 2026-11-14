import { useApi } from "@/api";
import type { NutrientValues } from "@/api/types";
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

/**
 * One portion's energy and macros under a recipe, from the products' own nutrition tables.
 * A value the labels do not give is left out, never shown as 0. Loading and a failed call are
 * one quiet line each, so the recipe card always shows.
 */
export function RecipeNutritionLine({ recipe }: { recipe: Recipe }) {
  const t = useT();
  const api = useApi();
  // The numbers change with the ingredients, so a saved edit loads them again.
  const ingredients = JSON.stringify(recipe.items.map((item) => [item.productId, item.unit, item.qtyPerPortion]));
  const state = useAsync(() => api.getRecipeNutrition(recipe.id), [api, recipe.id, ingredients]);
  const quiet = "text-sm text-muted-foreground";

  if (state.status === "loading") return <p className={quiet}>{t("Counting nutrition…")}</p>;
  if (state.status === "error") return <p className={quiet}>{t("Nutrition is not available right now.")}</p>;

  const nutrition = state.data;
  if (!nutrition.plausible) {
    return <p className="text-sm text-warning">{t("This looks wrong: check the units in this recipe.")}</p>;
  }
  const total = nutrition.knownIngredients + nutrition.unknown.length;
  const missing =
    nutrition.unknown.length > 0 ? (
      <p className="text-xs text-muted-foreground">
        {t("No nutrition table: {products}", {
          products: nutrition.unknown.map((product) => product.productName).join(", "),
        })}
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
