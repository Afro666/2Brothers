import { mapMoney } from "@/api/map";
import { ApiError } from "@/api/types";
import { isoWeekOf, weekDates } from "@/lib/week";
import type { ForecastAccuracy, ForecastScore, ForecastWeek } from "@/types";

/** One row of `GET /v1/kitchens/{k}/forecast-accuracy` (gateway/service.py, engine/forecast.py). */
interface AccuracyRow {
  predicted: number;
  actual: number;
  wape: number;
  bias: number;
  /** null when the products have two or more units (#1618): then `by_unit` has the sums. */
  under: number | null;
  over: number | null;
  /** Product-weeks compared. 0 means nothing was compared. */
  series: number;
  by_unit?: { unit: string | null; under: number; over: number }[];
  under_eur?: string | null;
  over_eur?: string | null;
  /** Product-weeks without a price: their short and waste are not in the euros. */
  unpriced_series?: number;
}
interface MethodBody {
  total: AccuracyRow;
  weeks: (AccuracyRow & { week: string })[];
}

function method(accuracy: unknown, name: string): MethodBody {
  const body = (accuracy as { methods?: Record<string, Partial<MethodBody>> } | null)?.methods?.[name];
  if (!body?.total || !Array.isArray(body.weeks)) {
    throw new ApiError("INVALID_RESPONSE", `forecast-accuracy has no "${name}" method.`);
  }
  return body as MethodBody;
}

type Figure = "predicted" | "actual" | "wape" | "bias" | "under" | "over";

/** With nothing compared the route still sends zeros: those are unknown, not zero. */
function known(row: AccuracyRow | undefined, field: Figure): number | null {
  const value = row?.[field];
  return row && row.series > 0 && typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** A euro total counts only priced products, so it is shown only when none is left out. */
function euros(row: AccuracyRow, field: "under_eur" | "over_eur"): number | null {
  const value = row[field];
  return row.series > 0 && row.unpriced_series === 0 && value != null ? mapMoney(value, field) : null;
}

function score(row: AccuracyRow): ForecastScore {
  const out: ForecastScore = {
    wape: known(row, "wape"),
    bias: known(row, "bias"),
    short: known(row, "under"),
    waste: known(row, "over"),
    // The route gives the quantities short and over, not days.
    stockOutDays: null,
  };
  if (row.series > 0 && Array.isArray(row.by_unit) && row.by_unit.length > 1) {
    // Two or more units: never one sum over kg, l and pieces (#1618).
    out.byUnit = row.by_unit.map((unit) => ({ unit: unit.unit, short: unit.under, waste: unit.over }));
    out.shortEur = euros(row, "under_eur");
    out.wasteEur = euros(row, "over_eur");
  }
  return out;
}

/**
 * `accuracy` is the body of `GET /v1/kitchens/{k}/forecast-accuracy?from=&to=` for the past weeks,
 * `forecast` the body of `GET /v1/kitchens/{k}/forecast?from=&to=` for the weeks ahead.
 * Both add products in different units, as the gateway does, so the kitchen has no unit.
 */
export function mapForecastAccuracy(accuracy: unknown, forecast: unknown): ForecastAccuracy {
  const engine = method(accuracy, "engine");
  const baseline = method(accuracy, "weekday-average");
  const engineWeeks = new Map(engine.weeks.map((row) => [row.week, row]));
  const baselineWeeks = new Map(baseline.weeks.map((row) => [row.week, row]));
  const weeks: ForecastWeek[] = [...new Set([...engineWeeks.keys(), ...baselineWeeks.keys()])].map((week) => {
    const ours = engineWeeks.get(week);
    const plain = baselineWeeks.get(week);
    return {
      week,
      actual: known(ours, "actual") ?? known(plain, "actual"),
      ahead: false,
      engine: known(ours, "predicted"),
      baseline: known(plain, "predicted"),
      engineWape: known(ours, "wape"),
      baselineWape: known(plain, "wape"),
    };
  });

  const lines = (forecast as { lines?: unknown } | null)?.lines;
  if (!Array.isArray(lines)) throw new ApiError("INVALID_RESPONSE", "forecast has no lines.");
  const ahead = new Map<string, number>();
  for (const line of lines as { date?: unknown; need?: unknown }[]) {
    if (typeof line?.date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(line.date)) {
      throw new ApiError("INVALID_RESPONSE", "A forecast line has no date.");
    }
    const week = isoWeekOf(line.date);
    // A week that is already scored keeps the forecast as it was made before that week.
    if (engineWeeks.has(week) || baselineWeeks.has(week)) continue;
    ahead.set(week, (ahead.get(week) ?? 0) + mapMoney(line.need, "need"));
  }
  for (const [week, need] of ahead) {
    weeks.push({
      week,
      actual: null,
      ahead: true,
      engine: Math.round(need * 1000) / 1000,
      baseline: null,
      engineWape: null,
      baselineWape: null,
    });
  }
  weeks.sort((a, b) => a.week.localeCompare(b.week));

  return {
    kitchen: {
      productId: null,
      name: "Whole kitchen",
      unit: null,
      engine: score(engine.total),
      baseline: score(baseline.total),
      weeks,
    },
    // The route scores the kitchen as a whole.
    products: null,
  };
}

/** The dates to ask the two routes for: the 12 full weeks before this week, then this week and the 3 after. */
export function forecastWindow(today: string) {
  const monday = weekDates(isoWeekOf(today))[0];
  const shift = (days: number) => {
    const date = new Date(`${monday}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
  };
  return { pastFrom: shift(-84), pastTo: shift(-1), aheadFrom: monday, aheadTo: shift(27) };
}
