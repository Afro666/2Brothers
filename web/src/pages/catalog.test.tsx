import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/api";
import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

const MILK_PRODUCTS = [
  "Arla 1 L lactose free fat free UHT milk drink",
  "Valio Eila organic lactose free milk drink 1 L",
  "Valio Eila lactose free milk drink 10 L novobox",
  "Valio Eila 3 % lactose free milk drink 1 L",
  "Arla lactose free milk drink 10 L novobox ESL",
];

const NO_DATA = "Arla lactose free milk drink 10 L novobox ESL";

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
});
