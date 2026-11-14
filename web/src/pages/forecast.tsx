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
import { useT } from "@/lib/i18n";
import { weekRangeLabel } from "@/lib/week";
import type { ForecastAccuracy, ForecastScore, ForecastSeries } from "@/types";

const KITCHEN = "kitchen";
export const GROUPS = ["Weekly error", "Stock-out days", "Waste"];

function percent(fraction: number | null, signed = false, missing = "unknown"): string {
  if (fraction == null) return missing;
  return `${signed && fraction > 0 ? "+" : ""}${(fraction * 100).toFixed(1)} %`;
}

export const TILES: {
  label: string;
  hint: string;
  value: (score: ForecastScore, unit: string | null, t: ReturnType<typeof useT>) => string;
}[] = [
  {
    label: "Weekly error (WAPE)",
    hint: "The share of the need the forecast missed. Lower is better.",
    value: (score, _unit, t) => percent(score.wape, false, t("unknown")),
  },
  {
    label: "Bias",
    hint: "Above zero: the forecast was too high.",
    value: (score, _unit, t) => percent(score.bias, true, t("unknown")),
  },
  {
    label: "Stock-out days",
    hint: "Days a product would have run out.",
    value: (score, _unit, t) => formatQuantity(score.stockOutDays, null, t("unknown")),
  },
  {
    label: "Short",
    hint: "Needed above the forecast.",
    value: (score, unit, t) => formatQuantity(score.short, unit, t("unknown")),
  },
  {
    label: "Waste",
    hint: "Forecast above the need.",
    value: (score, unit, t) => formatQuantity(score.waste, unit, t("unknown")),
  },
];

/** What the kitchen needed over the past weeks; null when no week has an actual. */
function needed(series: ForecastSeries): number | null {
  const actuals = series.weeks.flatMap((week) => week.actual ?? []);
  return actuals.length ? actuals.reduce((total, value) => total + value, 0) : null;
}

function ForecastView({ data }: { data: ForecastAccuracy }) {
  const t = useT();
  const selectId = useId();
  const [scope, setScope] = useState(KITCHEN);
  const series = data.products?.find((product) => product.productId === scope) ?? data.kitchen;

  if (data.kitchen.weeks.length === 0) {
    return (
      <EmptyState title={t("No forecast history yet")}>
        {t("Predicted against actual appears here once the kitchen has a forecast and a stock count for the same days.")}
      </EmptyState>
    );
  }

  const past = series.weeks.filter((week) => !week.ahead).length;
  return (
    <>
      {data.products ? (
        <div className="space-y-1.5 sm:max-w-xs">
          <Label htmlFor={selectId}>{t("Show")}</Label>
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
          {past === 1
            ? t("{name}: the last week", { name: series.name })
            : t("{name}: the last {count} weeks", { name: series.name, count: past })}
        </h2>
        <ul className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          {TILES.map((tile) => (
            <li key={tile.label} className="last:odd:col-span-2 lg:last:odd:col-span-1">
              <Card className="h-full gap-0 py-4">
                <CardContent className="space-y-1 px-4">
                  <h3 className="text-sm font-medium">{t(tile.label)}</h3>
                  <dl>
                    <dt className="text-xs text-muted-foreground">{t("Our engine")}</dt>
                    <dd className="text-2xl font-semibold">{tile.value(series.engine, series.unit, t)}</dd>
                    <dt className="mt-1 text-xs text-muted-foreground">{t("Weekday average")}</dt>
                    <dd className="text-sm font-medium">{tile.value(series.baseline, series.unit, t)}</dd>
                  </dl>
                  <p className="text-xs text-muted-foreground">{t(tile.hint)}</p>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      </section>

      <Card>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold">{t("Needed and predicted per week")}</h2>
            <p className="text-sm text-muted-foreground">
              {t("{past} past weeks, {future} future weeks with the forecast only.", {
                past,
                future: series.weeks.length - past,
              })}{" "}
              {series.unit ? t("In {unit}.", { unit: series.unit }) : t("Adds every product in its own unit.")}
            </p>
          </div>
          <ForecastChart weeks={series.weeks} unit={series.unit} />
          <details>
            <summary className="cursor-pointer rounded-sm text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {t("The weeks as a table")}
            </summary>
            <Table className="mt-2 tabular-nums">
              <TableHeader>
                <TableRow>
                  <TableHead>{t("Week")}</TableHead>
                  <TableHead className="text-right">{t("Needed")}</TableHead>
                  <TableHead className="text-right">{t("Our engine")}</TableHead>
                  <TableHead className="text-right">{t("Weekday average")}</TableHead>
                  <TableHead className="text-right">{t("Error, our engine")}</TableHead>
                  <TableHead className="text-right">{t("Error, weekday average")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {series.weeks.map((week) => {
                  // A future week has nothing to compare with yet; any other gap is unknown.
                  const missing = week.ahead ? t("not yet") : t("unknown");
                  return (
                    <TableRow key={week.week} data-week={week.week}>
                      <TableCell>
                        {t("Week {number}", { number: Number(week.week.slice(6)) })}
                        <span className="block text-xs text-muted-foreground">
                          {week.ahead ? t("Forecast only") : weekRangeLabel(week.week)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        {formatQuantity(week.actual, series.unit, missing)}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatQuantity(week.engine, series.unit, t("unknown"))}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatQuantity(week.baseline, series.unit, t("unknown"))}
                      </TableCell>
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
          {t("By product")}
        </h2>
        {data.products ? (
          <Table className="tabular-nums">
            <TableHeader>
              <TableRow>
                <TableHead rowSpan={2}>{t("Product")}</TableHead>
                <TableHead rowSpan={2} className="text-right">
                  {t("Needed")}
                </TableHead>
                {GROUPS.map((group) => (
                  <TableHead key={group} colSpan={2} scope="colgroup" className="text-center">
                    {t(group)}
                  </TableHead>
                ))}
              </TableRow>
              <TableRow>
                {GROUPS.flatMap((group) => [
                  <TableHead key={`${group}-engine`} className="text-right">
                    {t("Our engine")}
                  </TableHead>,
                  <TableHead key={`${group}-baseline`} className="text-right">
                    {t("Weekday average")}
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
                  <TableCell className="text-right">
                    {formatQuantity(needed(product), product.unit, t("unknown"))}
                  </TableCell>
                  <TableCell className="text-right">{percent(product.engine.wape, false, t("unknown"))}</TableCell>
                  <TableCell className="text-right">{percent(product.baseline.wape, false, t("unknown"))}</TableCell>
                  <TableCell className="text-right">
                    {formatQuantity(product.engine.stockOutDays, null, t("unknown"))}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatQuantity(product.baseline.stockOutDays, null, t("unknown"))}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatQuantity(product.engine.waste, product.unit, t("unknown"))}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatQuantity(product.baseline.waste, product.unit, t("unknown"))}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <p className="text-sm text-muted-foreground">
            {t("Per product: unknown. The figures here are for the whole kitchen only.")}
          </p>
        )}
      </section>
    </>
  );
}

export function ForecastPage() {
  const t = useT();
  const api = useApi();
  const state = useAsync(() => api.getForecastAccuracy(), [api]);
  return (
    <AppShell activeId="forecast">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">{t("Forecast vs actual")}</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t(
              "What the kitchen needed each week against what was predicted. Our engine (menu x covers x recipe) is next to the plain weekday average. Future weeks show the forecast only.",
            )}
          </p>
        </header>
        {state.status === "loading" ? <LoadingState label={t("Loading the forecast check")} /> : null}
        {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
        {state.status === "ready" ? <ForecastView data={state.data} /> : null}
      </div>
    </AppShell>
  );
}
