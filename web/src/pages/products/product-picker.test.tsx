import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Product } from "@/types";
import { PICKER_DEBOUNCE_MS, ProductPicker, type PickerProduct } from "@/pages/products/product-picker";

function catalogProduct(id: string, name: string): Product {
  return {
    id,
    names: { en: name },
    brand: "Valio",
    vendorName: "Valio Oy",
    category: "Milk",
    salesUnit: "ST",
    baseUnit: "L",
    baseUnitsPerSalesUnit: 1,
    units: [],
    fatPercent: null,
    temperature: null,
    allergens: null,
    labels: [],
    co2KgPerKg: null,
    deliveryReliability: null,
  };
}

const PICKER = {
  value: { productId: "", productName: "" },
  findProduct: () => undefined,
  ownProducts: [],
  suppliers: [],
  search: async () => [],
  loadProducts: async () => [],
  onChoose: () => undefined,
  onChange: () => undefined,
};

/** Answers each query after its own delay, so two answers can be made to overlap. */
function slowSearch(delays: Record<string, number>) {
  const calls: string[] = [];
  const search = (query: string) =>
    new Promise<Product[]>((resolve) => {
      calls.push(query);
      window.setTimeout(() => resolve([catalogProduct(query, `Result for ${query}`)]), delays[query] ?? 10);
    });
  return { calls, search };
}

function type(text: string) {
  fireEvent.change(screen.getByRole("searchbox", { name: "Find a product" }), { target: { value: text } });
}

async function wait(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("ProductPicker", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("waits for two characters and the debounce before it searches", async () => {
    const { calls, search } = slowSearch({});
    render(<ProductPicker {...PICKER} search={search} />);

    type("m");
    await wait(PICKER_DEBOUNCE_MS * 2);
    expect(calls).toEqual([]);
    expect(screen.getByRole("status")).toHaveTextContent("Type at least 2 characters to search.");

    type("mi");
    await wait(PICKER_DEBOUNCE_MS - 1);
    type("milk");
    await wait(PICKER_DEBOUNCE_MS - 1);
    expect(calls).toEqual([]);
    expect(screen.getByRole("status")).toHaveTextContent("Searching…");

    await wait(1);
    expect(calls).toEqual(["milk"]);
    await wait(10);
    expect(screen.getByRole("button", { name: /Result for milk/ })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 product found.");
  });

  it("shows only the latest query's results when a slow earlier answer arrives last", async () => {
    const { calls, search } = slowSearch({ milk: 1000, cream: 10 });
    render(<ProductPicker {...PICKER} search={search} />);

    type("milk");
    await wait(PICKER_DEBOUNCE_MS);
    type("cream");
    await wait(PICKER_DEBOUNCE_MS + 10);
    expect(calls).toEqual(["milk", "cream"]);
    expect(screen.getByRole("button", { name: /Result for cream/ })).toBeInTheDocument();

    // The answer for "milk" lands now, after the answer for "cream".
    await wait(1000);
    expect(screen.getByRole("button", { name: /Result for cream/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Result for milk/ })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 product found.");
  });

  it("says when nothing matches", async () => {
    render(<ProductPicker {...PICKER} />);
    type("zz");
    await wait(PICKER_DEBOUNCE_MS);
    expect(screen.getByRole("status")).toHaveTextContent("No products match “zz”.");
  });

  it("neither throws nor updates state when it unmounts mid-flight", async () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const answer = [catalogProduct("1", "Milk")];
    // The picker reads an answer with map only when it is still mounted and the query is current.
    const read = vi.spyOn(answer, "map");
    const calls: string[] = [];
    const search = (query: string) =>
      new Promise<Product[]>((resolve) => {
        calls.push(query);
        window.setTimeout(() => resolve(answer), 100);
      });
    const { unmount } = render(<ProductPicker {...PICKER} search={search} />);

    type("milk");
    await wait(PICKER_DEBOUNCE_MS);
    expect(calls).toEqual(["milk"]);
    unmount();
    await wait(100);
    expect(read).not.toHaveBeenCalled();
    expect(errors).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not search after it unmounts during the debounce", async () => {
    const { calls, search } = slowSearch({});
    const { unmount } = render(<ProductPicker {...PICKER} search={search} />);
    type("milk");
    unmount();
    await wait(PICKER_DEBOUNCE_MS * 2);
    expect(calls).toEqual([]);
  });

  it("moves focus to “Change” after a choice and back to the search box after “Change”", async () => {
    function Row() {
      const [value, setValue] = useState({ productId: "", productName: "" });
      return (
        <ProductPicker
          {...PICKER}
          search={async (query) => [catalogProduct("1", `Result for ${query}`)]}
          value={value}
          onChoose={(choice) => setValue({ productId: choice.product.id, productName: choice.name })}
          onChange={() => setValue({ productId: "", productName: "" })}
        />
      );
    }
    render(<Row />);
    type("milk");
    await wait(PICKER_DEBOUNCE_MS);

    fireEvent.click(screen.getByRole("button", { name: /Result for milk/ }));
    const change = screen.getByRole("button", { name: "Change product, currently Result for milk" });
    expect(change).toHaveFocus();

    fireEvent.click(change);
    expect(screen.getByRole("searchbox", { name: "Find a product" })).toHaveFocus();
  });

  it("does not load a product the page already has", async () => {
    const known: PickerProduct = { product: catalogProduct("1", "Milk"), name: "Milk", unit: "L", source: "Valio Oy" };
    const loadProducts = vi.fn(async () => []);
    render(
      <ProductPicker
        {...PICKER}
        value={{ productId: "1", productName: "Saved milk" }}
        findProduct={() => known}
        loadProducts={loadProducts}
      />,
    );
    await wait(0);
    expect(loadProducts).not.toHaveBeenCalled();
    expect(screen.getByText("L · Valio Oy")).toBeInTheDocument();
  });

  it("shows the saved name and “details unavailable” when a needed product fails to load", async () => {
    const loadProducts = vi.fn(async (): Promise<Product[]> => {
      throw new Error("gateway down");
    });
    render(
      <ProductPicker {...PICKER} value={{ productId: "9", productName: "Saved milk" }} loadProducts={loadProducts} />,
    );
    await wait(0);
    expect(loadProducts).toHaveBeenCalledWith(["9"]);
    expect(screen.getByText("Saved milk")).toBeInTheDocument();
    expect(screen.getByText("details unavailable")).toBeInTheDocument();
  });
});
