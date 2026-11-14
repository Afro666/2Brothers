import type { ForecastAccuracy, ForecastScore, ForecastSeries } from "@/types";

const PAST_WEEKS = 12;
const FUTURE_WEEKS = 4;
/** 2026-W34 starts on 17 Aug, the first day of the demo history. */
const WEEKS = Array.from({ length: PAST_WEEKS + FUTURE_WEEKS }, (_, index) => `2026-W${34 + index}`);

const PRODUCTS = [
  // `price`: EUR before VAT per kitchen unit.
  { productId: "463335", name: "Valio Eila 3 % milk", unit: "L", level: 420, price: 1.4 },
  { productId: "462775", name: "Arla lactose-free milk", unit: "L", level: 180, price: 1.55 },
  { productId: "OWN-SALMON", name: "Salmon fillet", unit: "KG", level: 95, price: 24.85 },
  { productId: "OWN-RYE", name: "Rye bread loaf", unit: "PCS", level: 140, price: 4.2 },
  { productId: "OWN-BUN", name: "Cinnamon bun", unit: "PCS", level: 610, price: 2.1 },
];

type Method = "engine" | "baseline";
/** One product in one week. `need` is what the kitchen really used plus what it could not serve. */
interface Cell {
  need: number;
  engine: number;
  baseline: number;
}

/** A fixed swing between -1 and 1: the same numbers on every call, no random source. */
const swing = (week: number, product: number, salt: number) => Math.sin(week * 2.4 + product * 1.9 + salt);
const sum = (values: number[]) => values.reduce((total, value) => total + value, 0);
const round4 = (value: number) => Math.round(value * 10000) / 10000;

/** The menu moves the need; the engine follows the menu, the weekday average only the last four weeks. */
const GRID: Cell[][] = PRODUCTS.map((product, productIndex) => {
  const needs = WEEKS.map((_, week) => Math.round(product.level * (1 + 0.16 * swing(week, productIndex, 0))));
  return needs.map((need, week) => {
    const before = needs.slice(Math.max(0, week - 4), week);
    return {
      need,
      engine: Math.round(need * (1 + 0.07 * swing(week, productIndex, 1))),
      baseline: before.length ? Math.round(sum(before) / before.length) : product.level,
    };
  });
});

/** Same sums as `engine/forecast.py`, per product and week. Stock-out days assume a 5 % safety stock. */
function score(cells: Cell[], method: Method): ForecastScore {
  const need = sum(cells.map((cell) => cell.need));
  const total = (part: (predicted: number, actual: number) => number) =>
    sum(cells.map((cell) => part(cell[method], cell.need)));
  return {
    wape: round4(total((predicted, actual) => Math.abs(predicted - actual)) / need),
    bias: round4(total((predicted, actual) => predicted - actual) / need),
    short: total((predicted, actual) => Math.max(actual - predicted, 0)),
    waste: total((predicted, actual) => Math.max(predicted - actual, 0)),
    stockOutDays: total((predicted, actual) => Math.ceil((Math.max(actual * 0.95 - predicted, 0) * 7) / actual)),
  };
}

/** The whole kitchen has L, KG and PCS: like the gateway, short and waste per unit and in euros (#1618). */
function perUnit(method: Method): ForecastScore {
  const past = (index: number) => GRID[index].slice(0, PAST_WEEKS);
  const units = [...new Set(PRODUCTS.map((product) => product.unit))].sort();
  const eur = (key: "short" | "waste") =>
    Math.round(sum(PRODUCTS.map((product, index) => score(past(index), method)[key]! * product.price)) * 100) / 100;
  return {
    ...score(PRODUCTS.flatMap((_, index) => past(index)), method),
    short: null,
    waste: null,
    byUnit: units.map((unit) => {
      const scores = PRODUCTS.flatMap((product, index) => (product.unit === unit ? [score(past(index), method)] : []));
      return { unit, short: sum(scores.map((s) => s.short!)), waste: sum(scores.map((s) => s.waste!)) };
    }),
    shortEur: eur("short"),
    wasteEur: eur("waste"),
  };
}

/** `rows` is one product, or every product for the whole kitchen. */
function series(productId: string | null, name: string, unit: string | null, rows: Cell[][]): ForecastSeries {
  const past = rows.flatMap((row) => row.slice(0, PAST_WEEKS));
  return {
    productId,
    name,
    unit,
    engine: productId ? score(past, "engine") : perUnit("engine"),
    baseline: productId ? score(past, "baseline") : perUnit("baseline"),
    weeks: WEEKS.map((week, index) => {
      const cells = rows.map((row) => row[index]);
      const over = index < PAST_WEEKS;
      return {
        week,
        actual: over ? sum(cells.map((cell) => cell.need)) : null,
        ahead: !over,
        engine: sum(cells.map((cell) => cell.engine)),
        // Like the gateway: a future week has the engine's forecast only.
        baseline: over ? sum(cells.map((cell) => cell.baseline)) : null,
        engineWape: over ? score(cells, "engine").wape : null,
        baselineWape: over ? score(cells, "baseline").wape : null,
      };
    }),
  };
}

/** 12 past weeks and 4 future weeks for the demo kitchen. */
export function forecastAccuracyMock(): ForecastAccuracy {
  return {
    kitchen: series(null, "Whole kitchen", null, GRID),
    products: PRODUCTS.map((product, index) => series(product.productId, product.name, product.unit, [GRID[index]])),
  };
}
