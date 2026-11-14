import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type Api } from "@/api";
import { createMockApi } from "@/api/mock";
import { products as sampleProducts } from "@/mocks/milk-case";
import { renderApp } from "@/test/render";

const MILK_PRODUCTS = [
  "Arla 1 L lactose free fat free UHT milk drink",
  "Valio Eila organic lactose free milk drink 1 L",
  "Valio Eila lactose free milk drink 10 L novobox",
  "Valio Eila 3 % lactose free milk drink 1 L",
  "Arla lactose free milk drink 10 L novobox ESL",
];

const NO_DATA = "Arla lactose free milk drink 10 L novobox ESL";

/** The first visit searches the first example; clearing the box brings the start state with the examples. */
async function startState(user: ReturnType<typeof userEvent.setup>, firstExample: string) {
  const box = await screen.findByRole("searchbox");
  await waitFor(() => expect(box).toHaveValue(firstExample));
  await user.clear(box);
  await user.keyboard("{Enter}");
}

describe("catalog page", () => {
  beforeEach(() => localStorage.clear());

  it("exposes allergen filters at desktop width without opening a panel", async () => {
    renderApp("/catalog");

    expect(await screen.findByRole("checkbox", { name: /Milk/ })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Gluten cereals/ })).toBeInTheDocument();
  });

  it("lists the milk products for a query", async () => {
    renderApp("/catalog?q=milk");

    expect(await screen.findByRole("heading", { level: 1, name: "Products" })).toBeInTheDocument();
    expect(await screen.findByText("5 products")).toBeInTheDocument();
    for (const name of MILK_PRODUCTS) {
      expect(await screen.findByText(name)).toBeInTheDocument();
    }
    expect(screen.getByRole("searchbox", { name: "Search the catalog" })).toHaveValue("milk");
  });

  it("searches on submit and lists everything for an empty query", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/catalog");
    expect(await screen.findByText("5 products")).toBeInTheDocument();

    await user.type(screen.getByRole("searchbox", { name: "Search the catalog" }), "organic{Enter}");

    expect(await screen.findByText("1 product")).toBeInTheDocument();
    expect(router.state.location.href).toBe("/catalog?q=organic");
  });

  it("excludes an allergen, flags missing data, then hides it when strict", async () => {
    const user = userEvent.setup();
    renderApp("/catalog?q=milk");
    await screen.findByText("5 products");

    await user.click(screen.getByRole("checkbox", { name: /Milk/ }));

    expect(await screen.findByText("1 product")).toBeInTheDocument();
    expect(screen.getByText(NO_DATA)).toBeInTheDocument();
    expect(screen.getByText("1 has no allergen data: unknown, not safe")).toBeInTheDocument();
    expect(screen.queryByText("Valio Eila organic lactose free milk drink 1 L")).not.toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Also hide products with no allergen data" }));

    expect(await screen.findByRole("heading", { name: "No products match this search" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(await screen.findByText("5 products")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search the catalog" })).toHaveValue("");
    expect(screen.getByRole("checkbox", { name: /Milk/ })).not.toBeChecked();
  });

  it("shows only the organic product when the organic label is required", async () => {
    const { router } = renderApp("/catalog?labels=EU_ORGANIC_FARMING");

    expect(await screen.findByText("1 product")).toBeInTheDocument();
    expect(screen.getByText("Valio Eila organic lactose free milk drink 1 L")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Organic (EU)" })).toBeChecked();
    expect(router.state.location.search).toMatchObject({ labels: "EU_ORGANIC_FARMING" });
  });

  it("keeps a pending search text when a filter changes the URL", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/catalog?q=milk");
    await screen.findByText("5 products");

    const box = screen.getByRole("searchbox", { name: "Search the catalog" });
    await user.clear(box);
    await user.type(box, "organic");
    await user.click(screen.getByRole("checkbox", { name: "Finnish swan" }));

    await waitFor(() => expect(router.state.location.search).toMatchObject({ labels: "GOODS_FROM_FINLAND_BLUE_SWAN" }));
    expect(box).toHaveValue("organic");
    expect(await screen.findByText("3 products")).toBeInTheDocument();
  });

  it("drops a strict exclusion when the allergen is unticked", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/catalog?q=milk&exclude=AM&strict=true");

    expect(await screen.findByRole("heading", { name: "No products match this search" })).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /Milk/ }));

    expect(await screen.findByText("4 products")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Also hide products with no allergen data" })).toBeChecked();
    expect(router.state.location.search).toMatchObject({ strict: true });
    expect(router.state.location.search).not.toHaveProperty("exclude");
  });

  it("filters by temperature and keeps the filter in the URL", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/catalog");
    await screen.findByText("5 products");

    await user.click(screen.getByRole("combobox", { name: "Temperature" }));
    await user.click(await screen.findByRole("option", { name: "Ambient" }));

    expect(await screen.findByText("1 product")).toBeInTheDocument();
    expect(screen.getByText("Arla 1 L lactose free fat free UHT milk drink")).toBeInTheDocument();
    expect(router.state.location.search).toMatchObject({ temp: "ambient" });
  });

  it("shows the API error with a retry", async () => {
    const api = createMockApi();
    const message = "The catalog search failed.";
    api.searchProducts = async () => {
      throw new ApiError("GATEWAY_DOWN", message);
    };
    renderApp("/catalog", api);

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("runs the allergen-exclusion example from the chip", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/catalog");
    await screen.findByText("5 products");

    await user.click(screen.getByRole("button", { name: "Example: milk without the milk allergen" }));

    expect(await screen.findByText("1 product")).toBeInTheDocument();
    expect(screen.getByText("1 has no allergen data: unknown, not safe")).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search the catalog" })).toHaveValue("milk");
    expect(router.state.location.href).toBe("/catalog?q=milk&exclude=AM");
  });

  it("says Atlas Search only when the gateway answers the search", async () => {
    renderApp("/catalog");
    await screen.findByText("5 products");
    expect(screen.queryByText("Atlas Search")).not.toBeInTheDocument();
    cleanup();

    renderApp("/catalog", Object.assign(createMockApi(), { live: new Set(["searchProducts" as const]) }));
    expect(await screen.findByText("Atlas Search")).toBeInTheDocument();
  });

  it("runs the first example on the first visit and shows its rows", async () => {
    const api = createMockApi();
    const actual = api.searchProducts;
    const calls: string[] = [];
    api.searchProducts = (query, filters) => {
      calls.push(query);
      if (query === "lactose-free milk") return Promise.resolve([sampleProducts.arlaUht1l]);
      return query.trim() ? actual(query, filters) : Promise.resolve([]);
    };
    const { router } = renderApp("/catalog", api);

    await waitFor(() => expect(calls).toContain("lactose-free milk"));
    expect(await screen.findByText(sampleProducts.arlaUht1l.names.en)).toBeInTheDocument();
    // Once: the example is not searched again when the page draws again.
    expect(calls.filter((query) => query === "lactose-free milk")).toHaveLength(1);
    expect(await screen.findByRole("searchbox", { name: "Search the catalog" })).toHaveValue("lactose-free milk");
    await waitFor(() => expect(router.state.location.href).toBe("/catalog?q=lactose-free+milk"));
    expect(screen.queryByRole("heading", { name: "No products match this search" })).not.toBeInTheDocument();
  });

  it("keeps text typed while the first search loads instead of running the example", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const actual = api.searchProducts;
    const calls: string[] = [];
    let finishFirst: (rows: Awaited<ReturnType<typeof actual>>) => void = () => {};
    api.searchProducts = (query, filters) => {
      calls.push(query);
      if (!query.trim()) return new Promise((resolve) => (finishFirst = resolve));
      return actual(query, filters);
    };
    renderApp("/catalog", api);
    const box = await screen.findByRole("searchbox", { name: "Search the catalog" });
    await waitFor(() => expect(calls).toContain(""));

    await user.type(box, "but");
    finishFirst([]);

    expect(await screen.findByRole("heading", { name: "Search the Valio Aimo catalog" })).toBeInTheDocument();
    expect(box).toHaveValue("but");
    expect(calls).not.toContain("lactose-free milk");
  });

  it("shows the start state with the examples once the person clears the box", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const actual = api.searchProducts;
    api.searchProducts = (query, filters) => (query.trim() ? actual(query, filters) : Promise.resolve([]));
    renderApp("/catalog", api);
    const box = await screen.findByRole("searchbox", { name: "Search the catalog" });
    await waitFor(() => expect(box).toHaveValue("lactose-free milk"));

    await user.clear(box);
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByRole("heading", { name: "Search the Valio Aimo catalog" })).toBeInTheDocument();
    expect(screen.getByText("Type a product name, or pick an allergen, a label or a temperature.")).toBeInTheDocument();
    expect(screen.getByText("Try:")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "lactose-free milk" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "butter" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "oat drink" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "No products match this search" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  });

  it("runs an example search from the start state", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const actual = api.searchProducts;
    const calls: string[] = [];
    const butter = [sampleProducts.arlaUht1l];
    api.searchProducts = (query, filters) => {
      calls.push(query);
      if (query === "butter") return Promise.resolve(butter);
      return query.trim() ? actual(query, filters) : Promise.resolve([]);
    };
    const { router } = renderApp("/catalog", api);
    await startState(user, "lactose-free milk");

    await user.click(await screen.findByRole("button", { name: "butter" }));

    expect(calls).toContain("butter");
    expect(await screen.findByText(butter[0].names.en)).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Search the catalog" })).toHaveValue("butter");
    expect(router.state.location.href).toBe("/catalog?q=butter");
  });

  it("sends an example search in the language shown", async () => {
    localStorage.setItem("purchasing-language", "fi");
    const user = userEvent.setup();
    const api = createMockApi();
    const calls: string[] = [];
    api.searchProducts = (query) => {
      calls.push(query);
      return Promise.resolve([]);
    };
    renderApp("/catalog", api);
    await startState(user, "laktoositon maito");

    await user.click(await screen.findByRole("button", { name: "voi" }));

    expect(calls).toContain("voi");
    expect(calls).not.toContain("butter");
    expect(screen.getByRole("searchbox")).toHaveValue("voi");
  });

  it("shows the start hint, not 'No products match', when only strictness or meaning is set (#1218)", async () => {
    const api = createMockApi();
    // The live client answers [] without a call when nothing but strictness or meaning is set.
    api.searchProducts = async (query) => (query.trim() ? [sampleProducts.arlaUht1l] : []);
    const { router } = renderApp("/catalog?strict=true&meaning=true", api);
    // The first visit searches the first example (#1587); the person then clears the box.
    await startState(userEvent.setup(), "lactose-free milk");

    await waitFor(() => expect(router.state.location.href).toBe("/catalog?strict=true&meaning=true"));
    expect(await screen.findByRole("heading", { name: "Search the Valio Aimo catalog" })).toBeInTheDocument();
    expect(screen.getByText("Type a product name, or pick an allergen, a label or a temperature.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "No products match this search" })).not.toBeInTheDocument();
  });

  it("still says no products match for a query that finds nothing", async () => {
    const api = createMockApi();
    const actual = api.searchProducts;
    api.searchProducts = (query, filters) => (query === "zzz-nothing" ? Promise.resolve([]) : actual(query, filters));
    renderApp("/catalog?q=zzz-nothing", api);

    expect(await screen.findByRole("heading", { name: "No products match this search" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Search the Valio Aimo catalog" })).not.toBeInTheDocument();
  });

  it("lists the products when the empty search returns them", async () => {
    renderApp("/catalog");

    expect(await screen.findByText("5 products")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Search the Valio Aimo catalog" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "No products match this search" })).not.toBeInTheDocument();
  });

  it("shows twelve results at a time while keeping the full result count", async () => {
    const api = createMockApi();
    const many = Array.from({ length: 30 }, (_, index) => ({
      ...sampleProducts.arlaUht1l,
      id: `product-${index + 1}`,
      names: { en: `Product ${index + 1}` },
    }));
    api.searchProducts = async () => many;
    const user = userEvent.setup();
    renderApp("/catalog?q=milk", api);

    expect(await screen.findByText("30 products")).toBeInTheDocument();
    expect(screen.getAllByText(/^Product \d+$/)).toHaveLength(12);
    await user.click(screen.getByRole("button", { name: "Show more (18 more)" }));
    expect(await screen.findByText("Product 24")).toBeInTheDocument();
    expect(screen.getAllByText(/^Product \d+$/)).toHaveLength(24);
    expect(screen.getByText("30 products")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show more (6 more)" })).toBeInTheDocument();
  });

  describe("Search by meaning (#1382)", () => {
    function meaningApi(unavailable = false) {
      const base = createMockApi();
      const asked: (boolean | undefined)[] = [];
      const api = Object.assign(base, {
        live: new Set(["searchProducts" as const]),
        async searchProducts(query: string, filters: Parameters<typeof base.searchProducts>[1] = {}) {
          asked.push(filters.byMeaning);
          const rows = await createMockApi().searchProducts(query, { ...filters, byMeaning: undefined });
          if (!filters.byMeaning) return rows;
          if (unavailable) return Object.assign(rows.map((row) => ({ ...row, matchedBy: "words" as const })), { meaningUnavailable: true as const });
          return rows.map((row, index) => ({ ...row, matchedBy: index === 0 ? ("meaning" as const) : ("both" as const) }));
        },
      });
      return { api, asked };
    }

    it("is a switch next to the search field that marks each row by how it was found", async () => {
      const user = userEvent.setup();
      const { api, asked } = meaningApi();
      const { router } = renderApp("/catalog?q=milk", api);
      expect(await screen.findByText("5 products")).toBeInTheDocument();
      expect(screen.queryByText("By meaning")).not.toBeInTheDocument();

      await user.click(screen.getByRole("checkbox", { name: "Search by meaning (Atlas Vector Search)" }));

      expect(await screen.findByText("By meaning")).toBeInTheDocument();
      expect(screen.getAllByText("By words and meaning")).toHaveLength(4);
      expect(router.state.location.href).toBe("/catalog?q=milk&meaning=true");
      expect(asked).toEqual([undefined, true]);
    });

    it("says so when the gateway used words instead", async () => {
      const { api } = meaningApi(true);
      renderApp("/catalog?q=milk&meaning=true", api);
      expect(
        await screen.findByText("Search by meaning is not available right now. These products match by words."),
      ).toBeInTheDocument();
      expect(screen.getAllByText("By words")).toHaveLength(5);
    });

    it("is not shown on sample data: the mock is not Atlas", async () => {
      renderApp("/catalog?q=milk");
      await screen.findByText("5 products");
      expect(screen.queryByRole("checkbox", { name: "Search by meaning (Atlas Vector Search)" })).not.toBeInTheDocument();
    });
  });
});

describe("catalog page: a short result list on a phone (#1142)", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  const SAMPLE = Object.values(sampleProducts);

  /** `count` products named "Product 01" …; the first has no allergen data, the second is an own product. */
  function manyProducts(count: number) {
    const api: Api = Object.assign(createMockApi(), { live: new Set(["searchProducts" as const]) });
    api.searchProducts = async (_query, filters = {}) =>
      Array.from({ length: count }, (_, index) => ({
        ...SAMPLE[index % SAMPLE.length],
        id: `9${String(index + 1).padStart(5, "0")}`,
        names: { en: `Product ${String(index + 1).padStart(2, "0")}` },
        salesUnit: "KI",
        baseUnit: "L",
        baseUnitsPerSalesUnit: 10,
        allergens: index === 0 ? null : [],
        ...(index === 1 ? { priceExVat: 12.5 } : {}),
        ...(filters.byMeaning ? { matchedBy: index === 0 ? ("meaning" as const) : ("words" as const) } : {}),
      }));
    return api;
  }

  /** A phone: the `max-width` query matches; every other media query does not. */
  function onAPhone() {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("max-width"),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
  }

  function resultItems(): HTMLElement[] {
    return [...document.querySelectorAll<HTMLElement>("ul[data-catalog-results] > li")];
  }

  it("moves focus to the first product that Show more adds, also in the next search", async () => {
    const user = userEvent.setup();
    renderApp("/catalog?q=milk", manyProducts(30));

    expect(await screen.findByText("30 products")).toBeInTheDocument();
    expect(resultItems()).toHaveLength(12);

    await user.click(screen.getByRole("button", { name: "Show more (18 more)" }));
    expect(resultItems()).toHaveLength(24);
    expect(resultItems()[12]).toHaveTextContent("Product 13");
    expect(resultItems()[12]).toContainElement(document.activeElement as HTMLElement);

    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "butter{Enter}");
    await waitFor(() => expect(resultItems()).toHaveLength(12));
    // The same step in the new search moves focus again.
    await user.click(screen.getByRole("button", { name: "Show more (18 more)" }));
    expect(resultItems()[12]).toContainElement(document.activeElement as HTMLElement);
  });

  it("keeps the full cards at desktop width", async () => {
    renderApp("/catalog?q=milk", manyProducts(3));

    await screen.findByText("3 products");
    expect(resultItems()).toHaveLength(3);
    expect(screen.getAllByText("CO2 per kg")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /Product 01/ })).not.toBeInTheDocument();
  });

  it("shows a compact row on a phone: name, code, pack and a known price; the card opens on a tap", async () => {
    onAPhone();
    const user = userEvent.setup();
    renderApp("/catalog?q=milk", manyProducts(3));
    await screen.findByText("3 products");

    const [first, second, third] = resultItems();
    const toggle = within(second).getByRole("button", { name: /Product 02/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveTextContent("900002");
    expect(toggle).toHaveTextContent("1 case = 10 l");
    expect(toggle).toHaveTextContent(/12[.,]50.* per KI ex VAT/);
    // A supplier's search row has no price: the closed row shows none, the card says where it comes from.
    expect(within(third).getByRole("button", { name: /Product 03/ })).not.toHaveTextContent("ex VAT");
    // Missing allergen data is a risk: it shows on the closed row too.
    expect(within(first).getByRole("button", { name: /Product 01/ })).toHaveTextContent("Allergen data missing: unknown");
    expect(toggle).not.toHaveTextContent("Allergen data missing");
    expect(screen.queryByText("CO2 per kg")).not.toBeInTheDocument();

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(second).getByText("CO2 per kg")).toBeInTheDocument();
    expect(within(second).getByText("No allergens declared")).toBeInTheDocument();
    expect(within(second).getByRole("link", { name: /Suppliers, VAT and stock/ })).toHaveAttribute(
      "href",
      "/catalog/900002",
    );
    expect(screen.getAllByText("CO2 per kg")).toHaveLength(1);

    await user.click(within(third).getByRole("button", { name: /Product 03/ }));
    expect(within(third).getByText("Live price and stock come with the offer")).toBeInTheDocument();

    await user.click(toggle);
    expect(within(second).queryByText("CO2 per kg")).not.toBeInTheDocument();
  });

  it("shows twelve compact rows and Show more on a phone", async () => {
    onAPhone();
    const user = userEvent.setup();
    renderApp("/catalog?q=milk", manyProducts(30));
    await screen.findByText("30 products");

    expect(resultItems()).toHaveLength(12);
    await user.click(screen.getByRole("button", { name: "Show more (18 more)" }));
    expect(resultItems()).toHaveLength(24);
    expect(within(resultItems()[12]).getByRole("button", { name: /Product 13/ })).toHaveFocus();
  });

  it("keeps the meaning switch, the Atlas badge and the row marks on a phone (#1448)", async () => {
    onAPhone();
    const user = userEvent.setup();
    renderApp("/catalog?q=milk", manyProducts(3));
    await screen.findByText("3 products");

    expect(screen.getByText("Atlas Search")).toBeInTheDocument();
    expect(screen.queryByText("By meaning")).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Search by meaning (Atlas Vector Search)" }));

    await waitFor(() => expect(screen.getAllByText("By words")).toHaveLength(2));
    const [first] = resultItems();
    expect(within(first).getByRole("button", { name: /Product 01/ })).toHaveTextContent("By meaning");
  });

  it("keeps the fallback line and the marks on a phone when meaning is not available", async () => {
    onAPhone();
    const api = manyProducts(3);
    const search = api.searchProducts;
    api.searchProducts = async (query, filters) =>
      Object.assign(
        (await search(query, filters)).map((row) => ({ ...row, matchedBy: "words" as const })),
        { meaningUnavailable: true as const },
      );
    renderApp("/catalog?q=milk&meaning=true", api);

    const rows = await waitFor(() => {
      expect(resultItems()).toHaveLength(3);
      return resultItems();
    });
    expect(
      screen.getByText("Search by meaning is not available right now. These products match by words."),
    ).toBeInTheDocument();
    for (const row of rows) expect(within(row).getByRole("button", { expanded: false })).toHaveTextContent("By words");
  });
});
