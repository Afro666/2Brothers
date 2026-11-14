import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { collectFinnishDictionaries } from "@/lib/i18n";
import { PRODUCT_PAGE_TEXTS } from "@/pages/product";
import { renderApp } from "@/test/render";

function section(name: string): HTMLElement {
  return screen.getByRole("heading", { level: 2, name }).closest("section")!;
}

describe("product page", () => {
  beforeEach(() => localStorage.clear());

  it("shows what it is, the allergens, live price, VAT and the cheapest supplier", async () => {
    renderApp("/catalog/461903");

    expect(await screen.findByRole("heading", { level: 1, name: "Salmon fillet A, ASC, skin on" })).toBeInTheDocument();
    expect(within(section("What it is")).getByText(/Salmo salar/)).toBeInTheDocument();

    const allergens = section("Allergens");
    expect(within(allergens).getByText("fish")).toBeInTheDocument();
    expect(within(allergens).getByText("gluten")).toBeInTheDocument();

    const price = section("Price, stock and VAT");
    expect(within(price).getByText("13.5 %")).toBeInTheDocument();
    expect(within(price).getByText(/Source: Valio price and availability API · Valio product data, vatCode/)).toBeInTheDocument();

    const suppliers = section("Suppliers");
    const rows = within(suppliers).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    const cheapest = rows.find((row) => row.hasAttribute("data-cheapest"))!;
    expect(within(cheapest).getByText("Baltic Catch Fish Wholesale (demo)")).toBeInTheDocument();
    expect(within(cheapest).getByText("Cheapest")).toBeInTheDocument();

    const kitchen = section("This kitchen");
    expect(within(kitchen).getByText("Salmon soup")).toBeInTheDocument();
    expect(within(kitchen).getByRole("link", { name: /ORD-1042/ })).toHaveAttribute("href", "/orders/ORD-1042");
  });

  it("says unknown plainly when the VAT code and the allergen data are missing", async () => {
    renderApp("/catalog/464179");

    expect(await screen.findByRole("heading", { level: 1, name: "Arla lactose free milk drink 10 L novobox ESL" })).toBeInTheDocument();
    expect(screen.getByText(/1 piece = 10 l/)).toBeInTheDocument();
    const price = section("Price, stock and VAT");
    expect(within(price).getByText("The catalog gives no VAT code for this product.")).toBeInTheDocument();
    expect(within(price).getByText("unknown: a person confirms")).toBeInTheDocument();
    const allergens = section("Allergens");
    expect(within(allergens).getByText(/Allergens not known/)).toBeInTheDocument();
    expect(within(allergens).queryByText(/none/i)).toBeNull();
  });

  it("says when a code is no product", async () => {
    renderApp("/catalog/000000");
    expect(await screen.findByText("Product not found")).toBeInTheDocument();
  });

  it("opens from a catalog card's product name", async () => {
    renderApp("/catalog?q=milk");
    const link = await screen.findByRole("link", { name: "Arla lactose free milk drink 10 L novobox ESL" });
    expect(link).toHaveAttribute("href", "/catalog/464179");
  });

  it("has a Finnish entry for every text on the page", () => {
    const files = import.meta.glob("../i18n/fi/*.ts", { eager: true }) as Record<string, { default: Record<string, string> }>;
    const dictionary = collectFinnishDictionaries(files);
    const source = readFileSync(resolve(process.cwd(), "src/pages/product.tsx"), "utf8");
    const texts = [...source.matchAll(/\bt\(\s*"((?:\\.|[^"\\])*)"/g)].map((match) => JSON.parse(`"${match[1]}"`) as string);
    texts.push(...Object.values(PRODUCT_PAGE_TEXTS).flatMap((group) => Object.values(group)));
    expect(texts.filter((text) => !Object.prototype.hasOwnProperty.call(dictionary, text))).toEqual([]);
  });
});
