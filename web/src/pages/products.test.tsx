import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";
import { PICKER_DEBOUNCE_MS } from "@/pages/products/product-picker";

describe("ProductsPage", () => {
  beforeEach(() => localStorage.clear());

  it("shows seeded products with suppliers and unknown allergen data", async () => {
    renderApp("/products", createMockApi());
    expect(await screen.findByText("Rye bread loaf")).toBeInTheDocument();
    expect(screen.getAllByText("Töölö Bakery").length).toBeGreaterThan(0);
    const bun = screen.getByText("Cinnamon bun").closest("[data-slot='card-content']");
    expect(bun).toHaveTextContent("Allergen data missing: unknown");
  });

  it("saves a new product with unknown allergens as null", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/products", api);
    await user.click(await screen.findByRole("button", { name: "Add product" }));
    const dialog = await screen.findByRole("dialog", { name: "Add product" });
    await user.type(within(dialog).getByLabelText("Name"), "Test item");
    await user.type(within(dialog).getByLabelText("Unit"), "PCS");
    await user.click(within(dialog).getByRole("button", { name: "Save product" }));
    expect(await screen.findByText("Test item")).toBeInTheDocument();
    expect((await api.listOwnProducts()).find((product) => product.name === "Test item")?.allergens).toBeNull();
  });

  it("still opens and closes the product dialog when another dialog node is in the document", async () => {
    const user = userEvent.setup();
    const stray = document.createElement("div");
    stray.setAttribute("role", "dialog");
    document.body.appendChild(stray);
    try {
      renderApp("/products", createMockApi());
      await user.click(await screen.findByRole("button", { name: "Add product" }));
      const dialog = await screen.findByRole("dialog", { name: "Add product" });
      await user.type(within(dialog).getByLabelText("Name"), "Stray item");
      await user.type(within(dialog).getByLabelText("Unit"), "PCS");
      await user.click(within(dialog).getByRole("button", { name: "Save product" }));
      await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add product" })).not.toBeInTheDocument());
    } finally {
      stray.remove();
    }
  });

  it("preserves allergens the editor does not display when saving an edit", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const rye = (await api.listOwnProducts()).find((product) => product.name === "Rye bread loaf")!;
    await api.saveOwnProduct({
      ...rye,
      allergens: [{ code: "CUSTOM", name: "Custom allergen", presence: "MAY_CONTAIN" }],
    });
    renderApp("/products", api);
    const row = (await screen.findByText("Rye bread loaf")).closest("[data-slot='card-content']");
    await user.click(within(row as HTMLElement).getByRole("button", { name: "Edit Rye bread loaf" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit product" });
    await user.clear(within(dialog).getByLabelText("Name"));
    await user.type(within(dialog).getByLabelText("Name"), "Rye loaf updated");
    await user.click(within(dialog).getByRole("button", { name: "Save product" }));
    expect((await api.listOwnProducts()).find((product) => product.name === "Rye loaf updated")?.allergens).toEqual([
      { code: "CUSTOM", name: "Custom allergen", presence: "MAY_CONTAIN" },
    ]);
  });

  it("keeps fractional recipe quantity input intact and validates positive quantity on save", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/products", api);
    await user.click(await screen.findByRole("tab", { name: "Recipes" }));
    await user.click(await screen.findByRole("button", { name: "Add recipe" }));
    const dialog = await screen.findByRole("dialog", { name: "Add recipe" });
    await user.type(within(dialog).getByLabelText("Name"), "Fractional recipe");
    await user.click(within(dialog).getByRole("button", { name: "Add item" }));
    await user.type(within(dialog).getByRole("searchbox", { name: "Find a product" }), "Rye");
    await user.click(await within(dialog).findByRole("button", { name: /Rye bread loaf/ }));
    const quantity = within(dialog).getByLabelText("Quantity per portion");
    await user.type(quantity, "0");
    expect(quantity).toHaveValue("0");
    await user.click(within(dialog).getByRole("button", { name: "Save recipe" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("greater than 0");
    expect((await api.listRecipes()).some((recipe) => recipe.name === "Fractional recipe")).toBe(false);
    await user.clear(quantity);
    await user.type(quantity, "0.25");
    // Verify the parsed numeric value reaches the API.
    await user.click(within(dialog).getByRole("button", { name: "Save recipe" }));
    expect(
      (await api.listRecipes()).find((recipe) => recipe.name === "Fractional recipe")?.items[0].qtyPerPortion,
    ).toBe(0.25);
  });

  it("reads a recipe quantity typed with a decimal comma", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/products", api);
    await user.click(await screen.findByRole("tab", { name: "Recipes" }));
    await user.click(await screen.findByRole("button", { name: "Add recipe" }));
    const dialog = await screen.findByRole("dialog", { name: "Add recipe" });
    await user.type(within(dialog).getByLabelText("Name"), "Comma recipe");
    await user.click(within(dialog).getByRole("button", { name: "Add item" }));
    await user.type(within(dialog).getByRole("searchbox", { name: "Find a product" }), "Rye");
    await user.click(await within(dialog).findByRole("button", { name: /Rye bread loaf/ }));
    const quantity = within(dialog).getByLabelText("Quantity per portion");
    expect(quantity).toHaveAccessibleDescription("PCS");
    await user.type(quantity, "0,2");
    await user.click(within(dialog).getByRole("button", { name: "Save recipe" }));
    expect(await screen.findByText("Comma recipe")).toBeInTheDocument();
    expect((await api.listRecipes()).find((recipe) => recipe.name === "Comma recipe")?.items[0].qtyPerPortion).toBe(
      0.2,
    );
  });

  it("keeps typed search text on its own row when a row above is removed", async () => {
    const user = userEvent.setup();
    renderApp("/products", createMockApi());
    await user.click(await screen.findByRole("tab", { name: "Recipes" }));
    await user.click(await screen.findByRole("button", { name: "Add recipe" }));
    const dialog = await screen.findByRole("dialog", { name: "Add recipe" });
    await user.click(within(dialog).getByRole("button", { name: "Add item" }));
    await user.click(within(dialog).getByRole("button", { name: "Add item" }));
    await user.type(within(dialog).getAllByRole("searchbox", { name: "Find a product" })[1], "Rye");
    await user.click(within(dialog).getAllByRole("button", { name: "Remove" })[0]);
    expect(within(dialog).getByRole("searchbox", { name: "Find a product" })).toHaveValue("Rye");
  });

  it("shows the recipe name in its delete dialog after a product delete dialog was cancelled", async () => {
    const user = userEvent.setup();
    renderApp("/products", createMockApi());
    const productRow = (await screen.findByText("Rye bread loaf")).closest("[data-slot='card-content']");
    await user.click(within(productRow as HTMLElement).getByRole("button", { name: "Delete Rye bread loaf" }));
    let dialog = await screen.findByRole("dialog", { name: "Delete product?" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await user.click(await screen.findByRole("tab", { name: "Recipes" }));
    const recipeRow = (await screen.findByText("Salmon soup")).closest("[data-slot='card-content']");
    await user.click(within(recipeRow as HTMLElement).getByRole("button", { name: "Delete Salmon soup" }));
    dialog = await screen.findByRole("dialog", { name: "Delete recipe?" });
    expect(within(dialog).getByText("Delete Salmon soup?")).toBeInTheDocument();
  });

  it("shows recipe allergen rollups and unknown data", async () => {
    const user = userEvent.setup();
    renderApp("/products", createMockApi());
    await user.click(await screen.findByRole("tab", { name: "Recipes" }));
    const coffee = screen.getByText("Coffee service").closest("[data-slot='card-content']");
    const salmon = screen.getByText("Salmon soup").closest("[data-slot='card-content']");
    expect(coffee).toHaveTextContent("Allergen data missing: unknown");
    expect(salmon).toHaveTextContent("Fish");
    expect(salmon).toHaveTextContent("Gluten cereals");
  });

  it("shows the API in-use message when rye bread is deleted", async () => {
    const user = userEvent.setup();
    renderApp("/products", createMockApi());
    const row = (await screen.findByText("Rye bread loaf")).closest("[data-slot='card-content']");
    await user.click(within(row as HTMLElement).getByRole("button", { name: "Delete Rye bread loaf" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete product?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Rye bread loaf is used in a recipe.");
  });

  it("loads recipe products by id and finds a catalog product by typing, without an empty search", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const emptySearches: string[] = [];
    api.searchProducts = async (query) => {
      emptySearches.push(query);
      return query.trim().length < 2 ? [] : await createMockApi().searchProducts(query);
    };
    renderApp("/products", api);

    await user.click(await screen.findByRole("tab", { name: "Recipes" }));
    const coffee = (await screen.findByText("Coffee service")).closest("[data-slot='card-content']");
    const pudding = screen.getByText("Rice pudding").closest("[data-slot='card-content']");
    expect(coffee).toHaveTextContent("ContainsMilk");
    expect(coffee).toHaveTextContent("Allergen data missing: unknown");
    expect(pudding).toHaveTextContent("ContainsMilk");
    expect(pudding).not.toHaveTextContent("Allergen data missing");
    expect(emptySearches).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Add recipe" }));
    const dialog = await screen.findByRole("dialog", { name: "Add recipe" });
    await user.type(within(dialog).getByLabelText("Name"), "Catalog recipe");
    await user.click(within(dialog).getByRole("button", { name: "Add item" }));
    const search = within(dialog).getByRole("searchbox", { name: "Find a product" });
    await user.type(search, "o");
    expect(within(dialog).getByText("Type at least 2 characters to search.")).toBeInTheDocument();
    expect(emptySearches).toEqual([]);

    // Own products match locally, at once and without a catalog search.
    await user.clear(search);
    await user.type(search, "bread");
    expect(await within(dialog).findByRole("button", { name: /Rye bread loaf/ })).toHaveTextContent(
      "own · Töölö Bakery",
    );

    await user.clear(search);
    await user.type(search, "organic");
    await new Promise((resolve) => setTimeout(resolve, PICKER_DEBOUNCE_MS / 2));
    const options = await within(dialog).findAllByRole(
      "button",
      { name: /Valio Oy/ },
      { timeout: PICKER_DEBOUNCE_MS + 2000 },
    );
    expect(options).toHaveLength(1);
    const [option] = options;
    expect(option).toHaveTextContent("Valio Eila organic lactose free milk drink 1 L");
    expect(option).toHaveTextContent("L · Valio Oy");
    await user.click(option);
    expect(within(dialog).queryByRole("searchbox", { name: "Find a product" })).not.toBeInTheDocument();
    expect(within(dialog).getByText("L · Valio Oy")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /Change product, currently Valio Eila organic/ }));
    expect(within(dialog).getByRole("searchbox", { name: "Find a product" })).toBeInTheDocument();
    await user.type(within(dialog).getByRole("searchbox", { name: "Find a product" }), "organic");
    const catalogOption = await within(dialog).findByRole(
      "button",
      { name: /Valio Eila organic/ },
      { timeout: PICKER_DEBOUNCE_MS + 2000 },
    );
    await user.click(catalogOption);

    await user.type(within(dialog).getByLabelText("Quantity per portion"), "0.2");
    await user.click(within(dialog).getByRole("button", { name: "Save recipe" }));
    expect(await screen.findByText("Catalog recipe")).toBeInTheDocument();
    expect((await api.listRecipes()).find((recipe) => recipe.name === "Catalog recipe")?.items[0]).toMatchObject({
      productId: "462921",
      productName: "Valio Eila organic lactose free milk drink 1 L",
      unit: "L",
      qtyPerPortion: 0.2,
    });
    // Only the settled query is searched: no call per keystroke.
    expect(emptySearches).toEqual(["organic", "organic"]);
  });
});
