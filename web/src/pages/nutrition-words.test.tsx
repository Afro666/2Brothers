import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { ApiError, type KitchenNutrition, type RecipeNutrition } from "@/api/types";
import { formatNumber } from "@/lib/format";
import { renderApp } from "@/test/render";

async function recipeCard(name: string): Promise<HTMLElement> {
  const user = userEvent.setup();
  await user.click(await screen.findByRole("tab", { name: "Recipes" }));
  return (await screen.findByText(name)).closest("[data-slot='card-content']") as HTMLElement;
}

describe("nutrition on the recipes tab", () => {
  beforeEach(() => localStorage.clear());

  it("shows energy and macros per portion, and what an incomplete count left out", async () => {
    renderApp("/products", createMockApi());

    const pudding = await recipeCard("Rice pudding");
    expect(await within(pudding).findByText("320 kcal per portion")).toBeInTheDocument();
    expect(pudding).toHaveTextContent("protein 9.5 g · fat 9.8 g · carbs 47.2 g · salt 0.3 g");
    expect(pudding).not.toHaveTextContent("counted from");

    const soup = screen.getByText("Salmon soup").closest("[data-slot='card-content']") as HTMLElement;
    expect(await within(soup).findByText(/540 kcal per portion/)).toBeInTheDocument();
    expect(soup).toHaveTextContent("counted from 2 of 3 ingredients");
    expect(soup).toHaveTextContent("No nutrition table: Rye bread loaf");
  });

  it("hides the number and asks to check the units when the gateway says it is not plausible", async () => {
    const api = createMockApi();
    const real = api.getRecipeNutrition;
    api.getRecipeNutrition = async (id): Promise<RecipeNutrition> => {
      const nutrition = await real(id);
      return id === "REC-RICE-PUDDING"
        ? { ...nutrition, perPortion: { ...nutrition.perPortion, kcal: 48000 }, plausible: false }
        : nutrition;
    };
    renderApp("/products", api);

    const pudding = await recipeCard("Rice pudding");
    expect(await within(pudding).findByText("This looks wrong: check the units in this recipe.")).toBeInTheDocument();
    expect(pudding).not.toHaveTextContent("kcal");
  });

  it("still shows the recipe when its nutrition cannot be loaded", async () => {
    const api = createMockApi();
    api.getRecipeNutrition = () => Promise.reject(new ApiError("NETWORK", "Could not reach the gateway."));
    renderApp("/products", api);

    const pudding = await recipeCard("Rice pudding");
    expect(await within(pudding).findByText("Nutrition is not available right now.")).toBeInTheDocument();
    expect(within(pudding).getByRole("button", { name: "Edit Rice pudding" })).toBeEnabled();
    expect(pudding).toHaveTextContent("1 item");
  });

  it("says not known, never 0, when no ingredient has a nutrition table", async () => {
    const api = createMockApi();
    await api.saveRecipe({
      name: "New dish",
      items: [{ productId: "OWN-RYE", productName: "Rye bread loaf", unit: "PCS", qtyPerPortion: 1 }],
    });
    renderApp("/products", api);

    const dish = await recipeCard("New dish");
    expect(await within(dish).findByText("Nutrition not known")).toBeInTheDocument();
    expect(dish).toHaveTextContent("No nutrition table: Rye bread loaf");
    expect(dish).not.toHaveTextContent("kcal");
  });
});

describe("energy on the planner", () => {
  beforeEach(() => localStorage.clear());

  it("shows energy per cover under a day and the week's planned and ordered energy", async () => {
    const api = createMockApi();
    const nutrition = await api.getNutrition("2026-11-16", "2026-11-22");
    renderApp("/planner?week=2026-W47", api);

    const monday = (await screen.findByRole("heading", { name: /Monday/ })).closest("[data-slot='card']") as HTMLElement;
    expect(await within(monday).findByText("about 1,007 kcal per cover · partly counted")).toBeInTheDocument();
    // A day without menu entries has no energy line.
    const sunday = screen.getByRole("heading", { name: /Sunday/ }).closest("[data-slot='card']") as HTMLElement;
    expect(sunday).not.toHaveTextContent("kcal");

    const summary = await screen.findByText(/^Planned: /);
    expect(summary).toHaveTextContent(`Planned: ${formatNumber(nutrition.planned.kcal!)} kcal.`);
    expect(summary).toHaveTextContent(
      `Ordered for this week so far: ${formatNumber(nutrition.ordered.kcal!)} kcal (62% of the plan).`,
    );
    expect(summary).toHaveTextContent("Counted from 3 of 4 order lines.");
  });

  it("says that nothing is ordered for a week without orders", async () => {
    renderApp("/planner?week=2026-W48", createMockApi());

    const summary = await screen.findByText(/Nothing ordered for this week yet\./);
    expect(summary).toHaveTextContent("No energy planned for this week yet. Nothing ordered for this week yet.");
    expect(summary).not.toHaveTextContent("kcal");
  });

  it("names what it could not count instead of showing 0", async () => {
    const api = createMockApi();
    const unknown: KitchenNutrition = {
      from: "2026-11-16",
      to: "2026-11-22",
      days: [{ date: "2026-11-16", covers: 0, kcal: null, proteinG: null, kcalPerCover: null, complete: false }],
      planned: { kcal: null, complete: false },
      ordered: { kcal: null, lines: 2, knownLines: 0, unknown: ["a", "b"] },
      orderedVsPlanned: null,
      note: "",
    };
    api.getNutrition = async () => unknown;
    renderApp("/planner?week=2026-W47", api);

    const summary = await screen.findByText(/^Planned: /);
    expect(summary).toHaveTextContent("Planned: energy not known. Ordered for this week so far: energy not known.");
    const monday = screen.getByRole("heading", { name: /Monday/ }).closest("[data-slot='card']") as HTMLElement;
    expect(within(monday).getByText("Energy per cover not known")).toBeInTheDocument();
    expect(screen.queryByText(/\b0 kcal/)).not.toBeInTheDocument();
  });

  it("still shows the plan when the energy cannot be loaded", async () => {
    const api = createMockApi();
    api.getNutrition = () => Promise.reject(new ApiError("NETWORK", "Could not reach the gateway."));
    renderApp("/planner?week=2026-W47", api);

    expect(await screen.findByText("Energy numbers are not available right now.")).toBeInTheDocument();
    const monday = screen.getByRole("heading", { name: /Monday/ }).closest("[data-slot='card']") as HTMLElement;
    expect(within(monday).getByText(/Rice pudding/)).toBeInTheDocument();
    expect(monday).not.toHaveTextContent("kcal");
  });

  it("hides a day's energy while that day has unsaved changes", async () => {
    const user = userEvent.setup();
    renderApp("/planner?week=2026-W47", createMockApi());

    const monday = (await screen.findByRole("heading", { name: /Monday/ })).closest("[data-slot='card']") as HTMLElement;
    await within(monday).findByText(/kcal per cover/);
    await user.click(within(monday).getAllByRole("button", { name: "Remove" })[0]);
    expect(monday).not.toHaveTextContent("kcal per cover");
    const tuesday = screen.getByRole("heading", { name: /Tuesday/ }).closest("[data-slot='card']") as HTMLElement;
    expect(tuesday).toHaveTextContent("kcal per cover");
  });
});

describe("the kitchen's words on the products tab", () => {
  beforeEach(() => localStorage.clear());

  it("lists the words that matched nothing and the kitchen's own names", async () => {
    renderApp("/products", createMockApi());

    const unknown = await screen.findByRole("region", { name: "Words we did not know" });
    const rows = within(unknown).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("house milk asked 3 times");
    expect(rows[1]).toHaveTextContent("oat barista asked 1 time");
    const names = screen.getByRole("region", { name: "Your own names for products" });
    expect(within(names).getByRole("listitem")).toHaveTextContent(
      "blue milk → goes toValio Eila 3 % lactose free milk drink 1 L used 4 times",
    );
  });

  it("links a word to a product found with the catalog search", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const link = vi.spyOn(api, "linkWord");
    renderApp("/products", api);

    await user.click(await screen.findByRole("button", { name: "Link “house milk” to a product" }));
    const search = screen.getByRole("searchbox", { name: "Find a product for “house milk”" });
    expect(search).toHaveFocus();
    await user.type(search, "Arla 1 L");
    await user.click(await screen.findByRole("button", { name: /Arla 1 L lactose free fat free UHT milk drink/ }));

    expect(
      await screen.findByText("“house milk” now goes to Arla 1 L lactose free fat free UHT milk drink"),
    ).toBeInTheDocument();
    expect(link).toHaveBeenCalledWith("house milk", "462775");
    const names = screen.getByRole("region", { name: "Your own names for products" });
    await waitFor(() => expect(names).toHaveTextContent("house milk"));
    expect(screen.getByRole("region", { name: "Words we did not know" })).not.toHaveTextContent("house milk");
    expect(screen.queryByRole("searchbox", { name: /Find a product for/ })).not.toBeInTheDocument();
  });

  it("forgets a word and removes an own name, down to the empty states", async () => {
    const user = userEvent.setup();
    renderApp("/products", createMockApi());

    await user.click(await screen.findByRole("button", { name: "Forget “house milk”" }));
    expect(await screen.findByText("“house milk” forgotten")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Forget “oat barista”" }));
    expect(await screen.findByText("Nothing asked for that we did not find.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Remove the name “blue milk”" }));
    expect(await screen.findByText("“blue milk” removed")).toBeInTheDocument();
    expect(
      await screen.findByText("No own names yet. Link a word above, and a request that uses it goes to that product."),
    ).toBeInTheDocument();
  });

  it("shows the gateway's refusal and keeps the word", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    api.forgetWord = () => Promise.reject(new ApiError("FORBIDDEN", "A viewer cannot change the kitchen's words."));
    renderApp("/products", api);

    await user.click(await screen.findByRole("button", { name: "Forget “house milk”" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A viewer cannot change the kitchen's words.");
    expect(screen.getByRole("region", { name: "Words we did not know" })).toHaveTextContent("house milk");
  });

  it("keeps the own products on screen when the words cannot be loaded", async () => {
    const api = createMockApi();
    api.getKitchenWords = () => Promise.reject(new ApiError("NETWORK", "Could not reach the gateway."));
    renderApp("/products", api);

    expect(await screen.findByText("Rye bread loaf")).toBeInTheDocument();
    expect(await screen.findByText("Could not reach the gateway.")).toBeInTheDocument();
  });
});
