import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

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
    const quantity = within(dialog).getAllByRole("textbox")[1];
    await user.click(within(dialog).getByRole("combobox", { name: "Product" }));
    await user.click(await screen.findByRole("option", { name: "Rye bread loaf" }));
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
});
