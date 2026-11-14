import { describe, expect, it } from "vitest";

import { forecastWindow, mapForecastAccuracy } from "@/api/map-forecast";
import { forecastAccuracyMock } from "@/api/mock-forecast";

const row = (predicted: number, actual: number, wape: number, bias: number, under: number, over: number) => ({
  predicted,
  actual,
  wape,
  bias,
  under,
  over,
  series: 12,
});
const nothing = { predicted: 0, actual: 0, wape: 0.0, bias: 0.0, under: 0, over: 0, series: 0 };

/** The shape `gateway/service.py` sends (#313). */
const accuracy = {
  kitchen_id: "demo-kitchen",
  from: "2026-10-26",
  to: "2026-11-08",
  methods: {
    engine: {
      total: row(2010, 2000, 0.047, 0.005, 42, 52),
      weeks: [
        { week: "2026-W44", ...row(1000, 990, 0.04, 0.0101, 20, 30) },
        { week: "2026-W45", ...row(1010, 1010, 0.054, 0, 22, 22) },
      ],
    },
    "weekday-average": {
      total: row(1900, 2000, 0.114, -0.05, 164, 64),
      weeks: [
        { week: "2026-W44", ...row(900, 990, 0.12, -0.0909, 104, 14) },
        { week: "2026-W45", ...row(1000, 1010, 0.108, -0.0099, 60, 50) },
      ],
    },
  },
};
const line = (date: string, need: string) => ({
  product_id: "463335",
  date,
  need,
  unit: "L",
  made_on: null,
  why: null,
});
const forecast = {
  kitchen_id: "demo-kitchen",
  lines: [line("2026-11-08", "999"), line("2026-11-09", "10.5"), line("2026-11-15", "20"), line("2026-11-16", "7.25")],
};

describe("mapForecastAccuracy", () => {
  it("keeps engine-only history and marks the absent baseline unknown instead of zero", () => {
    const withoutBaseline = { ...accuracy, methods: { ...accuracy.methods, "weekday-average": { total: nothing, weeks: [] } } };
    const { kitchen } = mapForecastAccuracy(withoutBaseline, { lines: [] });
    expect(kitchen.engine.wape).toBe(0.047);
    expect(kitchen.baseline.wape).toBeNull();
    expect(kitchen.weeks).toHaveLength(2);
    expect(kitchen.weeks[0]).toMatchObject({ engine: 1000, actual: 990, baseline: null, baselineWape: null });
  });
  it("maps both methods, week by week, and adds the weeks ahead from the forecast", () => {
    const { kitchen, products } = mapForecastAccuracy(accuracy, forecast);

    expect(kitchen.engine).toEqual({ wape: 0.047, bias: 0.005, short: 42, waste: 52, stockOutDays: null });
    expect(kitchen.baseline).toEqual({ wape: 0.114, bias: -0.05, short: 164, waste: 64, stockOutDays: null });
    expect(kitchen.unit).toBeNull();
    expect(products).toBeNull();
    expect(kitchen.weeks).toEqual([
      { week: "2026-W44", actual: 990, ahead: false, engine: 1000, baseline: 900, engineWape: 0.04, baselineWape: 0.12 },
      { week: "2026-W45", actual: 1010, ahead: false, engine: 1010, baseline: 1000, engineWape: 0.054, baselineWape: 0.108 },
      // The 8 Nov line belongs to a scored week and is not counted again.
      { week: "2026-W46", actual: null, ahead: true, engine: 30.5, baseline: null, engineWape: null, baselineWape: null },
      { week: "2026-W47", actual: null, ahead: true, engine: 7.25, baseline: null, engineWape: null, baselineWape: null },
    ]);
  });

  it("keeps a zero bias when weeks were compared, and reads zeros with nothing compared as unknown", () => {
    expect(mapForecastAccuracy(accuracy, forecast).kitchen.weeks[1].engineWape).toBe(0.054);
    const empty = {
      methods: { engine: { total: nothing, weeks: [] }, "weekday-average": { total: nothing, weeks: [] } },
    };
    const { kitchen } = mapForecastAccuracy(empty, { lines: [] });
    expect(kitchen.engine).toEqual({ wape: null, bias: null, short: null, waste: null, stockOutDays: null });
    expect(kitchen.baseline.wape).toBeNull();
    expect(kitchen.weeks).toEqual([]);
  });

  it("shows a week only one method scored, with the other unknown", () => {
    const oneSided = structuredClone(accuracy);
    oneSided.methods["weekday-average"].weeks.pop();
    const week = mapForecastAccuracy(oneSided, { lines: [] }).kitchen.weeks[1];
    expect(week).toMatchObject({ week: "2026-W45", actual: 1010, ahead: false, engine: 1010, baseline: null, baselineWape: null });
  });

  it.each([
    ["no methods", {}, forecast],
    ["one method missing", { methods: { engine: accuracy.methods.engine } }, forecast],
    ["no lines", accuracy, {}],
    ["a need that is not a decimal string", accuracy, { lines: [{ date: "2026-11-20", need: 12 }] }],
    ["a line without a date", accuracy, { lines: [{ need: "12" }] }],
  ])("rejects %s", (_, accuracyBody, forecastBody) => {
    expect(() => mapForecastAccuracy(accuracyBody, forecastBody)).toThrow(
      expect.objectContaining({ code: "INVALID_RESPONSE" }),
    );
  });
});

describe("forecastWindow", () => {
  it("asks for the 12 full weeks before this week, then this week and the 3 after", () => {
    expect(forecastWindow("2026-11-14")).toEqual({
      pastFrom: "2026-08-17",
      pastTo: "2026-11-08",
      aheadFrom: "2026-11-09",
      aheadTo: "2026-12-06",
    });
    // A Monday is the first day of its own week.
    expect(forecastWindow("2026-11-09").aheadFrom).toBe("2026-11-09");
  });
});

describe("forecastAccuracyMock", () => {
  it("has 12 past weeks and 4 future weeks without actuals, the same on every call", () => {
    const { kitchen, products } = forecastAccuracyMock();
    expect(forecastAccuracyMock()).toEqual({ kitchen, products });

    for (const series of [kitchen, ...(products ?? [])]) {
      expect(series.weeks.map((week) => week.week)).toEqual(
        Array.from({ length: 16 }, (_, index) => `2026-W${34 + index}`),
      );
      const past = series.weeks.slice(0, 12);
      const ahead = series.weeks.slice(12);
      expect(past.every((week) => week.actual != null && week.baseline != null && week.engineWape != null)).toBe(true);
      expect(ahead.every((week) => week.actual === null && week.baseline === null && week.engineWape === null)).toBe(
        true,
      );
      expect(ahead.every((week) => (week.engine ?? 0) > 0)).toBe(true);
      expect(series.engine.wape).toBeLessThan(series.baseline.wape ?? 0);
    }
    expect(products).toHaveLength(5);
    expect(kitchen.engine).toEqual({ wape: 0.045, bias: 0.0054, short: 346, waste: 440, stockOutDays: 13 });
    // The kitchen's week is the sum of its products.
    expect(kitchen.weeks[0].actual).toBe((products ?? []).reduce((total, p) => total + (p.weeks[0].actual ?? 0), 0));
  });
});
