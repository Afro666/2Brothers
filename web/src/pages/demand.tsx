import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { useId, useState, type ReactNode } from "react";

import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { ProductThumb } from "@/components/purchasing/product-thumb";
import { RiskBadge } from "@/components/purchasing/risk-badge";
import { useApi } from "@/api";
import type { Api } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDate, formatNumber } from "@/lib/format";
import { translate, useLanguage, useT } from "@/lib/i18n";
import { TONE_CLASSES } from "@/lib/tone";
import { useAsync } from "@/lib/use-async";
import { isValidWeek, isoWeekOf, shiftWeek, weekDates, weekRangeLabel } from "@/lib/week";
import type { BuyingNote, ShortageRisk, SupplierDemandRow } from "@/types";
import { isNemotron, NemotronMark } from "@/components/nemotron-mark";

/** Worst first: a short week matters more than an unmeasured one. */
const RISK_ORDER: Record<ShortageRisk, number> = { SHORT: 0, UNKNOWN: 1, AT_RISK: 2, COVERED: 3 };

export const RISK_PLURALS: Record<ShortageRisk, string> = {
  SHORT: "short",
  UNKNOWN: "unknown",
  AT_RISK: "at risk",
  COVERED: "covered",
};

const RISK_BEFORE_AND: readonly ShortageRisk[] = ["SHORT", "UNKNOWN", "AT_RISK"];

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
  const counts: Record<ShortageRisk, number> = { SHORT: 0, UNKNOWN: 0, AT_RISK: 0, COVERED: 0 };
  for (const row of rows) counts[row.risk] += 1;
  const spoken = RISK_BEFORE_AND.filter((risk) => counts[risk] > 0).map((risk) =>
    t("{count} {risk}", { count: counts[risk], risk: t(RISK_PLURALS[risk]) }),
  );
  if (counts.COVERED > 0) spoken.push(t("{count} {risk}", { count: counts.COVERED, risk: t("covered") }));
  if (spoken.length === 0) return t("No forecast lines this week");
  if (spoken.length === 1) return spoken[0];
  return t("{items} and {last}", { items: spoken.slice(0, -1).join(", "), last: spoken.at(-1) ?? "" });
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
  label: string;
  summary: string;
  groups: ProductGroup[];
}

/** The buying note for one window and language; a stale answer is ignored by `useAsync`. */
function loadNote(api: Api, from: string, to: string, language: "en" | "fi"): Promise<BuyingNote | null> {
  return api.getBuyingNote(from, to, language).catch(() => null);
}

const noteTone: Record<string, string> = {
  UNKNOWN: TONE_CLASSES.warning,
  SHORT: TONE_CLASSES.danger,
};

function BuyingNoteBox({ note }: { note: BuyingNote }) {
  const t = useT();
  const model = note.model || "Nemotron 3.5 Super VL";
  // The note often has one line per day for the same product: name it once.
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
                  <span className="shrink-0 font-mono text-xs">{formatDate(line.date)}</span>
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

async function loadWeek(api: Api, week: string, t: ReturnType<typeof useT>): Promise<WeekSection> {
  const [monday, sunday] = [weekDates(week)[0], weekDates(week)[6]];
  const rows = await api.getSupplierDemand(monday, sunday);
  return {
    monday,
    sunday,
    label: t("Week {number}, {range}", { number: Number(week.slice(6)), range: weekRangeLabel(week) }),
    summary: riskSummary(rows, t),
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
        <span className="block text-xs text-muted-foreground">{group.productId}</span>
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
            {t("Buy {amount}", { amount: `${formatNumber(group.totalBuy)} ${group.unit}` })}
          </span>
        ) : null}
        {group.unknownBuyDays > 0 ? (
          <span className="text-warning">
            {t("+ days with an unknown amount: {count}", { count: formatNumber(group.unknownBuyDays) })}
          </span>
        ) : null}
        <span className="tabular-nums">
          {t("kitchens: up to {count}", { count: formatNumber(group.maxKitchens) })}
        </span>
      </span>
    </span>
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
        </TableHead>
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
    <TableRow hidden={hidden}>
      <TableCell>{formatDate(row.date)}</TableCell>
      <TableCell className="text-right tabular-nums">
        {formatNumber(row.forecastDemand)} {row.unit}
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
            {formatNumber(row.available)} {row.unit}
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
            {formatNumber(row.suggestedBuy)} {row.unit}
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}

function KitchenDisclosure({ row }: { row: SupplierDemandRow }) {
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
        variant="ghost"
        size="sm"
        className="h-auto min-h-8 px-2 py-1"
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
              {formatNumber(kitchen.demand)} {row.unit}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function MobileGroup({
  group,
  open,
  onToggle,
}: {
  group: ProductGroup;
  open: boolean;
  onToggle: () => void;
}) {
  const t = useT();
  return (
    <li className="space-y-3 py-4">
      <Button
        type="button"
        variant="ghost"
        className="h-auto w-full justify-start px-2 py-1 text-left whitespace-normal"
        aria-expanded={open}
        onClick={onToggle}
      >
        <ProductSummary group={group} />
      </Button>
      <ul className="space-y-3" hidden={!open}>
        {group.rows.map((row) => (
          <li key={row.date} className="rounded-md border p-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span>{formatDate(row.date)}</span>
              <RiskBadge risk={row.risk} />
            </div>
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
              <dt className="text-muted-foreground">{t("Forecast demand")}</dt>
              <dd className="text-right tabular-nums">
                {formatNumber(row.forecastDemand)} {row.unit}
              </dd>
              <dt className="text-muted-foreground">{t("Kitchens")}</dt>
              <dd className="text-right">
                <KitchenDisclosure row={row} />
              </dd>
              <dt className="text-muted-foreground">{t("Available")}</dt>
              <dd className="text-right tabular-nums">
                {row.available == null ? (
                  <span className="font-medium text-warning">{t("unknown")}</span>
                ) : (
                  `${formatNumber(row.available)} ${row.unit}`
                )}
              </dd>
              <dt className="text-muted-foreground">{t("Buy")}</dt>
              <dd
                className={row.suggestedBuy == null ? "text-right font-medium text-warning" : "text-right tabular-nums"}
              >
                {row.suggestedBuy == null ? t("unknown") : `${formatNumber(row.suggestedBuy)} ${row.unit}`}
              </dd>
            </dl>
          </li>
        ))}
      </ul>
    </li>
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
  const coveredGroups = groups.filter((group) => group.shortDays === 0 && group.worst !== "UNKNOWN");
  const directGroups =
    filter === "SHORT" ? shortGroups : filter === "UNKNOWN" ? unknownGroups : filter === "ALL" ? [...shortGroups, ...unknownGroups] : [];
  const showCovered = filter === "ALL" || filter === "COVERED";
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
              variant={filter === option.id ? "default" : "outline"}
              aria-pressed={filter === option.id}
              onClick={() => chooseFilter(option.id)}
            >
              {option.label}
            </Button>
          ))}
        </div>
        <div className="flex gap-2">
          <Button type="button" size="sm" variant="outline" onClick={openAll}>
            {t("Open all")}
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={closeAll}>
            {t("Close all")}
          </Button>
        </div>
      </div>
      <Card>
        <CardContent>
          <div className="hidden md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("Date")}</TableHead>
                  <TableHead className="text-right">{t("Forecast demand")}</TableHead>
                  <TableHead className="text-right">{t("Kitchens")}</TableHead>
                  <TableHead>{t("Available")}</TableHead>
                  <TableHead>{t("Risk")}</TableHead>
                  <TableHead className="text-right">{t("Buy")}</TableHead>
                </TableRow>
              </TableHeader>
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
          <ul className="divide-y md:hidden">
            {directGroups.map((group) => (
              <MobileGroup
                key={group.productId}
                group={group}
                open={openProducts.has(group.productId)}
                onToggle={() => toggleProduct(group.productId)}
              />
            ))}
            {showCovered && coveredGroups.length > 0 ? (
              <li className="py-2">
                <Button
                  type="button"
                  variant="ghost"
                  className="h-auto w-full justify-start px-2 py-1 text-left"
                  aria-expanded={coveredOpen}
                  onClick={() => setCoveredOpen((open) => !open)}
                >
                  {t("Covered products: {count}", { count: formatNumber(coveredGroups.length) })}
                </Button>
                <ul className="divide-y" hidden={!coveredOpen}>
                  {coveredGroups.map((group) => (
                    <MobileGroup
                      key={group.productId}
                      group={group}
                      open={openProducts.has(group.productId)}
                      onToggle={() => toggleProduct(group.productId)}
                    />
                  ))}
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
  const state = useAsync(() => (weekIsValid ? loadWeek(api, week, t) : noWeek()), [api, week, weekIsValid, t]);
  const noteWindow = weekIsValid ? [weekDates(week)[0], weekDates(week)[6]] : null;
  const note = useAsync(
    () => (noteWindow ? loadNote(api, noteWindow[0], noteWindow[1], language) : Promise.resolve(null)),
    [api, noteWindow?.[0], noteWindow?.[1], language],
  );

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
            <Button variant="outline" onClick={() => showWeek(shiftWeek(week, -1))}>
              {t("Previous week")}
            </Button>
            <h2 className="px-2 text-center text-lg font-semibold">
              {t("Week {number}, {range}", {
                number: Number(week.slice(6)),
                range: weekRangeLabel(week),
              })}
            </h2>
            <Button variant="outline" onClick={() => showWeek(shiftWeek(week, 1))}>
              {t("Next week")}
            </Button>
          </div>
        ) : null}
        {!weekIsValid ? (
          <div className="space-y-3">
            <InvalidWeek>
              {t("Go to next week, {week}", {
                week: t("Week {number}, {range}", {
                  number: Number(defaultWeek.slice(6)),
                  range: weekRangeLabel(defaultWeek),
                }),
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
              <span className="sr-only">{state.data.label}: </span>
              {state.data.summary}
            </p>
            {state.data.groups.length === 0 ? (
              <EmptyState title={t("No demand forecast for this week")}>
                {t("Kitchens that share forecasts have nothing planned for {week}.", {
                  week: state.data.label.toLowerCase(),
                })}
              </EmptyState>
            ) : (
              <div className="space-y-4">
                {note.status === "ready" && note.data ? <BuyingNoteBox note={note.data} /> : null}
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
