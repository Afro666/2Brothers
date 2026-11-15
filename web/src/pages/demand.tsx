import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode, type Ref } from "react";

import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { ProductThumb } from "@/components/purchasing/product-thumb";
import { RiskBadge } from "@/components/purchasing/risk-badge";
import { useApi } from "@/api";
import { ApiError, type Api } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableRow } from "@/components/ui/table";
import { formatAmount, formatDate, formatNumber } from "@/lib/format";
import { translate, useLanguage, useT } from "@/lib/i18n";
import { TONE_CLASSES } from "@/lib/tone";
import { useAsync } from "@/lib/use-async";
import { isValidWeek, isoWeekOf, shiftWeek, weekDates, weekTitle } from "@/lib/week";
import type { BuyingNote, ShortageRisk, SupplierDemandRow } from "@/types";
import { isNemotron, NemotronMark } from "@/components/nemotron-mark";
import { ProductLink } from "@/components/purchasing/product-link";
import { explanationModelName } from "@/components/purchasing/proposal-explanation";

/** Worst first: a short week matters more than an unmeasured one. */
const RISK_ORDER: Record<ShortageRisk, number> = { SHORT: 0, UNKNOWN: 1, AT_RISK: 2, COVERED: 3 };

export const RISK_COUNTS: Record<ShortageRisk, string> = {
  SHORT: "{count} short",
  UNKNOWN: "{count} unknown",
  AT_RISK: "{count} at risk",
  COVERED: "{count} covered",
};

/** Finnish counts differ in the singular ("1 tuntematon", not "1 tuntematonta"). */
export const RISK_ONE: Record<ShortageRisk, string> = {
  SHORT: "1 short",
  UNKNOWN: "1 unknown",
  AT_RISK: "1 at risk",
  COVERED: "1 covered",
};

const RISK_SUMMARY_ORDER: readonly ShortageRisk[] = ["SHORT", "UNKNOWN", "AT_RISK", "COVERED"];

interface ProductGroup {
  productId: string;
  productName: string;
  unit: string;
  rows: SupplierDemandRow[];
  worst: ShortageRisk;
  shortDays: number;
  totalBuy: number | null;
  unknownBuyDays: number;
  maxKitchens: number;
}

export function riskSummary(
  rows: SupplierDemandRow[],
  // Without a language the English text, with its placeholders filled.
  t: ReturnType<typeof useT> = (text, vars) => translate("en", text, vars),
): string {
  const groups = groupByProduct(rows);
  const counts: Record<ShortageRisk, number> = { SHORT: 0, UNKNOWN: 0, AT_RISK: 0, COVERED: 0 };
  for (const group of groups) counts[group.worst] += 1;
  if (groups.length === 0) return t("No forecast lines this week");
  const items = RISK_SUMMARY_ORDER.filter((risk) => counts[risk] > 0)
    .map((risk) => (counts[risk] === 1 ? t(RISK_ONE[risk]) : t(RISK_COUNTS[risk], { count: formatNumber(counts[risk]) })))
    .join(", ");
  return t(groups.length === 1 ? "{count} product: {items}" : "{count} products: {items}", {
    count: formatNumber(groups.length),
    items,
  });
}

export function groupByProduct(rows: SupplierDemandRow[]): ProductGroup[] {
  const groups = new Map<string, ProductGroup>();
  for (const row of rows) {
    const current = groups.get(row.productId);
    if (current) {
      current.rows.push(row);
      if (RISK_ORDER[row.risk] < RISK_ORDER[current.worst]) current.worst = row.risk;
      if (row.risk === "SHORT") current.shortDays += 1;
      if (row.suggestedBuy == null) current.unknownBuyDays += 1;
      else current.totalBuy = (current.totalBuy ?? 0) + row.suggestedBuy;
      current.maxKitchens = Math.max(current.maxKitchens, row.kitchens);
    } else {
      groups.set(row.productId, {
        productId: row.productId,
        productName: row.productName,
        unit: row.unit,
        rows: [row],
        worst: row.risk,
        shortDays: row.risk === "SHORT" ? 1 : 0,
        totalBuy: row.suggestedBuy,
        unknownBuyDays: row.suggestedBuy == null ? 1 : 0,
        maxKitchens: row.kitchens,
      });
    }
  }
  const band = (group: ProductGroup) => (group.shortDays > 0 ? 0 : group.worst === "UNKNOWN" ? 1 : 2);
  return [...groups.values()]
    .map((group) => ({ ...group, rows: [...group.rows].sort((a, b) => a.date.localeCompare(b.date)) }))
    .sort(
      (a, b) =>
        band(a) - band(b) ||
        (a.shortDays > 0 && b.shortDays > 0 ? (b.totalBuy ?? -1) - (a.totalBuy ?? -1) : 0) ||
        RISK_ORDER[a.worst] - RISK_ORDER[b.worst] ||
        a.productName.localeCompare(b.productName) ||
        a.productId.localeCompare(b.productId),
    );
}

interface WeekSection {
  monday: string;
  sunday: string;
  /** The raw rows: the summary is written at render time, so a language toggle needs no new fetch (#1011). */
  rows: SupplierDemandRow[];
  groups: ProductGroup[];
}

/** The buying note for one window and language; a stale answer is ignored by `useAsync`. */
function loadNote(api: Api, from: string, to: string, language: "en" | "fi"): Promise<BuyingNote | null> {
  return api.getBuyingNote(from, to, language);
}

const noteTone: Record<string, string> = {
  UNKNOWN: TONE_CLASSES.warning,
  SHORT: TONE_CLASSES.danger,
};

function BuyingNoteBox({ note }: { note: BuyingNote }) {
  const t = useT();
  const model = explanationModelName(note.model || "Nemotron 3.5 Super VL");
  // Each line sums a product over its short (or unknown) days; name it once.
  const byProduct = new Map<string, BuyingNote["lines"]>();
  for (const line of note.lines) byProduct.set(line.productId, [...(byProduct.get(line.productId) ?? []), line]);
  const products = [...byProduct.values()];
  return (
    <section aria-labelledby="buying-note-title" className="space-y-3 rounded-lg border bg-card p-4 text-sm">
      <h2 id="buying-note-title" className="font-medium">
        {t("Buying note")}
      </h2>
      <ul className="space-y-2">
        {products.map((product) => (
          <li key={product[0].productId} className="space-y-1 rounded-md border px-3 py-2 text-sm">
            <p className="font-medium">{product[0].productName}</p>
            <ul className="space-y-1">
              {product.map((line) => (
                <li
                  key={line.date}
                  data-note-risk={line.risk}
                  className={`flex flex-col gap-x-2 rounded px-2 py-1 sm:flex-row sm:items-baseline ${noteTone[line.risk] ?? ""}`}
                >
                  <span className="shrink-0 font-mono text-xs">{t("from {date}", { date: formatDate(line.date) })}</span>
                  <RiskBadge risk={line.risk} />
                  <span>{line.text}</span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        <NemotronMark when={isNemotron(model)} />
        {t("Written by {model}. Every number is checked against its row in the table.", { model })}
      </p>
    </section>
  );
}

/** Never settles, so an invalid week makes no API call and shows the error instead. */
function noWeek(): Promise<WeekSection> {
  return new Promise<WeekSection>(() => undefined);
}

async function loadWeek(api: Api, week: string): Promise<WeekSection> {
  const [monday, sunday] = [weekDates(week)[0], weekDates(week)[6]];
  const rows = await api.getSupplierDemand(monday, sunday);
  return {
    monday,
    sunday,
    rows,
    groups: groupByProduct(rows),
  };
}

function ProductSummary({ group }: { group: ProductGroup }) {
  const t = useT();
  return (
    <span className="flex w-full min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
      <ProductThumb en={group.productName} size="sm" />
      <span className="block min-w-40 flex-1">
        <span className="block font-medium break-words">{group.productName}</span>
      </span>
      <RiskBadge risk={group.worst} />
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {group.shortDays > 0 ? (
          <span className="font-medium text-foreground">
            {t("Short on {count} of {days} days", {
              count: formatNumber(group.shortDays),
              days: formatNumber(group.rows.length),
            })}
          </span>
        ) : null}
        {group.totalBuy != null ? (
          <span className="font-medium text-foreground tabular-nums">
            {t("Buy {amount}", { amount: formatAmount(group.totalBuy, group.unit) })}
          </span>
        ) : null}
        {group.unknownBuyDays > 0 ? <UnknownBuyDays group={group} /> : null}
        <span className="tabular-nums">
          {t("kitchens: up to {count}", { count: formatNumber(group.maxKitchens) })}
        </span>
      </span>
    </span>
  );
}

/** The product page link, kept outside the row's toggle button: a link may not sit inside a button. */
function OpenProductPage({ group, className }: { group: ProductGroup; className?: string }) {
  const t = useT();
  return (
    <ProductLink productId={group.productId} className={`text-xs text-primary underline ${className ?? ""}`}>
      {t("Open the product page")}{" "}
      <span className="sr-only">{group.productName}</span>
    </ProductLink>
  );
}

/** One product's days, in their own body so its name heads the row group. */
function ProductSection({
  group,
  open,
  hidden = false,
  onToggle,
}: {
  group: ProductGroup;
  open: boolean;
  hidden?: boolean;
  onToggle: () => void;
}) {
  const t = useT();
  return (
    <TableBody data-product-section={group.productId} hidden={hidden}>
      <TableRow className="border-b-0 bg-muted/40 hover:bg-muted/40">
        <TableHead scope="rowgroup" colSpan={6} className="py-2 align-top font-normal whitespace-normal">
          <Button
            type="button"
            variant="ghost"
            className="h-auto w-full justify-start px-2 py-1 text-left whitespace-normal"
            aria-expanded={open}
            onClick={onToggle}
          >
            <ProductSummary group={group} />
          </Button>
          <OpenProductPage group={group} className="px-2" />
        </TableHead>
      </TableRow>
      <TableRow data-demand-day-header hidden={!open}>
        <TableHead scope="col">{t("Date")}</TableHead>
        <TableHead scope="col" className="text-right">{t("Forecast demand")}</TableHead>
        <TableHead scope="col" className="text-right">{t("Kitchens")}</TableHead>
        <TableHead scope="col">{t("Available")}</TableHead>
        <TableHead scope="col">{t("Risk")}</TableHead>
        <TableHead scope="col" className="text-right">{t("Buy")}</TableHead>
      </TableRow>
      {group.rows.map((row) => (
        <DemandRow key={row.date} row={row} hidden={!open} />
      ))}
    </TableBody>
  );
}

function DemandRow({ row, hidden }: { row: SupplierDemandRow; hidden: boolean }) {
  const t = useT();
  return (
    <TableRow data-demand-day hidden={hidden}>
      <TableCell>{formatDate(row.date)}</TableCell>
      <TableCell className="text-right tabular-nums">
        {formatAmount(row.forecastDemand, row.unit)}
      </TableCell>
      <TableCell>
        <KitchenDisclosure row={row} />
      </TableCell>
      <TableCell>
        {row.available == null ? (
          <span
            className="font-medium text-warning"
            title={t("The supplier has not measured availability for this product")}
          >
            {t("unknown")}
          </span>
        ) : (
          <span className="tabular-nums">
            {formatAmount(row.available, row.unit)}
          </span>
        )}
      </TableCell>
      <TableCell>
        <RiskBadge risk={row.risk} />
      </TableCell>
      <TableCell className="text-right">
        <div className="text-xs text-muted-foreground">{t("Buy")}</div>
        {row.suggestedBuy == null ? (
          <div className="font-medium text-warning">{t("unknown")}</div>
        ) : (
          <div className="tabular-nums">
            {formatAmount(row.suggestedBuy, row.unit)}
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}

/** `touch` gives the button a 44 px tap height, for the phone list. */
function KitchenDisclosure({ row, touch = false }: { row: SupplierDemandRow; touch?: boolean }) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  // The table and the phone list are both in the DOM, so each instance needs its own id.
  const listId = useId();
  if (row.byKitchen.length === 0) {
    return <span className="text-muted-foreground">{t("No kitchens share this forecast")}</span>;
  }
  const kitchens = [...row.byKitchen].sort((a, b) => b.demand - a.demand || a.kitchenName.localeCompare(b.kitchenName));
  return (
    <div className="space-y-2 whitespace-normal">
      <Button
        variant={touch ? "outline" : "ghost"}
        size="sm"
        className={touch ? "h-auto min-h-11 px-3 py-1" : "h-auto min-h-8 px-2 py-1"}
        aria-expanded={expanded}
        aria-controls={listId}
        onClick={() => setExpanded((value) => !value)}
      >
        {row.kitchens === 1
          ? t("{count} kitchen", { count: formatNumber(row.kitchens) })
          : t("{count} kitchens", { count: formatNumber(row.kitchens) })}{" "}
        <span className="sr-only">
          {t("for {product}, {date}", { product: row.productName, date: formatDate(row.date) })}
        </span>
      </Button>
      <ul id={listId} hidden={!expanded} className="space-y-1 text-sm">
        {kitchens.map((kitchen) => (
          <li key={kitchen.kitchenId} className="flex flex-wrap justify-between gap-x-3">
            <span>{kitchen.kitchenName}</span>
            <span className="tabular-nums">
              {formatAmount(kitchen.demand, row.unit)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function UnknownBuyDays({ group }: { group: ProductGroup }) {
  const t = useT();
  return (
    <span className="text-warning">
      {t(group.unknownBuyDays === 1 ? "{count} day with no stock figure" : "{count} days with no stock figure", {
        count: formatNumber(group.unknownBuyDays),
      })}
    </span>
  );
}

/** A phone shows this many products, then a "Show more" button for the next ones. */
export const PHONE_PRODUCT_LIMIT = 10;

/** One product on a phone: its name, its risk and what to buy; the code, the kitchens and the days open on a tap. */
function MobileGroup({
  group,
  open,
  onToggle,
  buttonRef,
}: {
  group: ProductGroup;
  open: boolean;
  onToggle: () => void;
  buttonRef?: Ref<HTMLButtonElement>;
}) {
  const t = useT();
  return (
    <li data-phone-product={group.productId} className="py-1">
      <Button
        ref={buttonRef}
        type="button"
        variant="ghost"
        className="h-auto min-h-11 w-full justify-start gap-3 px-1 py-2 text-left font-normal whitespace-normal"
        aria-expanded={open}
        onClick={onToggle}
      >
        <ProductThumb en={group.productName} size="sm" />
        <span className="block min-w-0 flex-1 space-y-1">
          <span className="block font-medium break-words">{group.productName}</span>
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            <RiskBadge risk={group.worst} />
            {group.totalBuy != null ? (
              <span className="font-semibold tabular-nums">
                {t("Buy {amount}", { amount: formatAmount(group.totalBuy, group.unit) })}
              </span>
            ) : null}
            {/* A sum that leaves days out says so next to it. */}
            {group.totalBuy != null && group.unknownBuyDays > 0 ? <UnknownBuyDays group={group} /> : null}
          </span>
        </span>
        <ChevronDown
          className={`size-4 text-muted-foreground transition-transform motion-reduce:transition-none ${open ? "rotate-180" : ""}`}
          aria-hidden
        />
      </Button>
      <div data-phone-details hidden={!open} className="ml-4 space-y-1 border-l pb-2 pl-3 text-sm">
        <OpenProductPage group={group} className="inline-flex min-h-11 items-center" />
        <p className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
          {group.shortDays > 0 ? (
            <span className="font-medium text-foreground">
              {t("Short on {count} of {days} days", {
                count: formatNumber(group.shortDays),
                days: formatNumber(group.rows.length),
              })}
            </span>
          ) : null}
          {group.unknownBuyDays > 0 ? <UnknownBuyDays group={group} /> : null}
          <span className="tabular-nums">{t("kitchens: up to {count}", { count: formatNumber(group.maxKitchens) })}</span>
        </p>
        <ul className="divide-y">
          {group.rows.map((row) => (
            <li key={row.date} data-phone-day={row.date} className="space-y-1 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{formatDate(row.date)}</span>
                <RiskBadge risk={row.risk} />
              </div>
              <dl className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
                <div className="flex gap-1">
                  <dt className="text-muted-foreground">{t("Forecast demand")}</dt>
                  <dd className="tabular-nums">{formatAmount(row.forecastDemand, row.unit)}</dd>
                </div>
                <div className="flex gap-1">
                  <dt className="text-muted-foreground">{t("Available")}</dt>
                  <dd className={row.available == null ? "font-medium text-warning" : "tabular-nums"}>
                    {row.available == null ? t("unknown") : formatAmount(row.available, row.unit)}
                  </dd>
                </div>
                <div className="flex gap-1">
                  <dt className="text-muted-foreground">{t("Buy")}</dt>
                  <dd className={row.suggestedBuy == null ? "font-medium text-warning" : "font-medium tabular-nums"}>
                    {row.suggestedBuy == null ? t("unknown") : formatAmount(row.suggestedBuy, row.unit)}
                  </dd>
                </div>
              </dl>
              <KitchenDisclosure row={row} touch />
            </li>
          ))}
        </ul>
      </div>
    </li>
  );
}

/** The first products of a phone list, and a button that shows the next ones. */
function MobileGroups({
  groups,
  openProducts,
  onToggle,
}: {
  groups: ProductGroup[];
  openProducts: Set<string>;
  onToggle: (productId: string) => void;
}) {
  const t = useT();
  const [limit, setLimit] = useState(PHONE_PRODUCT_LIMIT);
  // The first product that "Show more" added: focus moves there, where reading goes on.
  const [focusIndex, setFocusIndex] = useState<number | null>(null);
  const firstNew = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (focusIndex != null) firstNew.current?.focus();
  }, [focusIndex]);
  const rest = groups.length - limit;

  return (
    <>
      {groups.slice(0, limit).map((group, index) => (
        <MobileGroup
          key={group.productId}
          group={group}
          open={openProducts.has(group.productId)}
          onToggle={() => onToggle(group.productId)}
          buttonRef={index === focusIndex ? firstNew : undefined}
        />
      ))}
      {rest > 0 ? (
        <li className="py-2">
          <Button
            type="button"
            variant="outline"
            className="h-11 w-full"
            onClick={() => {
              setFocusIndex(limit);
              setLimit(limit + PHONE_PRODUCT_LIMIT);
            }}
          >
            {t("Show {count} more", { count: formatNumber(Math.min(rest, PHONE_PRODUCT_LIMIT)) })}
          </Button>
        </li>
      ) : null}
    </>
  );
}

type DemandFilter = "ALL" | "SHORT" | "UNKNOWN" | "COVERED";

function DemandGroups({ groups }: { groups: ProductGroup[] }) {
  const t = useT();
  const [filter, setFilter] = useState<DemandFilter>("ALL");
  const [openProducts, setOpenProducts] = useState<Set<string>>(() => new Set());
  const [coveredOpen, setCoveredOpen] = useState(false);
  const shortGroups = groups.filter((group) => group.shortDays > 0);
  const unknownGroups = groups.filter((group) => group.shortDays === 0 && group.worst === "UNKNOWN");
  const atRiskGroups = groups.filter((group) => group.shortDays === 0 && group.worst === "AT_RISK");
  const coveredGroups = groups.filter((group) => group.worst === "COVERED");
  const directGroups =
    filter === "SHORT"
      ? shortGroups
      : filter === "UNKNOWN"
        ? unknownGroups
        : filter === "ALL"
          ? [...shortGroups, ...unknownGroups, ...atRiskGroups]
          : [];
  const showCovered = filter === "ALL" || filter === "COVERED";
  const filterIsEmpty = directGroups.length === 0 && !(showCovered && coveredGroups.length > 0);
  const options = [
    { id: "ALL" as const, label: t("All ({n})", { n: formatNumber(groups.length) }) },
    { id: "SHORT" as const, label: t("Short ({n})", { n: formatNumber(shortGroups.length) }) },
    { id: "UNKNOWN" as const, label: t("Unknown ({n})", { n: formatNumber(unknownGroups.length) }) },
    { id: "COVERED" as const, label: t("Covered ({n})", { n: formatNumber(coveredGroups.length) }) },
  ];

  function toggleProduct(productId: string) {
    setOpenProducts((current) => {
      const next = new Set(current);
      if (next.has(productId)) next.delete(productId);
      else next.add(productId);
      return next;
    });
  }

  function chooseFilter(next: DemandFilter) {
    setFilter(next);
    if (next === "COVERED") setCoveredOpen(true);
  }

  function openAll() {
    // Opens what the filter shows; the filter itself stays as the person set it.
    setCoveredOpen(true);
    setOpenProducts(new Set(groups.map((group) => group.productId)));
  }

  function closeAll() {
    setCoveredOpen(false);
    setOpenProducts(new Set());
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {options.map((option) => (
            <Button
              key={option.id}
              type="button"
              size="sm"
              className="h-11 md:h-8"
              variant={filter === option.id ? "default" : "outline"}
              aria-pressed={filter === option.id}
              onClick={() => chooseFilter(option.id)}
            >
              {option.label}
            </Button>
          ))}
        </div>
        <div className="flex gap-2">
          <Button type="button" size="sm" variant="outline" className="h-11 md:h-8" onClick={openAll}>
            {t("Open all")}
          </Button>
          <Button type="button" size="sm" variant="outline" className="h-11 md:h-8" onClick={closeAll}>
            {t("Close all")}
          </Button>
        </div>
      </div>
      <Card className="py-2 md:py-6">
        <CardContent className="px-3 md:px-6">
          <div className="hidden md:block">
            <Table>
              {filterIsEmpty ? (
                <TableBody>
                  <TableRow>
                    <TableCell colSpan={6} className="py-4 text-center text-muted-foreground">
                      {t("No products in this filter")}
                    </TableCell>
                  </TableRow>
                </TableBody>
              ) : null}
              {directGroups.map((group) => (
                <ProductSection
                  key={group.productId}
                  group={group}
                  open={openProducts.has(group.productId)}
                  onToggle={() => toggleProduct(group.productId)}
                />
              ))}
              {showCovered && coveredGroups.length > 0 ? (
                <TableBody data-covered-group>
                  <TableRow className="bg-muted/40 hover:bg-muted/40">
                    <TableHead scope="rowgroup" colSpan={6} className="py-2 font-normal whitespace-normal">
                      <Button
                        type="button"
                        variant="ghost"
                        className="h-auto w-full justify-start px-2 py-1 text-left"
                        aria-expanded={coveredOpen}
                        onClick={() => setCoveredOpen((open) => !open)}
                      >
                        {t("Covered products: {count}", { count: formatNumber(coveredGroups.length) })}
                      </Button>
                    </TableHead>
                  </TableRow>
                </TableBody>
              ) : null}
              {showCovered
                ? coveredGroups.map((group) => (
                    <ProductSection
                      key={group.productId}
                      group={group}
                      open={openProducts.has(group.productId)}
                      hidden={!coveredOpen}
                      onToggle={() => toggleProduct(group.productId)}
                    />
                  ))
                : null}
            </Table>
          </div>
          <ul className="divide-y md:hidden" data-phone-list>
            {filterIsEmpty ? (
              <li className="py-4 text-center text-sm text-muted-foreground">{t("No products in this filter")}</li>
            ) : null}
            {/* A new filter starts again at the first ten. */}
            <MobileGroups key={filter} groups={directGroups} openProducts={openProducts} onToggle={toggleProduct} />
            {showCovered && coveredGroups.length > 0 ? (
              <li className="py-1">
                <Button
                  type="button"
                  variant="ghost"
                  className="h-auto min-h-11 w-full justify-start px-1 py-1 text-left"
                  aria-expanded={coveredOpen}
                  onClick={() => setCoveredOpen((open) => !open)}
                >
                  {t("Covered products: {count}", { count: formatNumber(coveredGroups.length) })}
                </Button>
                <ul className="divide-y" hidden={!coveredOpen}>
                  <MobileGroups groups={coveredGroups} openProducts={openProducts} onToggle={toggleProduct} />
                </ul>
              </li>
            ) : null}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

/** The ErrorState look, without a retry that would repeat the same bad request. */
function InvalidWeek({ children }: { children: ReactNode }) {
  const t = useT();
  return (
    <div role="alert" className="space-y-3 rounded-lg border border-destructive/40 p-4">
      <p className="text-sm">{t("That week is not valid")}</p>
      <Button variant="outline" asChild>
        <Link to="/demand">{children}</Link>
      </Button>
    </div>
  );
}

export function DemandPage() {
  const t = useT();
  const api = useApi();
  const requestedWeek = useRouterState({
    select: (routerState) => new URLSearchParams(routerState.location.searchStr).get("week"),
  });
  const navigate = useNavigate();
  // Without `?week=` the page opens on next week: that is the demand Valio can still act on.
  const defaultWeek = shiftWeek(isoWeekOf(new Date().toISOString().slice(0, 10)), 1);
  const week = requestedWeek ?? defaultWeek;
  const weekIsValid = isValidWeek(week);
  const { language } = useLanguage();
  const state = useAsync(() => (weekIsValid ? loadWeek(api, week) : noWeek()), [api, week, weekIsValid]);
  // Written in the current language on every render: switching language does not ask the API again.
  const weekLabel = weekIsValid ? weekTitle(week, t) : "";
  const noteWindow = weekIsValid ? [weekDates(week)[0], weekDates(week)[6]] : null;
  const note = useAsync(
    () => (noteWindow ? loadNote(api, noteWindow[0], noteWindow[1], language) : Promise.resolve(null)),
    [api, noteWindow?.[0], noteWindow?.[1], language],
  );
  const noteRequestKey = noteWindow ? `${noteWindow[0]}:${noteWindow[1]}:${language}` : "";
  const noteAutoRetried = useRef("");
  const noteRetryAfterS =
    note.status === "error" && note.error instanceof ApiError && note.error.status === 429
      ? note.error.retryAfterS
      : undefined;
  useEffect(() => {
    if (noteRetryAfterS == null || noteAutoRetried.current === noteRequestKey) return;
    const timer = window.setTimeout(() => {
      noteAutoRetried.current = noteRequestKey;
      void note.reload();
    }, noteRetryAfterS * 1000);
    return () => window.clearTimeout(timer);
  }, [note.reload, noteRequestKey, noteRetryAfterS]);

  function showWeek(target: string) {
    void navigate({ to: "/demand", search: { week: target } });
  }

  return (
    <AppShell activeId="demand">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">{t("Demand")}</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t("What kitchens that share their forecast expect to need, against what is available.")}
          </p>
        </header>
        {weekIsValid ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" className="h-11 md:h-9" onClick={() => showWeek(shiftWeek(week, -1))}>
              {t("Previous week")}
            </Button>
            <h2 className="order-first w-full text-lg font-semibold md:order-none md:w-auto md:px-2 md:text-center">
              {weekTitle(week, t)}
            </h2>
            <Button variant="outline" className="h-11 md:h-9" onClick={() => showWeek(shiftWeek(week, 1))}>
              {t("Next week")}
            </Button>
          </div>
        ) : null}
        {!weekIsValid ? (
          <div className="space-y-3">
            <InvalidWeek>
              {t("Go to next week, {week}", {
                week: weekTitle(defaultWeek, t),
              })}
            </InvalidWeek>
          </div>
        ) : null}
        {weekIsValid && state.status === "loading" ? <LoadingState label={t("Loading demand")} /> : null}
        {weekIsValid && state.status === "error" ? (
          <ErrorState message={state.error.message} onRetry={state.reload} />
        ) : null}
        {weekIsValid && state.status === "ready" ? (
          <div className="space-y-4">
            <p className="text-sm font-medium">
              <span className="sr-only">{weekLabel}: </span>
              {riskSummary(state.data.rows, t)}
            </p>
            {state.data.groups.length === 0 ? (
              <EmptyState title={t("No demand forecast for this week")}>
                {t("Kitchens that share forecasts have nothing planned for {week}.", {
                  week: weekLabel.toLowerCase(),
                })}
              </EmptyState>
            ) : (
              <div className="space-y-4">
                {note.status === "ready" && note.data ? <BuyingNoteBox note={note.data} /> : null}
                {note.status === "error" ? (
                  <div role="alert" className="space-y-3 rounded-lg border border-destructive/40 p-4 text-sm">
                    <p>{t("The buying note could not be loaded. The table below is complete.")}</p>
                    <Button variant="outline" size="sm" onClick={() => void note.reload()}>
                      {t("Try again")}
                    </Button>
                  </div>
                ) : null}
                <DemandGroups key={state.data.monday} groups={state.data.groups} />
              </div>
            )}
            <p className="text-sm text-muted-foreground">
              {t("Forecasts come only from kitchens that agreed to share them.")}
            </p>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
