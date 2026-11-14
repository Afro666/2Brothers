import { useNavigate, useSearch } from "@tanstack/react-router";
import { ChevronDown } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useApi } from "@/api";
import type { MatchedBy, ProductSearchFilters, ProductTemperature, SearchedProduct } from "@/api/types";
import { AppShell } from "@/components/purchasing/app-shell";
import { AllergenUnknownChip, LABEL_META } from "@/components/purchasing/chips";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { ProductCard } from "@/components/purchasing/product-card";
import { ProductThumb } from "@/components/purchasing/product-thumb";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EU_ALLERGENS } from "@/lib/allergens";
import { formatEur, formatPack } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { PHONE_QUERY, useMediaQuery } from "@/lib/use-media-query";
import type { ProductLabel } from "@/types";

export const ALLERGENS = [...EU_ALLERGENS, { code: "ML", name: "Lactose" }] as const;

const LABEL_OPTIONS = Object.keys(LABEL_META) as ProductLabel[];
const TEMPERATURES: ProductTemperature[] = ["ambient", "chilled", "frozen"];
const EXAMPLE_SEARCHES = ["lactose-free milk", "butter", "oat drink"];
const RESULTS_PER_PAGE = 12;

export const TEMPERATURE_LABELS: Record<ProductTemperature, string> = {
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
  /** The "Search by meaning" switch (#1382). */
  meaning: boolean;
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
    meaning: search.meaning === true || search.meaning === "true",
  };
}

function filtersOf(search: CatalogSearch): ProductSearchFilters {
  return {
    excludedAllergens: search.exclude.length > 0 ? search.exclude : undefined,
    strictAllergens: search.strict || undefined,
    requiredLabels: search.labels.length > 0 ? search.labels : undefined,
    temperature: search.temp,
    byMeaning: search.meaning || undefined,
  };
}

/** The /catalog URL params; every one is optional, so a plain `/catalog` link is valid. */
export interface CatalogParams {
  q?: string;
  exclude?: string;
  strict?: true;
  labels?: string;
  temp?: ProductTemperature;
  meaning?: true;
}

/** Empty params stay out of the URL, so a plain `/catalog` is a clean link. */
function toParams(search: CatalogSearch): CatalogParams {
  return {
    q: search.q.trim() || undefined,
    exclude: search.exclude.length > 0 ? search.exclude.join(",") : undefined,
    strict: search.strict || undefined,
    labels: search.labels.length > 0 ? search.labels.join(",") : undefined,
    temp: search.temp,
    meaning: search.meaning || undefined,
  };
}

/** `validateSearch` for the /catalog route: drops unknown and malformed params. */
export function validateCatalogSearch(search: Record<string, unknown>): CatalogParams {
  return toParams(parseSearch(search));
}

function toggle<T>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

/** The mark on a row found by a search by meaning. */
const MATCHED_BY_LABELS: Record<MatchedBy, string> = {
  words: "By words",
  meaning: "By meaning",
  both: "By words and meaning",
};

type Update = (change: (current: CatalogSearch) => CatalogSearch) => void;

export function CatalogPage() {
  const t = useT();
  const api = useApi();
  const search = parseSearch(useSearch({ from: "/catalog" }));
  const navigate = useNavigate();
  const [query, setQuery] = useState(search.q);
  const hasFilters =
    search.exclude.length > 0 || search.strict || search.labels.length > 0 || search.temp !== undefined;
  const [filtersOpen, setFiltersOpen] = useState<boolean | null>(null);
  const showFilters = filtersOpen ?? hasFilters;
  const [visibleCount, setVisibleCount] = useState(RESULTS_PER_PAGE);
  const phone = useMediaQuery(PHONE_QUERY);
  const resultList = useRef<HTMLUListElement>(null);
  /** The index of the first product the last "Show more" added; null before one. */
  const [focusFrom, setFocusFrom] = useState<number | null>(null);
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
    void navigate({ to: "/catalog", search: toParams(next), replace: true });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const q = query.trim();
    setQuery(q);
    update((current) => ({ ...current, q }));
  }

  function runExample(q: string) {
    setQuery(q);
    update((current) => ({ ...current, q }));
  }

  function clearFilters() {
    const cleared = parseSearch({});
    setQuery("");
    setFiltersOpen(false);
    latest.current = cleared;
    void navigate({ to: "/catalog", search: {}, replace: true });
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
  useEffect(() => {
    setVisibleCount(RESULTS_PER_PAGE);
    setFocusFrom(null);
  }, [searchKey]);
  // "Show more" takes focus to the first product it added, where reading goes on.
  useEffect(() => {
    if (focusFrom != null) resultList.current?.children[focusFrom]?.querySelector<HTMLElement>("button, a")?.focus();
  }, [focusFrom]);
  const withoutData = excluding && !active.strict ? results.filter((product) => product.allergens === null).length : 0;
  const unfiltered = !active.q.trim() && !excluding && active.labels.length === 0 && !active.temp;

  // The first visit with nothing typed runs the first example, so the page shows real rows from
  // the catalog search and not only buttons. Once per visit: clearing the box shows the examples.
  const firstSearchDone = useRef(false);
  useEffect(() => {
    if (firstSearchDone.current || currentResult.status !== "ready") return;
    firstSearchDone.current = true;
    // Text typed while the first search loads is the person's own: never replace it.
    if (unfiltered && results.length === 0 && !query.trim()) runExample(t(EXAMPLE_SEARCHES[0]));
  }, [currentResult.status]);

  return (
    <AppShell activeId="catalog">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">{t("Products")}</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t("Search what suppliers sell. A product with no allergen data is unknown, not safe.")}
          </p>
        </header>

        <form role="search" onSubmit={submit} className="space-y-4">
          <div className="flex flex-col gap-2 sm:flex-row">
            <label className="grid flex-1 gap-1 text-sm font-medium" htmlFor="catalog-query">
              {t("Search the catalog")}
              <Input
                id="catalog-query"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("Product name")}
              />
            </label>
            <div className="flex items-end">
              <Button type="submit" className="w-full sm:w-auto">
                {t("Search")}
              </Button>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {/* Only when the gateway answers the search: the mock is not Atlas. */}
            {api.live?.has("searchProducts") ? <Badge variant="secondary">{t("Atlas Search")}</Badge> : null}
            {api.live?.has("searchProducts") ? (
              <div className="flex items-center gap-2 rounded-md border px-2 py-1">
                <Checkbox
                  id="catalog-meaning"
                  checked={search.meaning}
                  onCheckedChange={() => update((current) => ({ ...current, meaning: !current.meaning }))}
                />
                <Label htmlFor="catalog-meaning" className="text-sm font-normal">
                  {t("Search by meaning (Atlas Vector Search)")}
                </Label>
              </div>
            ) : null}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setQuery("milk");
                update((current) => ({ ...current, q: "milk", exclude: ["AM"] }));
              }}
            >
              {t("Example: milk without the milk allergen")}
            </Button>
          </div>

          <div className="rounded-xl border bg-card px-4 py-3 shadow-sm md:px-6 md:py-6">
            <Button
              type="button"
              variant="ghost"
              aria-expanded={showFilters}
              aria-controls="catalog-filters"
              onClick={() => setFiltersOpen(!showFilters)}
              className="flex w-full justify-between px-0 text-sm font-medium"
            >
              {t("Filters")}
              <ChevronDown
                className={`size-4 text-muted-foreground transition-transform ${showFilters ? "rotate-180" : ""}`}
                aria-hidden
              />
            </Button>
            <div
              id="catalog-filters"
              className={`${showFilters ? "" : "hidden"} border-t pt-4 md:mt-0 md:border-0 md:pt-0`}
            >
              <Filters search={search} update={update} />
            </div>
          </div>
        </form>

        {currentResult.status === "loading" ? <LoadingState label={t("Searching the catalog")} /> : null}
        {currentResult.status === "error" ? (
          <ErrorState
            message={currentResult.error?.message ?? t("Search failed")}
            onRetry={() => setReloadVersion((version) => version + 1)}
          />
        ) : null}
        {currentResult.status === "ready" && results.length === 0 && unfiltered ? (
          <EmptyState title={t("Search the Valio Aimo catalog")}>
            <span>
              {t("Type a product name, or pick an allergen, a label or a temperature.")}
            </span>
            <span className="mt-3 flex flex-wrap items-center justify-center gap-2">
              <span className="text-sm text-muted-foreground">{t("Try:")}</span>
              {EXAMPLE_SEARCHES.map((example) => (
                <Button key={example} type="button" size="sm" variant="outline" onClick={() => runExample(t(example))}>
                  {t(example)}
                </Button>
              ))}
            </span>
          </EmptyState>
        ) : null}
        {currentResult.status === "ready" && results.length === 0 && !unfiltered ? (
          <EmptyState title={t("No products match this search")}>
            {active.meaning && currentResult.data?.meaningUnavailable ? (
              <p className="text-sm text-muted-foreground">
                {t("Search by meaning is not available right now; only words were searched.")}
              </p>
            ) : null}
            <Button className="mt-3" variant="outline" onClick={clearFilters}>
              {t("Clear filters")}
            </Button>
          </EmptyState>
        ) : null}
        {currentResult.status === "ready" && results.length > 0 ? (
          <div className="space-y-3">
            <div className="space-y-1" aria-live="polite">
              <p className="text-sm text-muted-foreground">
                {results.length > RESULTS_PER_PAGE
                  ? t("{shown} of {total} products", { shown: Math.min(visibleCount, results.length), total: results.length })
                  : results.length === 1
                    ? t("{count} product", { count: results.length })
                    : t("{count} products", { count: results.length })}
              </p>
              {withoutData > 0 ? (
                <p className="text-sm text-muted-foreground">
                  {withoutData === 1
                    ? t("{count} has no allergen data: unknown, not safe", { count: withoutData })
                    : t("{count} have no allergen data: unknown, not safe", { count: withoutData })}
                </p>
              ) : null}
              {active.meaning && currentResult.data?.meaningUnavailable ? (
                <p className="text-sm text-muted-foreground">
                  {t("Search by meaning is not available right now. These products match by words.")}
                </p>
              ) : null}
            </div>
            {/* A phone gets one compact row per product, with the card behind a tap (#1142). */}
            <ul
              ref={resultList}
              data-catalog-results
              className={phone ? "divide-y border-y" : "grid gap-3 md:grid-cols-2 lg:grid-cols-3"}
            >
              {results.slice(0, visibleCount).map((product) => {
                const mark = active.meaning && product.matchedBy ? t(MATCHED_BY_LABELS[product.matchedBy]) : null;
                return phone ? (
                  <CompactResult key={product.id} product={product} mark={mark} />
                ) : (
                  <li key={product.id} className="space-y-1 tabular-nums">
                    {mark ? <Badge variant="outline">{mark}</Badge> : null}
                    <ProductCard product={product} />
                  </li>
                );
              })}
            </ul>
            {results.length > visibleCount ? (
              <Button
                type="button"
                variant="outline"
                className="h-11 w-full"
                onClick={() => {
                  setFocusFrom(visibleCount);
                  setVisibleCount((count) => count + RESULTS_PER_PAGE);
                }}
              >
                {t("Show more ({count} more)", { count: results.length - visibleCount })}
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}

/**
 * One product on a phone: name, code and pack, a price when the row has one, how it was
 * found, and missing allergen data. The full card opens on a tap.
 */
function CompactResult({ product, mark }: { product: SearchedProduct; mark: string | null }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <li className="tabular-nums">
      <Button
        type="button"
        variant="ghost"
        className="h-auto min-h-11 w-full justify-start gap-3 px-1 py-2 text-left font-normal whitespace-normal"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <ProductThumb en={product.names.en} fi={product.names.fi} brand={product.brand} size="sm" />
        <span className="block min-w-0 flex-1 space-y-1">
          <span className="block font-medium break-words">{product.names.en}</span>
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <span>
              {product.id} · {formatPack(product.salesUnit, product.baseUnitsPerSalesUnit, product.baseUnit)}
            </span>
            {/* Only the kitchen's own products carry a price in a search row; a supplier's comes with the offer. */}
            {product.priceExVat != null ? (
              <span className="font-medium text-foreground">
                {t("{price} per {unit} ex VAT", { price: formatEur(product.priceExVat), unit: product.salesUnit })}
              </span>
            ) : null}
            {mark ? <Badge variant="outline">{mark}</Badge> : null}
            {/* Missing allergen data is a risk, so the closed row says it too. */}
            {product.allergens == null ? <AllergenUnknownChip /> : null}
          </span>
        </span>
        <ChevronDown
          className={`size-4 text-muted-foreground transition-transform motion-reduce:transition-none ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </Button>
      {open ? (
        <div className="pb-3">
          <ProductCard product={product} />
        </div>
      ) : null}
    </li>
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
  const t = useT();
  return (
    <div className="grid gap-6 sm:grid-cols-3">
      <FilterGroup title={t("Exclude allergens")}>
        {ALLERGENS.map((allergen) => (
          <CheckRow
            key={allergen.code}
            id={`catalog-exclude-${allergen.code}`}
            checked={search.exclude.includes(allergen.code)}
            onChange={() => update((current) => ({ ...current, exclude: toggle(current.exclude, allergen.code) }))}
          >
            {t(allergen.name)}
          </CheckRow>
        ))}
        <div className="pt-2">
          <CheckRow
            id="catalog-strict"
            checked={search.strict}
            onChange={() => update((current) => ({ ...current, strict: !current.strict }))}
          >
            {t("Also hide products with no allergen data")}
          </CheckRow>
        </div>
      </FilterGroup>

      <FilterGroup title={t("Require labels")}>
        {LABEL_OPTIONS.map((label) => (
          <CheckRow
            key={label}
            id={`catalog-label-${label}`}
            checked={search.labels.includes(label)}
            onChange={() => update((current) => ({ ...current, labels: toggle(current.labels, label) }))}
          >
            {t(LABEL_META[label].text)}
          </CheckRow>
        ))}
      </FilterGroup>

      <div className="space-y-2">
        <Label htmlFor="catalog-temperature" className="font-medium">
          {t("Temperature")}
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
            <SelectItem value="any">{t("Any")}</SelectItem>
            {TEMPERATURES.map((temperature) => (
              <SelectItem key={temperature} value={temperature}>
                {t(TEMPERATURE_LABELS[temperature])}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
