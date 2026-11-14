import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { useId, useState, type ReactNode } from "react";

import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { RiskBadge } from "@/components/purchasing/risk-badge";
import { useApi } from "@/api";
import type { Api } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDate, formatNumber } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import { isValidWeek, isoWeekOf, shiftWeek, weekDates, weekLabel } from "@/lib/week";
import type { ShortageRisk, SupplierDemandRow } from "@/types";

/** Worst first: a short week matters more than an unmeasured one. */
const RISK_ORDER: Record<ShortageRisk, number> = { SHORT: 0, UNKNOWN: 1, AT_RISK: 2, COVERED: 3 };

const RISK_PLURALS: Record<ShortageRisk, string> = {
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
}

export function riskSummary(rows: SupplierDemandRow[]): string {
  const counts: Record<ShortageRisk, number> = { SHORT: 0, UNKNOWN: 0, AT_RISK: 0, COVERED: 0 };
  for (const row of rows) counts[row.risk] += 1;
  const spoken = RISK_BEFORE_AND.filter((risk) => counts[risk] > 0).map(
    (risk) => `${counts[risk]} ${RISK_PLURALS[risk]}`,
  );
  if (counts.COVERED > 0) spoken.push(`${counts.COVERED} covered`);
  if (spoken.length === 0) return "No forecast lines this week";
  if (spoken.length === 1) return spoken[0];
  return `${spoken.slice(0, -1).join(", ")} and ${spoken.at(-1)}`;
}

export function groupByProduct(rows: SupplierDemandRow[]): ProductGroup[] {
  const groups = new Map<string, ProductGroup>();
  for (const row of rows) {
    const current = groups.get(row.productId);
    if (current) {
      current.rows.push(row);
      if (RISK_ORDER[row.risk] < RISK_ORDER[current.worst]) current.worst = row.risk;
    } else {
      groups.set(row.productId, {
        productId: row.productId,
        productName: row.productName,
        unit: row.unit,
        rows: [row],
        worst: row.risk,
      });
    }
  }
  return [...groups.values()]
    .map((group) => ({ ...group, rows: [...group.rows].sort((a, b) => a.date.localeCompare(b.date)) }))
    .sort(
      (a, b) =>
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

/** Never settles, so an invalid week makes no API call and shows the error instead. */
function noWeek(): Promise<WeekSection> {
  return new Promise<WeekSection>(() => undefined);
}

async function loadWeek(api: Api, week: string): Promise<WeekSection> {
  const [monday, sunday] = [weekDates(week)[0], weekDates(week)[6]];
  const rows = await api.getSupplierDemand(monday, sunday);
  return { monday, sunday, label: weekLabel(week), summary: riskSummary(rows), groups: groupByProduct(rows) };
}

/** One product's days, in their own body so its name heads the row group. */
function ProductSection({ group }: { group: ProductGroup }) {
  return (
    <TableBody data-product-section={group.productId}>
      <TableRow className="border-b-0 bg-muted/40 hover:bg-muted/40">
        <TableHead scope="rowgroup" colSpan={6} className="py-2 align-top font-normal whitespace-normal">
          <div className="font-medium">{group.productName}</div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>{group.productId}</span>
            <span aria-hidden>·</span>
            <span>{RISK_PLURALS[group.worst]} this week</span>
            <span aria-hidden>·</span>
            <span>{group.rows.length} days</span>
          </div>
        </TableHead>
      </TableRow>
      {group.rows.map((row) => (
        <DemandRow key={row.date} row={row} />
      ))}
    </TableBody>
  );
}

function DemandRow({ row }: { row: SupplierDemandRow }) {
  return (
    <TableRow>
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
            title="The supplier has not measured availability for this product"
          >
            unknown
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
        <div className="text-xs text-muted-foreground">Buy</div>
        {row.suggestedBuy == null ? (
          <div className="font-medium text-warning">unknown</div>
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
  const [expanded, setExpanded] = useState(false);
  // The table and the phone list are both in the DOM, so each instance needs its own id.
  const listId = useId();
  if (row.byKitchen.length === 0) {
    return <span className="text-muted-foreground">No kitchens share this forecast</span>;
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
        {formatNumber(row.kitchens)} {row.kitchens === 1 ? "kitchen" : "kitchens"}{" "}
        <span className="sr-only">
          for {row.productName}, {formatDate(row.date)}
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

function MobileGroup({ group }: { group: ProductGroup }) {
  return (
    <li className="space-y-3 py-4">
      <div>
        <div className="font-medium">{group.productName}</div>
        <div className="text-xs text-muted-foreground">
          {group.productId} · {RISK_PLURALS[group.worst]} this week · {group.rows.length} days
        </div>
      </div>
      <ul className="space-y-3">
        {group.rows.map((row) => (
          <li key={row.date} className="rounded-md border p-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <span>{formatDate(row.date)}</span>
              <RiskBadge risk={row.risk} />
            </div>
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1">
              <dt className="text-muted-foreground">Forecast demand</dt>
              <dd className="text-right tabular-nums">
                {formatNumber(row.forecastDemand)} {row.unit}
              </dd>
              <dt className="text-muted-foreground">Kitchens</dt>
              <dd className="text-right">
                <KitchenDisclosure row={row} />
              </dd>
              <dt className="text-muted-foreground">Available</dt>
              <dd className="text-right tabular-nums">
                {row.available == null ? (
                  <span className="font-medium text-warning">unknown</span>
                ) : (
                  `${formatNumber(row.available)} ${row.unit}`
                )}
              </dd>
              <dt className="text-muted-foreground">Buy</dt>
              <dd
                className={row.suggestedBuy == null ? "text-right font-medium text-warning" : "text-right tabular-nums"}
              >
                {row.suggestedBuy == null ? "unknown" : `${formatNumber(row.suggestedBuy)} ${row.unit}`}
              </dd>
            </dl>
          </li>
        ))}
      </ul>
    </li>
  );
}

/** The ErrorState look, without a retry that would repeat the same bad request. */
function InvalidWeek({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="space-y-3 rounded-lg border border-destructive/40 p-4">
      <p className="text-sm">That week is not valid</p>
      <Button variant="outline" asChild>
        <Link to="/demand">{children}</Link>
      </Button>
    </div>
  );
}

export function DemandPage() {
  const api = useApi();
  const requestedWeek = useRouterState({
    select: (routerState) => new URLSearchParams(routerState.location.searchStr).get("week"),
  });
  const navigate = useNavigate();
  // Without `?week=` the page opens on next week: that is the demand Valio can still act on.
  const defaultWeek = shiftWeek(isoWeekOf(new Date().toISOString().slice(0, 10)), 1);
  const week = requestedWeek ?? defaultWeek;
  const weekIsValid = isValidWeek(week);
  const state = useAsync(() => (weekIsValid ? loadWeek(api, week) : noWeek()), [api, week, weekIsValid]);

  function showWeek(target: string) {
    void navigate({ to: "/demand", search: { week: target } });
  }

  return (
    <AppShell activeId="demand">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">Demand</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            What kitchens that share their forecast expect to need, against what is available.
          </p>
        </header>
        {weekIsValid ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => showWeek(shiftWeek(week, -1))}>
              Previous week
            </Button>
            <h2 className="px-2 text-center text-lg font-semibold">{weekLabel(week)}</h2>
            <Button variant="outline" onClick={() => showWeek(shiftWeek(week, 1))}>
              Next week
            </Button>
          </div>
        ) : null}
        {!weekIsValid ? (
          <div className="space-y-3">
            <InvalidWeek>Go to next week, {weekLabel(defaultWeek)}</InvalidWeek>
          </div>
        ) : null}
        {weekIsValid && state.status === "loading" ? <LoadingState label="Loading demand" /> : null}
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
              <EmptyState title="No demand forecast for this week">
                Kitchens that share forecasts have nothing planned for {state.data.label.toLowerCase()}.
              </EmptyState>
            ) : (
              <Card>
                <CardContent>
                  <div className="hidden md:block">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Date</TableHead>
                          <TableHead className="text-right">Forecast demand</TableHead>
                          <TableHead className="text-right">Kitchens</TableHead>
                          <TableHead>Available</TableHead>
                          <TableHead>Risk</TableHead>
                          <TableHead className="text-right">Buy</TableHead>
                        </TableRow>
                      </TableHeader>
                      {state.data.groups.map((group) => (
                        <ProductSection key={group.productId} group={group} />
                      ))}
                    </Table>
                  </div>
                  <ul className="divide-y md:hidden">
                    {state.data.groups.map((group) => (
                      <MobileGroup key={group.productId} group={group} />
                    ))}
                  </ul>
                </CardContent>
              </Card>
            )}
            <p className="text-sm text-muted-foreground">
              Forecasts come only from kitchens that agreed to share them.
            </p>
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
