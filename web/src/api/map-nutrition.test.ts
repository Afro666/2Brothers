import { describe, expect, it } from "vitest";

import { mapNutrition, mapRecipeNutrition } from "@/api/map-nutrition";

const recipe = {
  recipe_id: "rec-1",
  name: "Salmon soup",
  per_portion: {
    kcal: "540",
    protein_g: "31.2",
    fat_g: "28.4",
    saturated_fat_g: "9.7",
    carbs_g: "36.5",
    sugar_g: "6.2",
    salt_g: "1.4",
  },
  known_ingredients: 2,
  unknown: [{ product_id: "own-1", product_name: null }],
  complete: false,
  plausible: true,
  source: "the products' own nutrition tables (GS1), per 100 g or 100 ml",
};

const window = {
  from: "2026-11-16",
  to: "2026-11-22",
  days: [
    { date: "2026-11-16", covers: 180, kcal: "144000", protein_g: "6700", kcal_per_cover: "800", complete: true },
    { date: "2026-11-17", covers: 0, kcal: "0", protein_g: "0", kcal_per_cover: null, complete: false },
  ],
  planned: { kcal: "144000", complete: false },
  ordered: { kcal: "89280", protein_g: "3100.5", lines: 4, known_lines: 3, unknown: ["own-1"] },
  ordered_vs_planned: "0.62",
  note: "Stock on hand is not in either number.",
};

describe("recipe nutrition", () => {
  it("maps one portion; a nutrient the labels leave out is null, never zero", () => {
    expect(mapRecipeNutrition(recipe)).toEqual({
      recipeId: "rec-1",
      name: "Salmon soup",
      perPortion: {
        kcal: 540,
        proteinG: 31.2,
        fatG: 28.4,
        saturatedFatG: 9.7,
        carbsG: 36.5,
        sugarG: 6.2,
        fibreG: null,
        saltG: 1.4,
      },
      knownIngredients: 2,
      unknown: [{ productId: "own-1", productName: "own-1" }],
      complete: false,
      plausible: true,
      source: "the products' own nutrition tables (GS1), per 100 g or 100 ml",
    });
  });

  it("keeps a recipe with nothing counted as all unknown", () => {
    const empty = mapRecipeNutrition({ ...recipe, per_portion: {}, known_ingredients: 0 });
    expect(Object.values(empty.perPortion).every((value) => value === null)).toBe(true);
  });

  it("reads plausible: false, and takes a gateway that does not send it as not checked", () => {
    expect(mapRecipeNutrition({ ...recipe, plausible: false }).plausible).toBe(false);
    expect(mapRecipeNutrition({ ...recipe, plausible: undefined }).plausible).toBe(true);
  });

  it.each([
    ["a nutrient that is a number", { ...recipe, per_portion: { kcal: 540 } }],
    ["no per_portion", { ...recipe, per_portion: undefined }],
    ["a count that is text", { ...recipe, known_ingredients: "2" }],
    ["unknown that is not a list", { ...recipe, unknown: null }],
    ["complete that is not a boolean", { ...recipe, complete: "no" }],
    ["plausible that is not a boolean", { ...recipe, plausible: "no" }],
    ["a list", [recipe]],
  ])("refuses %s", (_, body) => {
    expect(() => mapRecipeNutrition(body)).toThrow(expect.objectContaining({ code: "INVALID_RESPONSE" }));
  });
});

describe("window nutrition", () => {
  it("maps the days, the plan and the orders", () => {
    expect(mapNutrition(window)).toEqual({
      from: "2026-11-16",
      to: "2026-11-22",
      days: [
        { date: "2026-11-16", covers: 180, kcal: 144000, proteinG: 6700, kcalPerCover: 800, complete: true },
        // Nothing of this day could be counted: unknown, not 0 kcal.
        { date: "2026-11-17", covers: 0, kcal: null, proteinG: null, kcalPerCover: null, complete: false },
      ],
      planned: { kcal: 144000, complete: false },
      ordered: { kcal: 89280, lines: 4, knownLines: 3, unknown: ["own-1"] },
      orderedVsPlanned: 0.62,
      note: "Stock on hand is not in either number.",
    });
  });

  it("keeps a window with no menu and no orders unknown, never zero", () => {
    const empty = mapNutrition({
      ...window,
      days: [],
      planned: { kcal: "0", complete: false },
      ordered: { lines: 0, known_lines: 0, unknown: [] },
      ordered_vs_planned: null,
    });
    expect(empty.planned.kcal).toBeNull();
    expect(empty.ordered).toEqual({ kcal: null, lines: 0, knownLines: 0, unknown: [] });
    expect(empty.orderedVsPlanned).toBeNull();
  });

  it("keeps a planned sum of 0 unknown when no day could be counted", () => {
    const uncounted = mapNutrition({ ...window, days: [window.days[1]], planned: { kcal: "0", complete: false } });
    expect(uncounted.planned.kcal).toBeNull();
  });

  it("keeps a real 0 of a fully counted plan", () => {
    const day = { date: "2026-11-16", covers: 0, kcal: "0", protein_g: "0", kcal_per_cover: null, complete: true };
    const zero = mapNutrition({ ...window, days: [day], planned: { kcal: "0", complete: true } });
    expect(zero.planned.kcal).toBe(0);
    expect(zero.days[0].kcal).toBe(0);
    expect(zero.days[0].kcalPerCover).toBeNull();
  });

  it.each([
    ["days that are not a list", { ...window, days: null }],
    ["covers that are text", { ...window, days: [{ ...window.days[0], covers: "180" }] }],
    ["kcal that is a number", { ...window, days: [{ ...window.days[0], kcal: 144000 }] }],
    ["no planned", { ...window, planned: undefined }],
    ["no ordered line count", { ...window, ordered: { known_lines: 0, unknown: [] } }],
    ["a ratio that is a number", { ...window, ordered_vs_planned: 0.62 }],
  ])("refuses %s", (_, body) => {
    expect(() => mapNutrition(body)).toThrow(expect.objectContaining({ code: "INVALID_RESPONSE" }));
  });
});
