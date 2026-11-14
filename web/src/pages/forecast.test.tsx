import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { mapForecastAccuracy } from "@/api/map-forecast";
import { createMockApi } from "@/api/mock";
import type { Api } from "@/api/types";
import { axisTicks } from "@/components/purchasing/forecast-chart";
import { renderApp } from "@/test/render";
import type { ForecastAccuracy } from "@/types";

function apiWith(load: () => Promise<ForecastAccuracy>): Api {
  return { ...createMockApi(), getForecastAccuracy: load };
}

function tile(name: string): HTMLElement {
  const item = screen.getByRole("heading", { level: 3, name }).closest("li");
  if (!item) throw new Error(`No tile ${name}`);
  return item;
}

function weekRows(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>("tr[data-week]")];
}

describe("ForecastPage", () => {
  beforeEach(() => localStorage.clear());

  it("shows a loading state until the numbers arrive", async () => {
    renderApp(
      "/forecast",
      apiWith(() => new Promise(() => {})),
    );
    expect(await screen.findByRole("status", { name: "Loading the forecast check" })).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows our engine next to the weekday average: tiles, chart and products", async () => {
    renderApp("/forecast");

    expect(await screen.findByRole("heading", { level: 2, name: "Whole kitchen: the last 12 weeks" })).toBeVisible();
    expect(tile("Weekly error (WAPE)")).toHaveTextContent("Our engine4.5 %Weekday average12.8 %");
    expect(tile("Bias")).toHaveTextContent("Our engine+0.5 %Weekday average+0.1 %");
    expect(tile("Stock-out days")).toHaveTextContent("Our engine13Weekday average29");
    expect(tile("Waste")).toHaveTextContent("Our engine440Weekday average1,131");

    const chart = screen.getByRole("img", { name: "Needed and predicted per week" });
    expect(chart).toHaveAccessibleDescription(/^12 past weeks .* 4 future weeks with the forecast only\./);
    // One dot per week that has an actual.
    expect(chart.querySelectorAll("circle")).toHaveLength(12);
    expect(within(chart).getByText("Forecast only")).toBeInTheDocument();
    for (const name of ["Needed (actual)", "Our engine", "Weekday average"]) {
      expect(screen.getAllByText(name).length).toBeGreaterThan(0);
    }

    const salmon = document.querySelector<HTMLElement>('tr[data-product="OWN-SALMON"]');
    expect(salmon).toHaveTextContent("Salmon fillet");
    expect(
      within(salmon!)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual([
      "Salmon filletOWN-SALMON",
      expect.stringMatching(/^[\d,]+ KG$/),
      "4.4 %",
      "12.6 %",
      "3",
      "6",
      "24 KG",
      "72 KG",
    ]);
    expect(document.querySelectorAll("tr[data-product]")).toHaveLength(5);
  });

  it("gives future weeks a forecast and no actual", async () => {
    renderApp("/forecast");
    await screen.findByRole("img", { name: "Needed and predicted per week" });

    const rows = weekRows();
    expect(rows).toHaveLength(16);
    const cells = (row: HTMLElement) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent);
    expect(cells(rows[11])).toEqual(["Week 452 to 8 Nov 2026", "1,560", "1,565", "1,420", "4.4 %", "11.5 %"]);
    for (const row of rows.slice(12)) {
      const [week, needed, engine, baseline, engineError, baselineError] = cells(row);
      expect(week).toMatch(/^Week \d+Forecast only$/);
      expect(needed).toBe("not yet");
      expect(engine).toMatch(/^1,\d{3}$/);
      expect(baseline).toBe("unknown");
      expect([engineError, baselineError]).toEqual(["not yet", "not yet"]);
    }

    // Pointing at a week reads out the same numbers.
    const chart = screen.getByRole("img", { name: "Needed and predicted per week" });
    await userEvent.hover(chart.querySelectorAll('rect[fill="transparent"]')[12]);
    const readout = (await screen.findByText("9 to 15 Nov 2026")).closest("div");
    expect(readout).toHaveTextContent("Week 469 to 15 Nov 2026not yetNeeded1,276Our engineunknownWeekday average");
  });

  it("follows the chosen product", async () => {
    const user = userEvent.setup();
    renderApp("/forecast");
    await user.click(await screen.findByRole("combobox", { name: "Show" }));
    await user.click(await screen.findByRole("option", { name: "Salmon fillet" }));

    expect(await screen.findByRole("heading", { level: 2, name: "Salmon fillet: the last 12 weeks" })).toBeVisible();
    expect(tile("Waste")).toHaveTextContent("Our engine24 KGWeekday average72 KG");
    expect(screen.getByRole("img", { name: "Needed and predicted per week, in KG" })).toBeInTheDocument();
  });

  it("says unknown, never 0, for what the gateway does not give", async () => {
    const accuracy = {
      methods: {
        engine: {
          total: { predicted: 100, actual: 100, wape: 0.05, bias: 0, under: 2, over: 2, series: 3 },
          weeks: [{ week: "2026-W45", predicted: 100, actual: 100, wape: 0.05, bias: 0, under: 2, over: 2, series: 3 }],
        },
        "weekday-average": {
          total: { predicted: 0, actual: 0, wape: 0, bias: 0, under: 0, over: 0, series: 0 },
          weeks: [],
        },
      },
    };
    renderApp(
      "/forecast",
      apiWith(async () => mapForecastAccuracy(accuracy, { lines: [] })),
    );

    await screen.findByRole("heading", { level: 2, name: "Whole kitchen: the last week" });
    expect(tile("Weekly error (WAPE)")).toHaveTextContent("Our engine5.0 %Weekday averageunknown");
    expect(tile("Bias")).toHaveTextContent("Our engine0.0 %Weekday averageunknown");
    expect(tile("Stock-out days")).toHaveTextContent("Our engineunknownWeekday averageunknown");
    expect(tile("Waste")).toHaveTextContent("Our engine2Weekday averageunknown");
    expect(screen.getByText(/^Per product: unknown\./)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Show" })).not.toBeInTheDocument();
  });

  it("calls a past week with no stock count unknown, and starts the forecast band at the first week ahead", async () => {
    const scored = (week: string) => ({ week, predicted: 100, actual: 100, wape: 0.05, bias: 0, under: 2, over: 2, series: 3 });
    const blank = { predicted: 0, actual: 0, wape: 0, bias: 0, under: 0, over: 0, series: 0 };
    const weeks = [scored("2026-W43"), { week: "2026-W44", ...blank }, scored("2026-W45")];
    const accuracy = {
      methods: {
        engine: { total: scored("total"), weeks },
        "weekday-average": { total: scored("total"), weeks },
      },
    };
    renderApp(
      "/forecast",
      apiWith(async () => mapForecastAccuracy(accuracy, { lines: [{ date: "2026-11-10", need: "50" }] })),
    );

    const chart = await screen.findByRole("img", { name: "Needed and predicted per week" });
    expect(chart).toHaveAccessibleDescription(/^3 past weeks .* 1 future weeks with the forecast only\./);
    expect(chart.querySelector('rect[x="75%"]')).toHaveAttribute("width", "25%");

    const rows = weekRows();
    expect(rows.map((row) => row.dataset.week)).toEqual(["2026-W43", "2026-W44", "2026-W45", "2026-W46"]);
    const gap = within(rows[1])
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    expect(gap[0]).not.toContain("Forecast only");
    expect(gap.slice(1)).toEqual(["unknown", "unknown", "unknown", "unknown", "unknown"]);
    expect(rows[3]).toHaveTextContent("Forecast only");
    expect(within(rows[3]).getAllByRole("cell")[1]).toHaveTextContent("not yet");
  });

  it("says so when the kitchen has no forecast history", async () => {
    const nothing = { total: { predicted: 0, actual: 0, wape: 0, bias: 0, under: 0, over: 0, series: 0 }, weeks: [] };
    renderApp(
      "/forecast",
      apiWith(async () =>
        mapForecastAccuracy({ methods: { engine: nothing, "weekday-average": nothing } }, { lines: [] }),
      ),
    );
    expect(await screen.findByRole("heading", { name: "No forecast history yet" })).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows the error and loads again on Try again", async () => {
    let calls = 0;
    const mock = createMockApi();
    renderApp(
      "/forecast",
      apiWith(() => (calls++ === 0 ? Promise.reject(new Error("The gateway is down.")) : mock.getForecastAccuracy())),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("The gateway is down.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("img", { name: "Needed and predicted per week" })).toBeInTheDocument();
  });
});

describe("axisTicks", () => {
  it("gives round steps that cover the values", () => {
    expect(axisTicks(1276, 1622)).toEqual([1200, 1300, 1400, 1500, 1600, 1700]);
    expect(axisTicks(5, 5)).toEqual([5, 5.5]);
  });
});
