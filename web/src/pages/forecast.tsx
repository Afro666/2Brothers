import { ReadRefresh } from "@/components/purchasing/read-refresh";
import { useId, useState } from "react";

import { useApi } from "@/api";
import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { ForecastChart, formatQuantity } from "@/components/purchasing/forecast-chart";
import { LoadingState } from "@/components/purchasing/loading-state";
import { ProductThumb } from "@/components/purchasing/product-thumb";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAsync } from "@/lib/use-async";
import { COUNTED_AMOUNT_UNITS, formatCount, formatEur, formatPercentDecimal } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { weekRangeLabel } from "@/lib/week";
import type { ForecastAccuracy, ForecastScore, ForecastSeries } from "@/types";

const KITCHEN = "kitchen";

/** What the engine wins and what it costs, said only when the gateway's own numbers show exactly that. */
const EURO_SUMMARY =
  "In total the engine misses less (weekly error {wape}) and wastes less, about {waste} against {baselineWaste}, but with a larger shortfall: about {short} against {baselineShort}.";

export const GROUPS = ["Weekly error", "Stock-out days", "Waste"];

function percent(fraction: number | null, signed = false, missing = "unknown"): string {
  return formatPercentDecimal(fraction, signed, missing);
}

/** A line per unit; a counted unit is a whole count, never "668.35 PCS". */
function unitLine(amount: number, unit: string | null): string {
  return unit && COUNTED_AMOUNT_UNITS.has(unit.toUpperCase()) ? `${formatCount(amount)} ${unit}` : formatQuantity(amount, unit);
}

export const TILES: {
  label: string;
  hint: string;
  value: (score: ForecastScore, unit: string | null, t: ReturnType<typeof useT>) => string;
  /** Short or waste over two or more units: one line per unit, never one sum (#1618). */
  units?: "short" | "waste";
}[] = [
  {
    label: "Weekly error",
    hint: "The share of the need the forecast missed. Lower is better.",
    // The hint under the tile explains the error in words; the abbreviation on its own means nothing.
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
    hint: "Needed above the forecast. Euros are estimated from your latest order prices.",
    value: (score, unit, t) => quantityOrEuros(score, "short", unit, t),
    units: "short",
  },
  {
    label: "Waste",
    hint: "Forecast above the need. Euros are estimated from your latest order prices.",
    value: (score, unit, t) => quantityOrEuros(score, "waste", unit, t),
    units: "waste",
  },
];

/** One sum in one unit; over mixed units the euro value when every product has a price, else nothing. */
function quantityOrEuros(score: ForecastScore, key: "short" | "waste", unit: string | null, t: ReturnType<typeof useT>) {
  if (!score.byUnit) return formatQuantity(score[key], unit, t("unknown"));
  const eur = key === "short" ? score.shortEur : score.wasteEur;
  // Estimated: the latest order price per kitchen unit (gateway/forecast_value.py), never a booked figure.
  // The tile keeps "about" and the amount on one line (whitespace-nowrap in Figure).
  return eur == null ? "" : t("about {value}", { value: formatEur(eur) });
}

function Figure({ score, unit, tile, main }: { score: ForecastScore; unit: string | null; tile: (typeof TILES)[number]; main: boolean }) {
  const t = useT();
  const value = tile.value(score, unit, t);
  const lines = tile.units && score.byUnit ? score.byUnit.map((row) => unitLine(row[tile.units!], row.unit)) : [];
  return (
    <dd>
      {value ? (
        <span className={main ? "block text-xl leading-tight font-semibold break-words whitespace-nowrap" : "block text-sm font-medium whitespace-nowrap"}>
          {value}
        </span>
      ) : null}
      {lines.length ? (
        <ul className={value ? "text-xs text-muted-foreground" : main ? "text-base font-semibold" : "text-sm font-medium"}>
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
    </dd>
  );
}

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
  // A tile that would only say "unknown" for both methods says nothing: it is left out.
  const unknown = t("unknown");
  const tiles = TILES.filter((tile) =>
    [series.engine, series.baseline].some(
      (score) => (tile.units && score.byUnit?.length) || (tile.value(score, series.unit, t) && tile.value(score, series.unit, t) !== unknown),
    ),
  );
  const { engine, baseline } = series;
  const engineWins =
    engine.wape != null && baseline.wape != null && engine.wape < baseline.wape &&
    engine.wasteEur != null && baseline.wasteEur != null && engine.wasteEur < baseline.wasteEur &&
    engine.shortEur != null && baseline.shortEur != null && engine.shortEur > baseline.shortEur;
  const summary = engineWins
    ? t(EURO_SUMMARY, {
        wape: percent(engine.wape, false, t("unknown")),
        short: formatEur(engine.shortEur!),
        baselineShort: formatEur(baseline.shortEur!),
        waste: formatEur(engine.wasteEur!),
        baselineWaste: formatEur(baseline.wasteEur!),
      })
    : null;
  // A kitchen that mixes kg, l and pieces has no amount to plot: its chart is the weekly error, a share.
  const mixed = series.productId == null;
  const share = (fraction: number | null) => (fraction == null ? null : Math.round(fraction * 1000) / 10);
  const errorWeeks = series.weeks
    .filter((week) => !week.ahead)
    .map((week) => ({
      week: week.week,
      ahead: false,
      actual: null,
      engine: share(week.engineWape),
      baseline: share(week.baselineWape),
    }));
  const tableWeeks = mixed ? series.weeks.filter((week) => !week.ahead) : series.weeks;
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
              <SelectItem value={KITCHEN}>{t(data.kitchen.name)}</SelectItem>
              {data.products.map((product) => (
                <SelectItem key={product.productId} value={product.productId ?? KITCHEN}>
                  {/* The trigger copies this content, so the chosen product shows its picture too. */}
                  <ProductThumb en={product.name} size="sm" className="size-6" />
                  <span className="min-w-0 truncate">{product.name}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}

      <section aria-labelledby={`${selectId}-summary`} className="space-y-3">
        <div className="flex items-center gap-3">
          {series.productId ? <ProductThumb en={series.name} size="md" /> : null}
          <h2 id={`${selectId}-summary`} className="min-w-0 text-lg font-semibold break-words">
            {past === 1
              ? t("{name}: the last week", { name: series.productId ? series.name : t(series.name) })
              : t("{name}: the last {count} weeks", { name: series.productId ? series.name : t(series.name), count: past })}
          </h2>
        </div>
        <ul className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          {tiles.map((tile) => (
            <li key={tile.label} className="last:odd:col-span-2 lg:last:odd:col-span-1">
              <Card className="h-full gap-0 py-4">
                <CardContent className="space-y-1 px-4">
                  <h3 className="text-sm font-medium">{t(tile.label)}</h3>
                  <dl>
                    <dt className="text-xs text-muted-foreground">{t("Our engine")}</dt>
                    <Figure score={series.engine} unit={series.unit} tile={tile} main />
                    <dt className="mt-1 text-xs text-muted-foreground">{t("Weekday average")}</dt>
                    <Figure score={series.baseline} unit={series.unit} tile={tile} main={false} />
                  </dl>
                  <p className="text-xs text-muted-foreground">{t(tile.hint)}</p>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
        {summary ? <p className="max-w-prose text-sm text-muted-foreground">{summary}</p> : null}
      </section>

      <Card>
        <CardContent className="space-y-4">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold">
              {mixed
                ? t("Weekly error per week")
                : t("Needed and predicted per week, in {unit}", { unit: series.unit ?? "" })}
            </h2>
            <p className="text-sm text-muted-foreground">
              {mixed
                ? t("{past} past weeks. The whole kitchen mixes kilos, litres and pieces, so the chart shows the share of the need the forecast missed each week (lower is better), not an amount.", { past })
                : `${t("{past} past weeks, {future} future weeks with the forecast only.", {
                    past,
                    future: series.weeks.length - past,
                  })} ${t("In {unit}.", { unit: series.unit ?? "" })}`}
            </p>
          </div>
          {mixed ? (
            <ForecastChart weeks={errorWeeks} unit={null} axis="percent" />
          ) : (
            <ForecastChart weeks={series.weeks} unit={series.unit} />
          )}
          <details>
            <summary className="cursor-pointer rounded-sm text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
              {t("The weeks as a table")}
            </summary>
            <Table className="mt-2 tabular-nums">
              <TableHeader>
                <TableRow>
                  <TableHead>{t("Week")}</TableHead>
                  {mixed ? null : (
                    <>
                      <TableHead className="text-right">{t("Needed")}</TableHead>
                      <TableHead className="text-right">{t("Our engine")}</TableHead>
                      <TableHead className="text-right">{t("Weekday average")}</TableHead>
                    </>
                  )}
                  <TableHead className="text-right">{t("Error, our engine")}</TableHead>
                  <TableHead className="text-right">{t("Error, weekday average")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tableWeeks.map((week) => {
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
                      {mixed ? null : (
                        <>
                          <TableCell className="text-right">{formatQuantity(week.actual, series.unit, missing)}</TableCell>
                          <TableCell className="text-right">{formatQuantity(week.engine, series.unit, t("unknown"))}</TableCell>
                          <TableCell className="text-right">{formatQuantity(week.baseline, series.unit, t("unknown"))}</TableCell>
                        </>
                      )}
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

      <section aria-label={t("By product")} className="space-y-3">
        {/* Nothing under "By product": no heading over a single "unknown" line. */}
        {data.products ? (
          <h2 className="text-lg font-semibold">{t("By product")}</h2>
        ) : null}
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
                    <div className="flex items-center gap-2">
                      <ProductThumb en={product.name} size="sm" />
                      <div className="min-w-0">
                        {product.name}
                        <span className="block text-xs text-muted-foreground">{product.productId}</span>
                      </div>
                    </div>
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
            {t("Per product: unknown. The figures here are for the whole kitchen only.")}{" "}
            {t("The gateway sends one score for the whole kitchen, not one per product.")}
          </p>
        )}
      </section>
    </>
  );
}

export function ForecastPage() {
  const t = useT();
  const api = useApi();
  const state = useAsync(() => api.getForecastAccuracy(), [api], { keep: "forecast", scope: api });
  return (
    <AppShell activeId="forecast">
      <ReadRefresh refreshing={state.refreshing} outdated={state.outdated} reload={state.reload} />
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
