import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { OwnProduct, Product, ProductCode, Supplier } from "@/types";

/** How long the picker waits after typing before it calls the catalog search. */
export const PICKER_DEBOUNCE_MS = 250;

/** A product a recipe line can use, with where it comes from. */
export interface PickerProduct {
  product: Product | OwnProduct;
  name: string;
  unit: string;
  source: string;
}

interface PickerResults {
  status: "idle" | "loading" | "ready" | "error";
  products: PickerProduct[];
  error: string;
}

const IDLE: PickerResults = { status: "idle", products: [], error: "" };

/** Own products as rows, marked "own"; the catalog rows carry the supplier or vendor instead. */
/** The first few of a long catalog result, so the row card stays short. */
const MAX_CATALOG_RESULTS = 8;

function ownChoices(ownProducts: readonly OwnProduct[], suppliers: readonly Supplier[]): PickerProduct[] {
  const supplierNames = new Map(suppliers.map((supplier) => [supplier.id, supplier.name]));
  return ownProducts.map((product) => ({
    product,
    name: product.name,
    unit: product.unit,
    source: `own · ${supplierNames.get(product.supplierId) ?? "supplier not found"}`,
  }));
}

function catalogChoice(product: Product): PickerProduct {
  return {
    product,
    name: product.names.en,
    unit: product.baseUnit,
    source: product.vendorName || "supplier not set",
  };
}

function matchesQuery(choice: PickerProduct, words: readonly string[]): boolean {
  const name = choice.name.toLocaleLowerCase();
  return words.every((word) => name.includes(word));
}

/**
 * Search-as-you-type over the kitchen's own products and the supplier catalog.
 * The catalog search waits for two characters and 250 ms so a real gateway is not hit per keystroke.
 */
export function ProductPicker({
  value,
  findProduct,
  ownProducts,
  suppliers,
  search,
  loadProducts,
  onChoose,
  onChange,
}: {
  value: { productId: string; productName: string };
  /** Finds the row's product in the recipes already loaded; any other product is loaded by id. */
  findProduct: (id: string) => PickerProduct | undefined;
  ownProducts: readonly OwnProduct[];
  suppliers: readonly Supplier[];
  /** The catalog search, plus products by id to resolve a row chosen from the search or saved earlier. */
  search: (query: string) => Promise<Product[]>;
  loadProducts: (ids: ProductCode[]) => Promise<Product[]>;
  onChoose: (choice: PickerProduct) => void;
  /** “Change” clears the row, so the picker shows again. */
  onChange: () => void;
}) {
  const inputId = useId();
  const [query, setQuery] = useState("");
  // Results carry the text they answer, so a list for old text never shows under new text.
  const [results, setResults] = useState<{ query: string; state: PickerResults }>({ query: "", state: IDLE });
  const [chosen, setChosen] = useState<PickerProduct | null>(null);
  const [unavailableId, setUnavailableId] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const changeRef = useRef<HTMLButtonElement>(null);
  const moveFocus = useRef(false);

  // Choosing and “Change” unmount the focused control, so focus follows to the one that replaces it.
  useEffect(() => {
    if (!moveFocus.current) return;
    moveFocus.current = false;
    (value.productId === "" ? inputRef : changeRef).current?.focus();
  }, [value.productId]);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setResults({ query: "", state: IDLE });
      return;
    }
    let active = true;
    setResults({ query: trimmed, state: { status: "loading", products: [], error: "" } });
    const timer = window.setTimeout(() => {
      search(trimmed)
        .then((products) => {
          if (active) {
            setResults({
              query: trimmed,
              state: { status: "ready", products: products.map(catalogChoice), error: "" },
            });
          }
        })
        .catch((cause: unknown) => {
          if (active) {
            setResults({
              query: trimmed,
              state: {
                status: "error",
                products: [],
                error: cause instanceof Error ? cause.message : String(cause),
              },
            });
          }
        });
    }, PICKER_DEBOUNCE_MS);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [query, search]);

  // Only a row whose product is in neither the loaded recipes nor this picker's choice is loaded by id.
  useEffect(() => {
    const id = value.productId;
    if (id === "" || findProduct(id) || chosen?.product.id === id) return;
    let active = true;
    loadProducts([id])
      .then(([product]) => {
        if (!active) return;
        if (product) setChosen(catalogChoice(product));
        else setUnavailableId(id);
      })
      .catch(() => {
        if (active) setUnavailableId(id);
      });
    return () => {
      active = false;
    };
  }, [value.productId, chosen, findProduct, loadProducts]);

  function choose(choice: PickerProduct) {
    moveFocus.current = true;
    onChoose(choice);
    setChosen(choice);
    setQuery("");
  }

  if (value.productId !== "") {
    const shown = findProduct(value.productId) ?? (chosen?.product.id === value.productId ? chosen : null);
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm">
        <span className="font-medium">{shown?.name ?? value.productName}</span>
        {shown ? <span className="text-muted-foreground">{`${shown.unit} · ${shown.source}`}</span> : null}
        {!shown && unavailableId === value.productId ? (
          <span className="text-xs text-muted-foreground">details unavailable</span>
        ) : null}
        <Button
          ref={changeRef}
          type="button"
          variant="outline"
          size="sm"
          className="ml-auto"
          aria-label={`Change product, currently ${shown?.name ?? value.productName}`}
          onClick={() => {
            moveFocus.current = true;
            setQuery("");
            onChange();
          }}
        >
          Change
        </Button>
      </div>
    );
  }

  const trimmed = query.trim();
  const words = trimmed.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const own = trimmed.length >= 2 ? ownChoices(ownProducts, suppliers) : [];
  const matchingOwn = own.filter((match) => matchesQuery(match, words));
  const ownIds = new Set(matchingOwn.map((match) => match.product.id));
  const found = results.query === trimmed ? results.state : IDLE;
  const waiting = trimmed.length >= 2 && found.status === "idle";
  const catalogMatches = found.products.filter((match) => !ownIds.has(match.product.id));
  const catalog = catalogMatches.slice(0, MAX_CATALOG_RESULTS);
  const count = matchingOwn.length + catalog.length;
  let status = "";
  if (trimmed.length < 2) status = "Type at least 2 characters to search.";
  else if (found.status === "loading" || waiting) status = "Searching…";
  else if (found.status === "ready" && count === 0) status = `No products match “${trimmed}”.`;
  else if (found.status === "ready" && catalogMatches.length > catalog.length)
    status = `First ${count} products shown. Type more to narrow the list.`;
  else if (found.status === "ready") status = `${count} ${count === 1 ? "product" : "products"} found.`;

  return (
    <div className="space-y-2">
      <label htmlFor={inputId} className="grid gap-1.5 text-sm font-medium">
        Find a product
        <Input
          ref={inputRef}
          id={inputId}
          type="search"
          autoComplete="off"
          value={query}
          placeholder="Start typing a product name"
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      {/* Always mounted, so a screen reader announces each change of the search state. */}
      <p role="status" className="text-xs text-muted-foreground">
        {status}
      </p>
      {count > 0 || found.status === "error" ? (
        <div className="space-y-1 rounded-md border p-2">
          {matchingOwn.map((match) => (
            <PickerOption key={`own-${match.product.id}`} choice={match} onChoose={choose} />
          ))}
          {found.status === "error" ? (
            <p role="alert" className="px-2 py-1 text-xs text-destructive">
              {found.error}
            </p>
          ) : null}
          {catalog.map((match) => (
            <PickerOption key={`catalog-${match.product.id}`} choice={match} onChoose={choose} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function PickerOption({ choice, onChoose }: { choice: PickerProduct; onChoose: (choice: PickerProduct) => void }) {
  return (
    <button
      type="button"
      className="flex w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-md px-2 py-1.5 text-left text-sm outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50"
      onClick={() => onChoose(choice)}
    >
      <span className="font-medium">{choice.name}</span>
      <span className="text-muted-foreground">
        {choice.unit} · {choice.source}
      </span>
    </button>
  );
}
