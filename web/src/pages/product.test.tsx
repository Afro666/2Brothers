import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { collectFinnishDictionaries } from "@/lib/i18n";
import { PRODUCT_PAGE_TEXTS } from "@/pages/product";
import { renderApp } from "@/test/render";

function section(name: string): HTMLElement {
  return screen.getByRole("heading", { level: 2, name }).closest("section")!;
}

describe("product page", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.useRealTimers());

  it("shows what it is, the allergens, live price, VAT and the cheapest supplier", async () => {
    renderApp("/catalog/461903");

    expect(await screen.findByRole("heading", { level: 1, name: "Salmon fillet A, ASC, skin on" })).toBeInTheDocument();
    expect(within(section("What it is")).getByText(/Salmo salar/)).toBeInTheDocument();

    const allergens = section("Allergens");
    expect(within(allergens).getByText("Fish")).toBeInTheDocument();
    expect(within(allergens).getByText("none declared")).toBeInTheDocument();
    expect(within(allergens).getByText("Gluten")).toBeInTheDocument();

    const price = section("Price, stock and VAT");
    expect(within(price).getByText("13.5 %")).toBeInTheDocument();
    expect(within(price).queryByText(/MEDIUM/)).toBeNull();
    expect(within(price).getByText(/Source: Valio price and availability API · Valio product data: VAT/)).toBeInTheDocument();
    expect(within(price).queryByText(/vatCode/)).toBeNull();

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
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-14T22:00:00Z"));
    renderApp("/catalog/464179");

    expect(await screen.findByRole("heading", { level: 1, name: "Arla lactose free milk drink 10 L novobox ESL" })).toBeInTheDocument();
    expect(screen.getByText(/1 piece = 10 l/)).toBeInTheDocument();
    const price = section("Price, stock and VAT");
    expect(within(price).getByText("The catalog gives no VAT code for this product.")).toBeInTheDocument();
    expect(within(price).getByText("not confirmed; the approver checks it on the proposal")).toBeInTheDocument();
    expect(within(price).getByText("cut-off passed")).toBeInTheDocument();
    expect(within(price).getByText("next: Mon 16 Nov, 17:00")).toBeInTheDocument();
    const about = section("What it is");
    expect(within(about).getByText("Supplier id 10400")).toBeInTheDocument();
    const allergens = section("Allergens");
    expect(within(allergens).getByText("Milk")).toBeInTheDocument();
    expect(within(allergens).getByText("none declared")).toBeInTheDocument();
  });

  it("shows the allergen names in Finnish, and no VAT code", async () => {
    localStorage.setItem("purchasing-language", "fi");
    renderApp("/catalog/464179");

    expect(await screen.findByRole("heading", { level: 1, name: "Arla lactose free milk drink 10 L novobox ESL" })).toBeInTheDocument();
    const allergens = section("Allergeenit");
    expect(within(allergens).getByText("Maito")).toBeInTheDocument();
    expect(within(allergens).getByText("Äyriäiset")).toBeInTheDocument();
    expect(within(allergens).getByText("Sulfiitit")).toBeInTheDocument();
    expect(within(allergens).queryByText(/crustaceans|sulphites/)).toBeNull();

    const price = section("Hinta, varasto ja alv");
    expect(within(price).getByText(/^Lähde: Valion hinta- ja saatavuusrajapinta/)).toBeInTheDocument();
    expect(within(price).queryByText(/vatCode/)).toBeNull();
    expect(within(price).queryByText(/MEDIUM/)).toBeNull();
  });

  it("names the delivery fee in full and units in words", async () => {
    renderApp("/catalog/461903");
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();

    const suppliers = section("Suppliers");
    const rows = within(suppliers).getAllByRole("row").slice(1);
    const cheapest = rows.find((row) => row.hasAttribute("data-cheapest"))!;
    expect(within(cheapest).getByText("€18.00 delivery under €150.00")).toBeInTheDocument();
    expect(within(suppliers).queryByText(/\/ ST/)).toBeNull();
    expect(within(section("Price, stock and VAT")).getAllByText("€24.85 / kg")).not.toHaveLength(0);
  });

  it("names an allergen code that is in no table as an other allergen, not by the gateway's word", async () => {
    const api = createMockApi();
    const get = api.getProductPage.bind(api);
    api.getProductPage = async (...args) => {
      const page = await get(...args);
      return { ...page, allergens: { ...page.allergens, freeFrom: [...page.allergens.freeFrom, { code: "ZZ", name: "zorbs" }] } };
    };
    renderApp("/catalog/464179", api);

    await screen.findByRole("heading", { level: 1 });
    const allergens = within(section("Allergens"));
    expect(allergens.getByText("Other allergen (ZZ)")).toBeInTheDocument();
    expect(allergens.queryByText("zorbs")).toBeNull();
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
