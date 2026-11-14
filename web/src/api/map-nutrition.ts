import { decimal, object, rows, text } from "@/api/gateway-map";
import { ApiError, type KitchenNutrition, type NutrientValues, type NutritionDay, type RecipeNutrition } from "@/api/types";

/**
 * The nutrition routes (gateway/nutrition_routes.py, engine/nutrition.py) to the UI types.
 *
 * The gateway sends each nutrient as a decimal string and leaves out what the labels do not
 * say. What it leaves out is null here: unknown, never zero. It adds up only what it could
 * count, so a sum of nothing arrives as "0"; that is null here too.
 */

function invalid(what: string): never {
  throw new ApiError("INVALID_RESPONSE", `The gateway sent ${what} in an unexpected shape.`);
}

function count(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) invalid(what);
  return value;
}

function flag(value: unknown, what: string): boolean {
  if (typeof value !== "boolean") invalid(what);
  return value;
}

function list(value: unknown, what: string): unknown[] {
  if (!Array.isArray(value)) invalid(what);
  return value;
}

const NUTRIENTS: [keyof NutrientValues, string][] = [
  ["kcal", "kcal"],
  ["proteinG", "protein_g"],
  ["fatG", "fat_g"],
  ["saturatedFatG", "saturated_fat_g"],
  ["carbsG", "carbs_g"],
  ["sugarG", "sugar_g"],
  ["fibreG", "fibre_g"],
  ["saltG", "salt_g"],
];

/** `GET /recipes/{id}/nutrition`. A gateway that does not send `plausible` has not checked: true. */
export function mapRecipeNutrition(body: unknown): RecipeNutrition {
  const row = object(body, "a recipe's nutrition");
  const portion = object(row.per_portion, "per_portion");
  const perPortion = Object.fromEntries(
    NUTRIENTS.map(([key, field]) => [key, decimal(portion[field], field)]),
  ) as unknown as NutrientValues;
  const recipeId = text(row.recipe_id, "a recipe_id");
  return {
    recipeId,
    name: typeof row.name === "string" && row.name ? row.name : recipeId,
    perPortion,
    knownIngredients: count(row.known_ingredients, "known_ingredients"),
    unknown: list(row.unknown, "the unknown ingredients").map((item) => {
      const product = object(item, "an unknown ingredient");
      const productId = text(product.product_id, "an ingredient product_id");
      return {
        productId,
        productName: typeof product.product_name === "string" && product.product_name ? product.product_name : productId,
      };
    }),
    complete: flag(row.complete, "complete"),
    plausible: row.plausible == null ? true : flag(row.plausible, "plausible"),
    source: typeof row.source === "string" ? row.source : "",
  };
}

/** A sum the gateway could not count fully and that is 0 has counted nothing: unknown. */
function counted(sum: number | null, complete: boolean): number | null {
  return sum === 0 && !complete ? null : sum;
}

function mapDay(row: Record<string, unknown>): NutritionDay {
  const complete = flag(row.complete, "a day's complete");
  return {
    date: text(row.date, "a day's date"),
    covers: count(row.covers, "a day's covers"),
    kcal: counted(decimal(row.kcal, "a day's kcal"), complete),
    proteinG: counted(decimal(row.protein_g, "a day's protein_g"), complete),
    kcalPerCover: decimal(row.kcal_per_cover, "kcal_per_cover"),
    complete,
  };
}

/**
 * `GET /nutrition?from=&to=`. `ordered.kcal` is absent when no order line could be counted,
 * and `ordered_vs_planned` is null when either side is unknown: both stay null.
 */
export function mapNutrition(body: unknown): KitchenNutrition {
  const row = object(body, "the nutrition");
  const days = rows(row, "days").map(mapDay);
  const planned = object(row.planned, "the planned nutrition");
  const ordered = object(row.ordered, "the ordered nutrition");
  const plannedComplete = flag(planned.complete, "planned.complete");
  return {
    from: text(row.from, "from"),
    to: text(row.to, "to"),
    days,
    planned: {
      kcal: days.length === 0 ? null : counted(decimal(planned.kcal, "planned.kcal"), plannedComplete),
      complete: plannedComplete,
    },
    ordered: {
      kcal: decimal(ordered.kcal, "ordered.kcal"),
      lines: count(ordered.lines, "ordered.lines"),
      knownLines: count(ordered.known_lines, "ordered.known_lines"),
      unknown: list(ordered.unknown ?? [], "ordered.unknown").map((id) => text(id, "an ordered product id")),
    },
    orderedVsPlanned: decimal(row.ordered_vs_planned, "ordered_vs_planned"),
    note: typeof row.note === "string" ? row.note : "",
  };
}
