import { configure, getConfig, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { packLabel } from "@/pages/products";
import { renderApp } from "@/test/render";

describe("ProductsPage after jury 3", () => {
  let asyncUtilTimeout: number;
  beforeAll(() => {
    asyncUtilTimeout = getConfig().asyncUtilTimeout;
    configure({ asyncUtilTimeout: 10_000 });
  });
  afterAll(() => configure({ asyncUtilTimeout }));
  beforeEach(() => localStorage.clear());

  it("names the open tab in its title and never calls the tab Products again", async () => {
    renderApp("/products", createMockApi());

    expect(await screen.findByRole("tab", { name: "Own supplier products" })).toHaveAttribute("data-state", "active");
    expect(screen.getByRole("heading", { level: 1, name: "Own supplier products" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Products" })).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("tab", { name: "Recipes" }));
    expect(screen.getByRole("heading", { level: 1, name: "Recipes" })).toBeInTheDocument();
  });

  it("shows the pack size with its unit, not a unit code", async () => {
    renderApp("/products", createMockApi());

    const salmon = (await screen.findByText("Salmon fillet")).closest("[data-slot=card]");
    expect(within(salmon as HTMLElement).getByText("1 kg · not set")).toBeInTheDocument();
    const bread = screen.getByText("Rye bread loaf").closest("[data-slot=card]");
    expect(within(bread as HTMLElement).getByText("1 piece = 0.8 kg · €4.20")).toBeInTheDocument();
  });

  it("never prints a pack number without its measure", () => {
    expect(packLabel({ unit: "ST", packSize: null, packMeasure: null })).toBe("piece");
    expect(packLabel({ unit: "ST", packSize: 5, packMeasure: null })).toBe("piece (pack size unknown)");
    expect(packLabel({ unit: "ST", packSize: 5, packMeasure: "KG" })).toBe("1 piece = 5 kg");
    expect(packLabel({ unit: "KG", packSize: 5, packMeasure: "KG" })).toBe("5 kg");
  });

  it("keeps the row Delete quiet until the confirm dialog", async () => {
    const user = userEvent.setup();
    renderApp("/products", createMockApi());

    const bread = (await screen.findByText("Rye bread loaf")).closest("[data-slot=card]");
    const rowDelete = within(bread as HTMLElement).getByRole("button", { name: "Delete Rye bread loaf" });
    expect(rowDelete).toHaveAttribute("data-variant", "outline");

    await user.click(rowDelete);
    const dialog = await screen.findByRole("dialog", { name: "Delete product?" });
    expect(within(dialog).getByRole("button", { name: "Delete" })).toHaveAttribute("data-variant", "destructive");
  });

  it("does not point to a word above when there are no words", async () => {
    const api = createMockApi();
    api.getKitchenWords = async () => ({ aliases: [], unknownItems: [] });
    renderApp("/products", api);

    expect(
      await screen.findByText("No own names yet. They appear here when you link a word of a request to a product."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Link a word above/)).not.toBeInTheDocument();
  });
});
