import { useNavigate, useSearch } from "@tanstack/react-router";
import { ChevronDown } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useApi } from "@/api";
import type { ProductSearchFilters, ProductTemperature } from "@/api/types";
import { AppShell } from "@/components/purchasing/app-shell";
import { LABEL_META } from "@/components/purchasing/chips";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { ProductCard } from "@/components/purchasing/product-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { ProductLabel } from "@/types";

const ALLERGENS = [
  { code: "AM", name: "Milk" },
  { code: "AW", name: "Gluten cereals" },
  { code: "AE", name: "Egg" },
  { code: "AF", name: "Fish" },
  { code: "AN", name: "Tree nuts" },
  { code: "AP", name: "Peanuts" },
  { code: "AS", name: "Sesame" },
  { code: "AY", name: "Soy" },
] as const;

const LABEL_OPTIONS = Object.keys(LABEL_META) as ProductLabel[];
const TEMPERATURES: ProductTemperature[] = ["ambient", "chilled", "frozen"];

const TEMPERATURE_LABELS: Record<ProductTemperature, string> = {
  ambient: "Ambient",
  chilled: "Chilled",
  frozen: "Frozen",
};

interface CatalogSearch {
  q: string;
  exclude: string[];
  strict: boolean;
  labels: ProductLabel[];
  temp: ProductTemperature | undefined;
}

function csv(value: unknown): string[] {
  if (typeof value === "string")
    return value
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
  if (Array.isArray(value)) return value.flatMap(csv);
  return [];
}

function parseSearch(search: Record<string, unknown>): CatalogSearch {
  const rawExclude = search.exclude;
  const rawLabels = search.labels;
  const rawTemp = search.temp;
  const temp = typeof rawTemp === "string" ? TEMPERATURES.find((value) => value === rawTemp) : undefined;
  return {
    q: typeof search.q === "string" ? search.q : "",
    exclude: csv(rawExclude),
    strict: search.strict === true || search.strict === "true",
    labels: csv(rawLabels).filter((value): value is ProductLabel => LABEL_OPTIONS.includes(value as ProductLabel)),
    temp,
  };
}

function filtersOf(search: CatalogSearch): ProductSearchFilters {
  return {
    excludedAllergens: search.exclude.length > 0 ? search.exclude : undefined,
    strictAllergens: search.strict || undefined,
    requiredLabels: search.labels.length > 0 ? search.labels : undefined,
    temperature: search.temp,
  };
}

/** Empty params stay out of the URL, so a plain `/catalog` is a clean link. */
function toParams(search: CatalogSearch): Record<string, string | true | undefined> {
  return {
    q: search.q.trim() || undefined,
    exclude: search.exclude.length > 0 ? search.exclude.join(",") : undefined,
    strict: search.strict || undefined,
    labels: search.labels.length > 0 ? search.labels.join(",") : undefined,
    temp: search.temp,
  };
}

function toggle<T>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

type Update = (change: (current: CatalogSearch) => CatalogSearch) => void;

export function CatalogPage() {
  const api = useApi();
  // The catalog route has no typed search, so the params are read defensively.
  const search = parseSearch(useSearch({ strict: false }));
  const navigate = useNavigate();
  const [query, setQuery] = useState(search.q);
  const [filtersOpen, setFiltersOpen] = useState(false);
  // A click and a navigation render later, so chained toggles read the latest params here.
  const latest = useRef(search);
  latest.current = search;

  // A link can change the query; text typed but not yet searched stays as it is.
  useEffect(() => {
    setQuery((current) => (current.trim() === search.q ? current : search.q));
  }, [search.q]);

  function update(change: (current: CatalogSearch) => CatalogSearch) {
    const next = change(latest.current);
    latest.current = next;
    void navigate({ to: "/catalog", search: toParams(next) as never, replace: true });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const q = query.trim();
    setQuery(q);
    update((current) => ({ ...current, q }));
  }

  function clearFilters() {
    const cleared = parseSearch({});
    setQuery("");
    latest.current = cleared;
    void navigate({ to: "/catalog", search: {} as never, replace: true });
  }

  const searchKey = JSON.stringify(search);
  const [result, setResult] = useState<{
    key: string;
    status: "loading" | "ready" | "error";
    data?: Awaited<ReturnType<typeof api.searchProducts>>;
    error?: Error;
  }>({ key: "", status: "loading" });
  const [reloadVersion, setReloadVersion] = useState(0);
  useEffect(() => {
    let active = true;
    setResult({ key: searchKey, status: "loading" });
    api
      .searchProducts(search.q, filtersOf(search))
      .then((data) => {
        if (active) setResult({ key: searchKey, status: "ready", data });
      })
      .catch((error: unknown) => {
        if (active)
          setResult({
            key: searchKey,
            status: "error",
            error: error instanceof Error ? error : new Error(String(error)),
          });
      });
    return () => {
      active = false;
    };
  }, [api, searchKey, reloadVersion]);
  const currentResult = result.key === searchKey ? result : { key: searchKey, status: "loading" as const };
  const active = latest.current;
  const excluding = active.exclude.length > 0;
  const results = currentResult.status === "ready" ? (currentResult.data ?? []) : [];
  const withoutData = excluding && !active.strict ? results.filter((product) => product.allergens === null).length : 0;

  return (
    <AppShell activeId="catalog">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">Catalog</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            Search what suppliers sell. A product with no allergen data is unknown, not safe.
          </p>
        </header>

        <form role="search" onSubmit={submit} className="space-y-4">
          <div className="flex flex-col gap-2 sm:flex-row">
            <label className="grid flex-1 gap-1 text-sm font-medium" htmlFor="catalog-query">
              Search the catalog
              <Input
                id="catalog-query"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Product name"
              />
            </label>
            <div className="flex items-end">
              <Button type="submit" className="w-full sm:w-auto">
                Search
              </Button>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {/* Only when the gateway answers the search: the mock is not Atlas. */}
            {api.live?.has("searchProducts") ? <Badge variant="secondary">Atlas Search</Badge> : null}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setQuery("milk");
                update((current) => ({ ...current, q: "milk", exclude: ["AM"] }));
              }}
            >
              Example: milk without the milk allergen
            </Button>
          </div>

          <div className="rounded-xl border bg-card px-4 py-3 shadow-sm md:px-6 md:py-6">
            <Button
              type="button"
              variant="ghost"
              aria-expanded={filtersOpen}
              onClick={() => setFiltersOpen((open) => !open)}
              className="flex w-full justify-between px-0 text-sm font-medium md:hidden"
            >
              Filters
              <ChevronDown
                className={`size-4 text-muted-foreground transition-transform ${filtersOpen ? "rotate-180" : ""}`}
                aria-hidden
              />
            </Button>
            <div className={`${filtersOpen ? "" : "hidden"} border-t pt-4 md:mt-0 md:block md:border-0 md:pt-0`}>
              <Filters search={search} update={update} />
            </div>
          </div>
        </form>

        {currentResult.status === "loading" ? <LoadingState label="Searching the catalog" /> : null}
        {currentResult.status === "error" ? (
          <ErrorState
            message={currentResult.error?.message ?? "Search failed"}
            onRetry={() => setReloadVersion((version) => version + 1)}
          />
        ) : null}
        {currentResult.status === "ready" && results.length === 0 ? (
          <EmptyState title="No products match this search">
            <Button className="mt-3" variant="outline" onClick={clearFilters}>
              Clear filters
            </Button>
          </EmptyState>
        ) : null}
        {currentResult.status === "ready" && results.length > 0 ? (
          <div className="space-y-3">
            <div className="space-y-1" aria-live="polite">
              <p className="text-sm text-muted-foreground">
                {results.length} {results.length === 1 ? "product" : "products"}
              </p>
              {withoutData > 0 ? (
                <p className="text-sm text-muted-foreground">
                  {withoutData} {withoutData === 1 ? "has" : "have"} no allergen data: unknown, not safe
                </p>
              ) : null}
            </div>
            <ul className="grid gap-4 md:grid-cols-2">
              {results.map((product) => (
                <li key={product.id} className="tabular-nums">
                  <ProductCard product={product} />
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}

function FilterGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{title}</legend>
      {children}
    </fieldset>
  );
}

function CheckRow({
  id,
  checked,
  onChange,
  children,
}: {
  id: string;
  checked: boolean;
  onChange: () => void;
  children: ReactNode;
}) {
  return (
    <div className="flex items-start gap-2">
      <Checkbox id={id} checked={checked} onCheckedChange={onChange} className="mt-0.5" />
      <Label htmlFor={id} className="font-normal leading-snug">
        {children}
      </Label>
    </div>
  );
}

function Filters({ search, update }: { search: CatalogSearch; update: Update }) {
  return (
    <div className="grid gap-6 sm:grid-cols-3">
      <FilterGroup title="Exclude allergens">
        {ALLERGENS.map((allergen) => (
          <CheckRow
            key={allergen.code}
            id={`catalog-exclude-${allergen.code}`}
            checked={search.exclude.includes(allergen.code)}
            onChange={() => update((current) => ({ ...current, exclude: toggle(current.exclude, allergen.code) }))}
          >
            {allergen.name}
            <span className="ml-1 text-xs text-muted-foreground">({allergen.code})</span>
          </CheckRow>
        ))}
        <div className="pt-2">
          <CheckRow
            id="catalog-strict"
            checked={search.strict}
            onChange={() => update((current) => ({ ...current, strict: !current.strict }))}
          >
            Also hide products with no allergen data
          </CheckRow>
        </div>
      </FilterGroup>

      <FilterGroup title="Require labels">
        {LABEL_OPTIONS.map((label) => (
          <CheckRow
            key={label}
            id={`catalog-label-${label}`}
            checked={search.labels.includes(label)}
            onChange={() => update((current) => ({ ...current, labels: toggle(current.labels, label) }))}
          >
            {LABEL_META[label].text}
          </CheckRow>
        ))}
      </FilterGroup>

      <div className="space-y-2">
        <Label htmlFor="catalog-temperature" className="font-medium">
          Temperature
        </Label>
        <Select
          value={search.temp ?? "any"}
          onValueChange={(value) =>
            update((current) => ({ ...current, temp: TEMPERATURES.find((temperature) => temperature === value) }))
          }
        >
          <SelectTrigger id="catalog-temperature" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="any">Any</SelectItem>
            {TEMPERATURES.map((temperature) => (
              <SelectItem key={temperature} value={temperature}>
                {TEMPERATURE_LABELS[temperature]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
