import { ApiError, type Api, type KitchenNutrition, type NutrientValues, type NutritionDay, type RecipeNutrition } from "@/api/types";
import { isoWeekOf, shiftWeek } from "@/lib/week";
import type { Recipe } from "@/types";

type NutritionApi = Pick<Api, "getRecipeNutrition" | "getNutrition">;

const NOTHING: NutrientValues = {
  kcal: null,
  proteinG: null,
  fatG: null,
  saturatedFatG: null,
  carbsG: null,
  sugarG: null,
  fibreG: null,
  saltG: null,
};

/**
 * Sample numbers per portion for the seeded recipes, with the ingredients that have no
 * nutrition table (the kitchen's own products). Against the gateway the numbers come from
 * the products' labels (api/http-nutrition.ts).
 */
const SAMPLE: Record<string, { perPortion: NutrientValues; unknown: string[] }> = {
  "REC-RICE-PUDDING": {
    perPortion: { kcal: 320, proteinG: 9.5, fatG: 9.8, saturatedFatG: 6.1, carbsG: 47.2, sugarG: 18.4, fibreG: 0.6, saltG: 0.3 },
    unknown: [],
  },
  "REC-SALMON-SOUP": {
    perPortion: { kcal: 540, proteinG: 31.2, fatG: 28.4, saturatedFatG: 9.7, carbsG: 36.5, sugarG: 6.2, fibreG: null, saltG: 1.4 },
    unknown: ["OWN-RYE"],
  },
  "REC-COFFEE-SERVICE": {
    perPortion: { kcal: 310, proteinG: 6.1, fatG: 11.9, saturatedFatG: 6.8, carbsG: 43.5, sugarG: 17, fibreG: 1.6, saltG: 0.5 },
    unknown: ["OWN-BUN"],
  },
};

/** A recipe without sample numbers (one a person added) has no nutrition table: all unknown. */
function portionOf(recipe: Recipe): RecipeNutrition {
  const sample = SAMPLE[recipe.id];
  const unknown = recipe.items.filter((item) => !sample || sample.unknown.includes(item.productId));
  return {
    recipeId: recipe.id,
    name: recipe.name,
    perPortion: { ...(unknown.length === recipe.items.length ? NOTHING : sample.perPortion) },
    knownIngredients: recipe.items.length - unknown.length,
    unknown: unknown.map((item) => ({ productId: item.productId, productName: item.productName })),
    complete: unknown.length === 0 && recipe.items.length > 0,
    plausible: true,
    source: "sample data",
  };
}

/** Nutrition for the mock API, from the mock's own recipes and menu plan. */
export function createNutritionMock(planning: Pick<Api, "listRecipes" | "getMenuPlan">): NutritionApi {
  return {
    async getRecipeNutrition(recipeId) {
      const recipe = (await planning.listRecipes()).find((candidate) => candidate.id === recipeId);
      if (!recipe) throw new ApiError("NOT_FOUND", "no such recipe", {}, 404);
      return portionOf(recipe);
    },

    async getNutrition(from, to): Promise<KitchenNutrition> {
      const portions = new Map((await planning.listRecipes()).map((recipe) => [recipe.id, portionOf(recipe)]));
      const days = new Map<string, NutritionDay>();
      const last = isoWeekOf(to);
      for (let week = isoWeekOf(from); week <= last; week = shiftWeek(week, 1)) {
        for (const entry of await planning.getMenuPlan(week)) {
          if (entry.date < from || entry.date > to) continue;
          const day = days.get(entry.date) ?? { date: entry.date, covers: 0, kcal: 0, proteinG: 0, kcalPerCover: null, complete: true };
          days.set(entry.date, day);
          const portion = portions.get(entry.recipeId);
          if (!portion || portion.perPortion.kcal == null) {
            day.complete = false;
            continue;
          }
          // The busiest dish of the day is the day's guests, as the gateway counts it.
          day.covers = Math.max(day.covers, entry.covers);
          day.kcal = (day.kcal ?? 0) + portion.perPortion.kcal * entry.covers;
          day.proteinG = (day.proteinG ?? 0) + (portion.perPortion.proteinG ?? 0) * entry.covers;
          day.complete = day.complete && portion.complete;
        }
      }
      const list = [...days.values()]
        .sort((a, b) => a.date.localeCompare(b.date))
        .map((day) =>
          day.covers === 0
            ? { ...day, kcal: null, proteinG: null }
            : { ...day, proteinG: Math.round(day.proteinG ?? 0), kcalPerCover: Math.round((day.kcal ?? 0) / day.covers) },
        );
      const counted = list.filter((day) => day.kcal != null);
      const planned = counted.length ? counted.reduce((sum, day) => sum + (day.kcal ?? 0), 0) : null;
      // Sample: a week with a plan has four order lines so far, one without a nutrition table.
      const ordered = planned == null ? null : Math.round(planned * 0.62);
      return {
        from,
        to,
        days: list,
        planned: { kcal: planned, complete: list.length > 0 && list.every((day) => day.complete) },
        ordered:
          ordered == null
            ? { kcal: null, lines: 0, knownLines: 0, unknown: [] }
            : { kcal: ordered, lines: 4, knownLines: 3, unknown: ["OWN-RYE"] },
        orderedVsPlanned: ordered == null ? null : 0.62,
        note: "Ordered energy is what the approved orders for this window contain; planned energy is covers x recipe portions. Stock on hand is not in either number.",
      };
    },
  };
}
