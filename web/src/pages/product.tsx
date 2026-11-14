import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, ChefHat, CircleQuestionMark, MapPin, Receipt, Store, Thermometer, TriangleExclamationPoint } from "lucide-react";
import type { ReactNode } from "react";

import { useApi } from "@/api";
import type { NutrientKey, ProductPage, ProductPageAllergen, ProductPageSupplier, Texts } from "@/api/http-product-page";
import { AppShell } from "@/components/purchasing/app-shell";
import { LabelChip } from "@/components/purchasing/chips";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { ProductThumb } from "@/components/purchasing/product-thumb";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { formatDate, formatDateTime, formatEur, formatNumber, formatPack, shortOrderId } from "@/lib/format";
import { useLanguage, useT } from "@/lib/i18n";
import { TONE_CLASSES } from "@/lib/tone";
import { useAsync } from "@/lib/use-async";
import { cn } from "@/lib/utils";

/** Texts the page builds at run time; the Finnish coverage test reads this list. */
export const PRODUCT_PAGE_TEXTS = {
  days: { MON: "Mon", TUE: "Tue", WED: "Wed", THU: "Thu", FRI: "Fri", SAT: "Sat", SUN: "Sun" } as Record<string, string>,
  temperatures: { ambient: "Ambient", chilled: "Chilled", frozen: "Frozen" } as Record<string, string>,
  nutrients: {
    kcal: "Energy (kcal)",
    fat_g: "Fat (g)",
    saturated_fat_g: "of which saturated (g)",
    carbs_g: "Carbohydrate (g)",
    sugar_g: "of which sugars (g)",
    fibre_g: "Fibre (g)",
    protein_g: "Protein (g)",
    salt_g: "Salt (g)",
  } satisfies Record<NutrientKey, string>,
  liveErrors: {
    SUPPLIER_BUSY: "Valio is busy right now: price and stock unknown.",
    VALIO_UNAVAILABLE: "Valio did not answer: price and stock unknown.",
  } as Record<string, string>,
};

const UNKNOWN = "font-medium text-warning";

/** The text in the reader's language, else English, else any language the catalog has. */
function pick(texts: Texts, language: string): string | null {
  if (!texts) return null;
  return (language === "fi" ? texts.fi : undefined) ?? texts.en ?? texts.fi ?? texts.sv ?? null;
}

function country(code: string | null, language: string): string | null {
  if (!code) return null;
  try {
    return new Intl.DisplayNames([language], { type: "region" }).of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
}

function Section({ id, title, source, children }: { id: string; title: string; source?: string | null; children: ReactNode }) {
  const t = useT();
  return (
    <section aria-labelledby={`${id}-heading`} className="space-y-2">
      <h2 id={`${id}-heading`} className="text-base font-semibold">
        {title}
      </h2>
      {children}
      {source ? <p className="text-xs text-muted-foreground">{t("Source: {source}", { source })}</p> : null}
    </section>
  );
}

function Fact({ label, children, unknown }: { label: string; children: ReactNode; unknown?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="label-caps">{label}</dt>
      <dd className={cn("break-words", unknown && UNKNOWN)}>{children}</dd>
    </div>
  );
}

const CHIP = "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-medium";

function Allergens({ allergens }: { allergens: ProductPage["allergens"] }) {
  const t = useT();
  if (!allergens.known) {
    return (
      <p className={cn(CHIP, TONE_CLASSES.danger, "border-dashed")}>
        <CircleQuestionMark className="size-3" aria-hidden />
        {t("Allergens not known: the catalog has no allergen data. Check the label.")}
      </p>
    );
  }
  const row = (label: string, list: ProductPageAllergen[], tone: string, empty: string) => (
    <div className="flex flex-wrap items-baseline gap-1.5">
      <dt className="w-28 shrink-0 text-xs text-muted-foreground">{label}</dt>
      <dd className="flex flex-1 flex-wrap gap-1">
        {list.length === 0 ? (
          <span className="text-sm text-muted-foreground">{empty}</span>
        ) : (
          list.map((allergen) => (
            <span key={allergen.code} className={cn(CHIP, tone)}>
              {allergen.name}
            </span>
          ))
        )}
      </dd>
    </div>
  );
  return (
    <dl className="space-y-2">
      {row(t("Contains"), allergens.contains, TONE_CLASSES.danger, allergens.noDeclarableAllergens ? t("No declarable allergens") : t("No allergen declared"))}
      {row(t("May contain"), allergens.mayContain, cn(TONE_CLASSES.warning, "border-dashed"), t("No allergen declared"))}
      {row(t("Free from"), allergens.freeFrom, TONE_CLASSES.success, t("No claim"))}
    </dl>
  );
}

function PriceStockVat({ page }: { page: ProductPage }) {
  const t = useT();
  const { live, vat } = page;
  const vatRate = vat.rate ?? live?.taxRate ?? null;
  const stock = live?.stock ?? null;
  const per = live?.per ?? page.product.salesUnit;
  const sources = [live?.source, vat.source].filter(Boolean).join(" · ");
  if (live === null) {
    return (
      <dl className="grid grid-cols-2 gap-3 text-sm tabular-nums">
        <Fact label={t("VAT")} unknown={vatRate == null}>
          {vatRate == null ? t("unknown") : `${formatNumber(vatRate)} %`}
        </Fact>
        <Fact label={t("Live price")}>{t("Not for this product: its price comes from the supplier's price list.")}</Fact>
      </dl>
    );
  }
  return (
    <>
      {live.error ? (
        <p role="status" className={cn(CHIP, TONE_CLASSES.warning)}>
          {t(PRODUCT_PAGE_TEXTS.liveErrors[live.error] ?? "Valio did not answer: price and stock unknown.")}
        </p>
      ) : null}
      <dl className="grid grid-cols-2 gap-3 text-sm tabular-nums">
        <Fact label={t("Price ex VAT")} unknown={live.priceExVat == null}>
          {live.priceExVat == null ? t("unknown") : `${t(formatEur(live.priceExVat))} / ${per}`}
        </Fact>
        <Fact label={t("Price incl VAT")} unknown={live.priceInclVat == null}>
          {live.priceInclVat == null ? t("unknown") : `${t(formatEur(live.priceInclVat))} / ${per}`}
        </Fact>
        <Fact label={t("VAT")} unknown={vatRate == null}>
          {vatRate == null ? (
            <>
              {t("unknown")}
              <span className="block text-xs font-normal text-muted-foreground">{t("The catalog gives no VAT code for this product.")}</span>
            </>
          ) : (
            <>
              {formatNumber(vatRate)} %{vat.code ? <span className="text-xs text-muted-foreground"> · {vat.code}</span> : null}
            </>
          )}
        </Fact>
        <Fact label={t("Valio stock on {date}", { date: t(formatDate(live.date)) })} unknown={!stock || stock.unknown}>
          {!stock || stock.unknown
            ? t("unknown: a person confirms")
            : stock.available === 0
              ? t("none available")
              : `${formatNumber(stock.available ?? 0)} ${per}`}
        </Fact>
        {live.comparisonPrice != null && live.comparisonUnit ? (
          <Fact label={t("Unit price")}>{`${t(formatEur(live.comparisonPrice))} / ${live.comparisonUnit}`}</Fact>
        ) : null}
        {stock?.closingTime ? (
          <Fact label={t("Order by")}>{stock.cutoffPassed ? t("cut-off passed") : t(formatDateTime(stock.closingTime))}</Fact>
        ) : null}
      </dl>
      {sources ? <p className="text-xs text-muted-foreground">{t("Source: {source}", { source: sources })}</p> : null}
    </>
  );
}

function days(list: string[], t: ReturnType<typeof useT>): string {
  return list.map((day) => t(PRODUCT_PAGE_TEXTS.days[day] ?? day)).join(" ");
}

function Suppliers({ suppliers }: { suppliers: ProductPageSupplier[] }) {
  const t = useT();
  if (suppliers.length === 0) return <p className="text-sm text-muted-foreground">{t("No supplier offers this product yet.")}</p>;
  const priced = suppliers.filter((s) => s.pricePerMeasure != null);
  const cheapest = priced.length > 1 ? priced.reduce((a, b) => (b.pricePerMeasure! < a.pricePerMeasure! ? b : a)) : null;
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="w-full min-w-[20rem] text-sm tabular-nums">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th scope="col" className="px-1 py-1.5 font-medium">{t("Supplier")}</th>
            <th scope="col" className="px-1 py-1.5 text-right font-medium">{t("Per kg or L")}</th>
            <th scope="col" className="px-1 py-1.5 text-right font-medium">{t("Lead time")}</th>
            <th scope="col" className="px-1 py-1.5 text-right font-medium">{t("Free delivery from")}</th>
          </tr>
        </thead>
        <tbody>
          {suppliers.map((s) => (
            <tr key={`${s.supplierId}-${s.productId}`} className="border-b align-top last:border-0" data-cheapest={s === cheapest ? "" : undefined}>
              <td className="px-1 py-2">
                <div className="font-medium break-words">{s.name}</div>
                <div className="text-xs text-muted-foreground">
                  {s.priceExVat == null ? t("price unknown") : `${t(formatEur(s.priceExVat))} / ${s.per ?? "?"}`}
                  {s.netContent ? ` · ${formatNumber(s.netContent.value)} ${s.netContent.unit}` : ""}
                  {s.orderDays.length ? ` · ${days(s.orderDays, t)}` : ""}
                </div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {s === cheapest ? <span className={cn(CHIP, TONE_CLASSES.success)}>{t("Cheapest")}</span> : null}
                  {s.stockKnown ? null : <span className={cn(CHIP, TONE_CLASSES.neutral)}>{t("Stock not confirmed")}</span>}
                </div>
              </td>
              <td className={cn("px-1 py-2 text-right", s.pricePerMeasure == null && UNKNOWN)}>
                {s.pricePerMeasure == null ? t("unknown") : `${t(formatEur(s.pricePerMeasure))}/${s.measureUnit}`}
              </td>
              <td className={cn("px-1 py-2 text-right", s.leadTimeDays == null && UNKNOWN)}>
                {s.leadTimeDays == null ? t("unknown") : s.leadTimeDays === 1 ? t("1 day") : t("{n} days", { n: s.leadTimeDays })}
              </td>
              <td className={cn("px-1 py-2 text-right", s.freeDeliveryThresholdEur == null && UNKNOWN)}>
                {s.freeDeliveryThresholdEur == null ? t("unknown") : t(formatEur(s.freeDeliveryThresholdEur))}
                {s.deliveryFeeEur != null ? (
                  <div className="text-xs font-normal text-muted-foreground">{t("else {fee}", { fee: t(formatEur(s.deliveryFeeEur)) })}</div>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-xs text-muted-foreground">
        {t("Prices ex VAT. A supplier with stock not confirmed can still be ordered: a person approves it.")}
      </p>
    </div>
  );
}

function amount(quantity: number | null, unit: string | null): string {
  return quantity == null ? "?" : `${formatNumber(quantity)}${unit ? ` ${unit}` : ""}`;
}

function ThisKitchen({ kitchen }: { kitchen: ProductPage["kitchen"] }) {
  const t = useT();
  const { stock, demand } = kitchen;
  return (
    <div className="space-y-3 text-sm tabular-nums">
      <dl className="grid grid-cols-2 gap-3">
        <Fact label={t("Stock counted")} unknown={!stock || stock.onHand == null}>
          {stock && stock.onHand != null ? (
            <>
              {amount(stock.onHand, stock.unit)}
              {stock.countedAt ? <span className="block text-xs font-normal text-muted-foreground">{t(formatDateTime(stock.countedAt))}</span> : null}
            </>
          ) : (
            t("not counted yet")
          )}
        </Fact>
        <Fact label={t("Need, next 14 days")}>
          {demand ? (
            demand.grossNeed == null ? (
              t("mixed units")
            ) : (
              <>
                {amount(demand.grossNeed, demand.unit)}
                <span className="block text-xs text-muted-foreground">{t("on {n} days", { n: demand.days })}</span>
              </>
            )
          ) : (
            <span className="text-muted-foreground">{t("no planned use")}</span>
          )}
        </Fact>
      </dl>
      <div className="space-y-1">
        <h3 className="label-caps">{t("Waiting for approval")}</h3>
        {kitchen.proposalsWaiting.length === 0 ? (
          <p className="text-muted-foreground">{t("No proposal with this product is waiting.")}</p>
        ) : (
          <ul className="space-y-1">
            {kitchen.proposalsWaiting.map((line) => (
              <li key={line.id} className="flex justify-between gap-2">
                <Link to="/approvals" search={{ proposal: line.id }} className="font-medium underline-offset-2 hover:underline">
                  {amount(line.quantity, line.unit)} · {t(formatDate(line.createdAt))}
                </Link>
                <span>{t(formatEur(line.total))}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="space-y-1">
        <h3 className="label-caps">{t("Last orders")}</h3>
        {kitchen.orders.length === 0 ? (
          <p className="text-muted-foreground">{t("Not ordered yet.")}</p>
        ) : (
          <ul className="space-y-1">
            {kitchen.orders.map((line) => (
              <li key={line.id} className="flex justify-between gap-2">
                <Link to="/orders/$orderId" params={{ orderId: line.id }} className="font-medium underline-offset-2 hover:underline">
                  {t(formatDate(line.createdAt))} · {amount(line.quantity, line.unit)}
                  <span className="text-xs font-normal text-muted-foreground"> · {shortOrderId(line.id)}</span>
                </Link>
                <span>{t(formatEur(line.total))}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="space-y-1">
        <h3 className="label-caps">{t("Recipes that use it")}</h3>
        {kitchen.recipes.length === 0 ? (
          <p className="text-muted-foreground">{t("No recipe uses it.")}</p>
        ) : (
          <ul className="space-y-1">
            {kitchen.recipes.map((recipe) => (
              <li key={recipe.recipeId} className="flex justify-between gap-2">
                <span className="flex items-center gap-1.5">
                  <ChefHat className="size-4 text-muted-foreground" aria-hidden />
                  {recipe.name}
                </span>
                <span className="text-muted-foreground">{t("{amount} per portion", { amount: amount(recipe.qtyPerPortion, recipe.unit) })}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function StorageOrigin({ page, language }: { page: ProductPage; language: string }) {
  const t = useT();
  const { storage } = page;
  const signed = (value: number) => (value > 0 ? `+${value}` : String(value));
  const range = storage.minC != null && storage.maxC != null ? `, ${signed(storage.minC)} to ${signed(storage.maxC)} °C` : "";
  const temperature = storage.temperature ? `${t(PRODUCT_PAGE_TEXTS.temperatures[storage.temperature] ?? storage.temperature)}${range}` : null;
  const where = country(page.origin.country, language);
  const instructions = pick(page.about?.storageInstructions ?? null, language);
  const preparation = pick(page.about?.preparationInstructions ?? null, language);
  return (
    <div className="space-y-2 text-sm">
      <dl className="grid grid-cols-2 gap-3">
        <Fact label={t("Temperature")} unknown={!temperature}>
          <span className="inline-flex items-center gap-1">
            <Thermometer className="size-4 text-muted-foreground" aria-hidden />
            {temperature ?? t("unknown")}
          </span>
        </Fact>
        <Fact label={t("Country of origin")} unknown={!where}>
          <span className="inline-flex items-center gap-1">
            <MapPin className="size-4 text-muted-foreground" aria-hidden />
            {where ?? t("unknown")}
          </span>
        </Fact>
      </dl>
      {instructions ? <p>{instructions}</p> : null}
      {preparation ? (
        <p>
          <span className="label-caps mr-1">{t("Preparation")}</span>
          {preparation}
        </p>
      ) : null}
    </div>
  );
}

function Nutrition({ nutrition }: { nutrition: ProductPage["nutrition"] }) {
  const t = useT();
  if (!nutrition) return <p className="text-sm text-muted-foreground">{t("The label has no nutrition table we can read.")}</p>;
  const keys = Object.keys(PRODUCT_PAGE_TEXTS.nutrients) as NutrientKey[];
  return (
    <details className="rounded-lg border p-3 text-sm">
      <summary className="cursor-pointer font-medium">{nutrition.basis === "ml" ? t("Per 100 ml") : t("Per 100 g")}</summary>
      <dl className="mt-2 divide-y tabular-nums">
        {keys.map((key) => (
          <div key={key} className="flex justify-between py-1">
            <dt className={cn(key.startsWith("saturated") || key.startsWith("sugar") ? "pl-3 text-muted-foreground" : "")}>{t(PRODUCT_PAGE_TEXTS.nutrients[key])}</dt>
            <dd className={nutrition.values[key] == null ? "text-muted-foreground" : ""}>
              {nutrition.values[key] == null ? t("not on the label") : formatNumber(nutrition.values[key]!)}
            </dd>
          </div>
        ))}
      </dl>
      {nutrition.source ? <p className="mt-2 text-xs text-muted-foreground">{t("Source: {source}", { source: nutrition.source })}</p> : null}
    </details>
  );
}

function ProductBody({ page }: { page: ProductPage }) {
  const t = useT();
  const { language } = useLanguage();
  const { product, about } = page;
  const otherNames = [language === "fi" ? product.names.en : product.names.fi, product.names.sv].filter(
    (name) => name && name !== (language === "fi" ? product.names.fi : product.names.en),
  );
  const title = (language === "fi" ? product.names.fi : undefined) ?? product.names.en;
  const marketing = pick(about?.marketingText ?? null, language);
  const key = pick(about?.keyIngredients ?? null, language);
  const ingredients = (about?.ingredients ?? []).map((item) => pick(item, language)).filter(Boolean).join(", ");
  return (
    <article className="mx-auto max-w-2xl space-y-4">
      <Link to="/catalog" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" aria-hidden />
        {t("Catalog")}
      </Link>
      <header className="flex items-start gap-3">
        <ProductThumb en={product.names.en} fi={product.names.fi} brand={product.brand} size="lg" />
        <div className="min-w-0 flex-1 space-y-1">
          <h1 className="page-title leading-snug break-words">{title}</h1>
          {otherNames.length ? <p className="text-sm break-words text-muted-foreground">{otherNames.join(" · ")}</p> : null}
          <p className="text-sm text-muted-foreground tabular-nums">
            {[product.brand, product.id, formatPack(product.salesUnit, product.baseUnitsPerSalesUnit, product.baseUnit)].filter(Boolean).join(" · ")}
          </p>
          {product.labels.length ? (
            <div className="flex flex-wrap gap-1">
              {product.labels.map((label) => (
                <LabelChip key={label} label={label} />
              ))}
            </div>
          ) : null}
        </div>
      </header>
      {page.recall.status === "BLOCKED_BY_RECALL" ? (
        <p role="alert" className={cn("flex items-start gap-2 rounded-lg border p-3 text-sm", TONE_CLASSES.danger)}>
          <TriangleExclamationPoint className="mt-0.5 size-4 shrink-0" aria-hidden />
          {t("Held by a recall: this product cannot be approved until a person checks the packs.")}
          {page.recall.alerts[0]?.title ? ` ${page.recall.alerts[0].title}` : ""}
        </p>
      ) : null}
      <Card className="gap-5 p-4">
        <Section id="about" title={t("What it is")} source={about?.source}>
          <div className="space-y-1 text-sm">
            {marketing ? <p>{marketing}</p> : null}
            {ingredients ? (
              <p>
                <span className="label-caps mr-1">{t("Ingredients")}</span>
                {ingredients}
              </p>
            ) : key ? (
              <p>
                <span className="label-caps mr-1">{t("Ingredients")}</span>
                {key}
              </p>
            ) : null}
            <p className="text-muted-foreground">
              {[product.category, about?.producer ?? product.vendorName].filter(Boolean).join(" · ") || t("No description in the catalog.")}
            </p>
          </div>
        </Section>
        <Section id="allergens" title={t("Allergens")} source={page.allergens.source}>
          <Allergens allergens={page.allergens} />
        </Section>
        <Section id="price" title={t("Price, stock and VAT")}>
          <PriceStockVat page={page} />
        </Section>
      </Card>
      <Card className="gap-5 p-4">
        <Section id="suppliers" title={t("Suppliers")}>
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Store className="size-4" aria-hidden />
            {page.suppliers.length === 1 ? t("1 supplier") : t("{n} suppliers", { n: page.suppliers.length })}
          </div>
          <Suppliers suppliers={page.suppliers} />
        </Section>
      </Card>
      <Card className="gap-5 p-4">
        <Section id="kitchen" title={t("This kitchen")}>
          <ThisKitchen kitchen={page.kitchen} />
        </Section>
      </Card>
      <Card className="gap-5 p-4">
        <Section id="storage" title={t("Storage and origin")} source={page.storage.source ?? page.origin.source}>
          <StorageOrigin page={page} language={language} />
        </Section>
        <Section id="nutrition" title={t("Nutrition")}>
          <Nutrition nutrition={page.nutrition} />
        </Section>
      </Card>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Receipt className="size-3.5" aria-hidden />
        {t("Unknown means the source does not say. It is never read as zero or as none.")}
      </p>
    </article>
  );
}

/** `/catalog/$productId`: everything a buyer needs about one product, each part with its source. */
export function ProductPageView() {
  const t = useT();
  const api = useApi();
  const { productId } = useParams({ from: "/catalog/$productId" });
  const state = useAsync(() => api.getProductPage(productId), [api, productId]);
  return (
    <AppShell activeId="catalog">
      {state.status === "loading" ? <LoadingState label={t("Loading the product")} /> : null}
      {state.status === "error" && (state.error as { code?: string }).code === "PRODUCT_NOT_FOUND" ? (
        <EmptyState title={t("Product not found")}>
          <span>{t("No catalog or own product has the code {id}.", { id: productId })}</span>
          <Button asChild variant="outline" className="mt-3">
            <Link to="/catalog">{t("Search the catalog")}</Link>
          </Button>
        </EmptyState>
      ) : state.status === "error" ? (
        <ErrorState message={state.error.message} onRetry={state.reload} />
      ) : null}
      {state.status === "ready" ? <ProductBody page={state.data} /> : null}
    </AppShell>
  );
}
