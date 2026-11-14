import { useId, useState } from "react";

import { useApi } from "@/api";
import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { ForecastChart, formatQuantity } from "@/components/purchasing/forecast-chart";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAsync } from "@/lib/use-async";
import { weekRangeLabel } from "@/lib/week";
import type { ForecastAccuracy, ForecastScore, ForecastSeries } from "@/types";

const KITCHEN = "kitchen";
const GROUPS = ["Weekly error", "Stock-out days", "Waste"];

function percent(fraction: number | null, signed = false, missing = "unknown"): string {
  if (fraction == null) return missing;
  return `${signed && fraction > 0 ? "+" : ""}${(fraction * 100).toFixed(1)} %`;
}

const TILES: { label: string; hint: string; value: (score: ForecastScore, unit: string | null) => string }[] = [
  {
    label: "Weekly error (WAPE)",
    hint: "The share of the need the forecast missed. Lower is better.",
    value: (score) => percent(score.wape),
  },
  {
    label: "Bias",
    hint: "Above zero: the forecast was too high.",
    value: (score) => percent(score.bias, true),
  },
  {
    label: "Stock-out days",
    hint: "Days a product would have run out.",
    value: (score) => formatQuantity(score.stockOutDays, null),
  },
  {
    label: "Short",
    hint: "Needed above the forecast.",
    value: (score, unit) => formatQuantity(score.short, unit),
  },
  {
    label: "Waste",
    hint: "Forecast above the need.",
    value: (score, unit) => formatQuantity(score.waste, unit),
  },
];

/** What the kitchen needed over the past weeks; null when no week has an actual. */
function needed(series: ForecastSeries): number | null {
  const actuals = series.weeks.flatMap((week) => week.actual ?? []);
  return actuals.length ? actuals.reduce((total, value) => total + value, 0) : null;
}

function ForecastView({ data }: { data: ForecastAccuracy }) {
  const selectId = useId();
  const [scope, setScope] = useState(KITCHEN);
  const series = data.products?.find((product) => product.productId === scope) ?? data.kitchen;

  if (data.kitchen.weeks.length === 0) {
    return (
      <EmptyState title="No forecast history yet">
        Predicted against actual appears here once the kitchen has a forecast and a stock count for the same days.
      </EmptyState>
    );
  }

  const past = series.weeks.filter((week) => week.actual != null).length;
  return (
    <>
      {data.products ? (
        <div className="space-y-1.5 sm:max-w-xs">
          <Label htmlFor={selectId}>Show</Label>
          <Select value={scope} onValueChange={setScope}>
            <SelectTrigger id={selectId} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={KITCHEN}>{data.kitchen.name}</SelectItem>
              {data.products.map((product) => (
                <SelectItem key={product.productId} value={product.productId ?? KITCHEN}>
                  {product.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}

      <section aria-labelledby={`${selectId}-summary`} className="space-y-3">
        <h2 id={`${selectId}-summary`} className="text-lg font-semibold">
          {series.name}: the last {past === 1 ? "week" : `${past} weeks`}
        </h2>
        <ul className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          {TILES.map((tile) => (
            <li key={tile.label}>
              <Card className="h-full gap-0 py-4">
                <CardContent className="space-y-1 px-4">
                  <h3 className="text-sm font-medium">{tile.label}</h3>
                  <dl>
                    <dt className="text-xs text-muted-foreground">Our engine</dt>
                    <dd className="text-2xl font-semibold">{tile.value(series.engine, series.unit)}</dd>
                    <dt className="mt-1 text-xs text-muted-foreground">Weekday average</dt>
                    <dd className="text-sm font-medium">{tile.value(series.baseline, series.unit)}</dd>
                  </dl>
                  <p className="text-xs text-muted-foreground">{tile.hint}</p>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      </section>

      <Card>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold">Needed and predicted per week</h2>
            <p className="text-sm text-muted-foreground">
              {past} past weeks, {series.weeks.length - past} future weeks with the forecast only.{" "}
              {series.unit ? `In ${series.unit}.` : "Adds every product in its own unit."}
            </p>
          </div>
          <ForecastChart weeks={series.weeks} unit={series.unit} />
          <details>
            <summary className="cursor-pointer rounded-sm text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
              The weeks as a table
            </summary>
            <Table className="mt-2 tabular-nums">
              <TableHeader>
                <TableRow>
                  <TableHead>Week</TableHead>
                  <TableHead className="text-right">Needed</TableHead>
                  <TableHead className="text-right">Our engine</TableHead>
                  <TableHead className="text-right">Weekday average</TableHead>
                  <TableHead className="text-right">Error, our engine</TableHead>
                  <TableHead className="text-right">Error, weekday average</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {series.weeks.map((week) => {
                  // A future week has nothing to compare with yet; any other gap is unknown.
                  const missing = week.actual == null ? "not yet" : "unknown";
                  return (
                    <TableRow key={week.week} data-week={week.week}>
                      <TableCell>
                        Week {Number(week.week.slice(6))}
                        <span className="block text-xs text-muted-foreground">
                          {week.actual == null ? "Forecast only" : weekRangeLabel(week.week)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        {formatQuantity(week.actual, series.unit, "not yet")}
                      </TableCell>
                      <TableCell className="text-right">{formatQuantity(week.engine, series.unit)}</TableCell>
                      <TableCell className="text-right">{formatQuantity(week.baseline, series.unit)}</TableCell>
                      <TableCell className="text-right">{percent(week.engineWape, false, missing)}</TableCell>
                      <TableCell className="text-right">{percent(week.baselineWape, false, missing)}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </details>
        </CardContent>
      </Card>

      <section aria-labelledby={`${selectId}-products`} className="space-y-3">
        <h2 id={`${selectId}-products`} className="text-lg font-semibold">
          By product
        </h2>
        {data.products ? (
          <Table className="tabular-nums">
            <TableHeader>
              <TableRow>
                <TableHead rowSpan={2}>Product</TableHead>
                <TableHead rowSpan={2} className="text-right">
                  Needed
                </TableHead>
                {GROUPS.map((group) => (
                  <TableHead key={group} colSpan={2} scope="colgroup" className="text-center">
                    {group}
                  </TableHead>
                ))}
              </TableRow>
              <TableRow>
                {GROUPS.flatMap((group) => [
                  <TableHead key={`${group}-engine`} className="text-right">
                    Our engine
                  </TableHead>,
                  <TableHead key={`${group}-baseline`} className="text-right">
                    Weekday average
                  </TableHead>,
                ])}
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.products.map((product) => (
                <TableRow key={product.productId} data-product={product.productId}>
                  <TableCell>
                    {product.name}
                    <span className="block text-xs text-muted-foreground">{product.productId}</span>
                  </TableCell>
                  <TableCell className="text-right">{formatQuantity(needed(product), product.unit)}</TableCell>
                  <TableCell className="text-right">{percent(product.engine.wape)}</TableCell>
                  <TableCell className="text-right">{percent(product.baseline.wape)}</TableCell>
                  <TableCell className="text-right">{formatQuantity(product.engine.stockOutDays, null)}</TableCell>
                  <TableCell className="text-right">{formatQuantity(product.baseline.stockOutDays, null)}</TableCell>
                  <TableCell className="text-right">{formatQuantity(product.engine.waste, product.unit)}</TableCell>
                  <TableCell className="text-right">{formatQuantity(product.baseline.waste, product.unit)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="text-sm text-muted-foreground">
            Per product: unknown. The figures here are for the whole kitchen only.
          </p>
        )}
      </section>
    </>
  );
}

export function ForecastPage() {
  const api = useApi();
  const state = useAsync(() => api.getForecastAccuracy(), [api]);
  return (
    <AppShell activeId="forecast">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">Forecast check</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            What the kitchen needed each week against what was predicted. Our engine (menu x covers x recipe) is next to
            the plain weekday average. Future weeks show the forecast only.
          </p>
        </header>
        {state.status === "loading" ? <LoadingState label="Loading the forecast check" /> : null}
        {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
        {state.status === "ready" ? <ForecastView data={state.data} /> : null}
      </div>
    </AppShell>
  );
}
