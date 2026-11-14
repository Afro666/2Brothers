import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { createMockApi } from "@/api/mock";

const K = "/api/v1/kitchens/demo-kitchen";
type Handler = (body: Record<string, unknown>) => unknown;
interface Call {
  route: string;
  body: Record<string, unknown>;
}

/** A fake gateway: `"PUT /path"` -> the JSON it answers. Returns the calls it received. */
function gateway(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    const route = `${init.method ?? "GET"} ${url}`;
    const body = init.body ? JSON.parse(init.body as string) : {};
    calls.push({ route, body });
    const answer = routes[route]
      ? routes[route](body)
      : new Response(JSON.stringify({ error: { code: "NO_ROUTE", message: route } }), { status: 404 });
    return answer instanceof Response ? answer : new Response(JSON.stringify(answer));
  });
  return calls;
}

const refusal = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ error: { code, message } }), { status });

const recipeAnswer = {
  recipe_id: "rec/1",
  name: "Rice pudding",
  per_portion: { kcal: "320", protein_g: "9.5" },
  known_ingredients: 1,
  unknown: [],
  complete: true,
  plausible: true,
  source: "labels",
};
const windowAnswer = {
  from: "2026-11-16",
  to: "2026-11-22",
  days: [{ date: "2026-11-16", covers: 180, kcal: "57600", protein_g: "1710", kcal_per_cover: "320", complete: true }],
  planned: { kcal: "57600", complete: true },
  ordered: { lines: 0, known_lines: 0, unknown: [] },
  ordered_vs_planned: null,
  note: "",
};

afterEach(() => vi.unstubAllGlobals());

describe("nutrition and words on the real gateway", () => {
  it("marks the five methods as live", () => {
    const live = createHttpApi("/api").live!;
    for (const method of ["getRecipeNutrition", "getNutrition", "getKitchenWords", "linkWord", "forgetWord"] as const) {
      expect(live.has(method), method).toBe(true);
    }
  });

  it("reads one recipe's nutrition", async () => {
    const calls = gateway({ [`GET ${K}/recipes/rec%2F1/nutrition`]: () => recipeAnswer });
    const nutrition = await createHttpApi("/api").getRecipeNutrition("rec/1");
    expect(nutrition.perPortion).toMatchObject({ kcal: 320, proteinG: 9.5, fatG: null });
    expect(nutrition.complete).toBe(true);
    expect(calls.map((call) => call.route)).toEqual([`GET ${K}/recipes/rec%2F1/nutrition`]);
  });

  it("reads the nutrition of a window", async () => {
    const route = `GET ${K}/nutrition?from=2026-11-16&to=2026-11-22`;
    const calls = gateway({ [route]: () => windowAnswer });
    const nutrition = await createHttpApi("/api").getNutrition("2026-11-16", "2026-11-22");
    expect(nutrition.days[0].kcalPerCover).toBe(320);
    expect(nutrition.planned).toEqual({ kcal: 57600, complete: true });
    expect(nutrition.ordered).toEqual({ kcal: null, lines: 0, knownLines: 0, unknown: [] });
    expect(calls.map((call) => call.route)).toEqual([route]);
  });

  it("passes the gateway's error on", async () => {
    gateway({ [`GET ${K}/recipes/gone/nutrition`]: () => refusal(404, "NOT_FOUND", "no such recipe") });
    await expect(createHttpApi("/api").getRecipeNutrition("gone")).rejects.toMatchObject({
      code: "NOT_FOUND",
      message: "no such recipe",
    });
  });

  it("lists the words, links one and forgets one", async () => {
    const calls = gateway({
      [`GET ${K}/aliases`]: () => ({
        aliases: [],
        unknown_items: [{ phrase: "house milk", times: 2, first_asked: null, last_asked: null }],
      }),
      [`PUT ${K}/aliases`]: () => ({ phrase: "house milk", product_id: "463335", product_name: "Milk", set_by: "aino" }),
      [`DELETE ${K}/aliases?phrase=oat%20%26%20barista`]: () => ({ deleted: true }),
    });
    const api = createHttpApi("/api");
    expect((await api.getKitchenWords()).unknownItems).toEqual([
      { phrase: "house milk", times: 2, firstAsked: null, lastAsked: null, suggestions: null, suggestedBy: null },
    ]);
    await api.linkWord("house milk", "463335");
    await api.forgetWord("oat & barista");
    expect(calls).toEqual([
      { route: `GET ${K}/aliases`, body: {} },
      { route: `PUT ${K}/aliases`, body: { phrase: "house milk", product_id: "463335" } },
      { route: `DELETE ${K}/aliases?phrase=oat%20%26%20barista`, body: {} },
    ]);
  });

  it("passes a refused link on", async () => {
    gateway({ [`PUT ${K}/aliases`]: () => refusal(422, "INVALID_REQUEST", "no such product for this kitchen") });
    await expect(createHttpApi("/api").linkWord("house milk", "nope")).rejects.toMatchObject({
      code: "INVALID_REQUEST",
      message: "no such product for this kitchen",
    });
  });
});

describe("nutrition on the mock", () => {
  it("serves sample numbers per portion, between 300 and 900 kcal", async () => {
    const api = createMockApi();
    for (const recipe of await api.listRecipes()) {
      const nutrition = await api.getRecipeNutrition(recipe.id);
      expect(nutrition.perPortion.kcal).toBeGreaterThanOrEqual(300);
      expect(nutrition.perPortion.kcal).toBeLessThanOrEqual(900);
      expect(nutrition.knownIngredients + nutrition.unknown.length).toBe(recipe.items.length);
      expect(nutrition.complete).toBe(nutrition.unknown.length === 0);
    }
  });

  it("knows nothing about a recipe a person added, and refuses an unknown id", async () => {
    const api = createMockApi();
    const added = await api.saveRecipe({
      name: "New dish",
      items: [{ productId: "OWN-RYE", productName: "Rye bread loaf", unit: "PCS", qtyPerPortion: 1 }],
    });
    const nutrition = await api.getRecipeNutrition(added.id);
    expect(nutrition.perPortion.kcal).toBeNull();
    expect(nutrition).toMatchObject({ knownIngredients: 0, complete: false });
    await expect(api.getRecipeNutrition("nope")).rejects.toMatchObject({ code: "NOT_FOUND" });
  });

  it("adds the planned week up from the menu plan", async () => {
    const nutrition = await createMockApi().getNutrition("2026-11-16", "2026-11-22");
    // Monday: salmon soup 160 x 540, rice pudding 180 x 320, coffee service 120 x 310.
    expect(nutrition.days[0]).toMatchObject({
      date: "2026-11-16",
      covers: 180,
      kcal: 181200,
      kcalPerCover: 1007,
      complete: false,
    });
    const planned = nutrition.days.reduce((sum, day) => sum + (day.kcal ?? 0), 0);
    expect(nutrition.planned).toEqual({ kcal: planned, complete: false });
    expect(nutrition.ordered.lines).toBeGreaterThan(0);
    expect(nutrition.orderedVsPlanned).toBe(0.62);
  });

  it("says nothing is planned or ordered for a week without a menu", async () => {
    const nutrition = await createMockApi().getNutrition("2026-11-23", "2026-11-29");
    expect(nutrition.days).toEqual([]);
    expect(nutrition.planned.kcal).toBeNull();
    expect(nutrition.ordered).toMatchObject({ kcal: null, lines: 0 });
    expect(nutrition.orderedVsPlanned).toBeNull();
  });
});

describe("words on the mock", () => {
  it("links an unknown word to a product, which clears it from the unknown list", async () => {
    const api = createMockApi();
    const before = await api.getKitchenWords();
    expect(before.unknownItems.map((item) => item.phrase)).toContain("house milk");
    await api.linkWord("House  Milk!", "462775");
    const after = await api.getKitchenWords();
    expect(after.unknownItems.map((item) => item.phrase)).not.toContain("house milk");
    expect(after.aliases.find((alias) => alias.phrase === "house milk")).toMatchObject({
      productId: "462775",
      productName: "Arla 1 L lactose free fat free UHT milk drink",
      uses: 0,
    });
  });

  it("refuses a product it does not know and a phrase that is too short", async () => {
    const api = createMockApi();
    await expect(api.linkWord("house milk", "nope")).rejects.toMatchObject({ code: "INVALID_REQUEST" });
    await expect(api.linkWord("?", "462775")).rejects.toMatchObject({ code: "INVALID_REQUEST" });
  });

  it("forgets an unknown word and removes an own name", async () => {
    const api = createMockApi();
    const { aliases, unknownItems } = await api.getKitchenWords();
    await api.forgetWord(unknownItems[0].phrase);
    await api.forgetWord(aliases[0].phrase);
    const after = await api.getKitchenWords();
    expect(after.unknownItems).toHaveLength(unknownItems.length - 1);
    expect(after.aliases).toHaveLength(aliases.length - 1);
    await expect(api.forgetWord("never asked")).rejects.toMatchObject({ code: "NOT_FOUND" });
  });
});
