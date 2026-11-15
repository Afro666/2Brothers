import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { mapForecastAccuracy } from "@/api/map-forecast";
import { createMockApi } from "@/api/mock";
import type { Api } from "@/api/types";
import { axisTicks } from "@/components/purchasing/forecast-chart";
import { updateLanguage } from "@/lib/i18n";
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
  beforeEach(() => {
    localStorage.clear();
    updateLanguage("en", false);
  });

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
    expect(tile("Weekly error")).toHaveTextContent("Our engine4.5 %Weekday average12.9 %");
    // The hint under it explains the error; the abbreviation alone means nothing to a buyer.
    expect(screen.queryByRole("heading", { name: /WAPE/ })).not.toBeInTheDocument();
    expect(tile("Bias")).toHaveTextContent("Our engine+0.5 %Weekday average+0.1 %");
    expect(tile("Stock-out days")).toHaveTextContent("Our engine13Weekday average29");
    // The mock's engine is also short less often: no sentence claims a trade-off the numbers do not show.
    expect(screen.queryByText(/In total the engine misses less/)).not.toBeInTheDocument();
    // The whole kitchen has L, KG and PCS: euros and one line per unit, never one sum (#1618).
    expect(tile("Waste")).not.toHaveTextContent("Our engine440");
    // A count of pieces has no decimals.
    expect(tile("Waste")).toHaveTextContent(
      "WasteOur engineabout €1,443.9024 KG183 L233 PCSWeekday averageabout €3,949.3572 KG453 L606 PCS",
    );

    // The kitchen mixes kg, l and pieces: its chart is the weekly error (a share), never one sum of amounts.
    const chart = screen.getByRole("img", { name: "Weekly error per week, in %" });
    expect(screen.getByRole("heading", { level: 2, name: "Weekly error per week" })).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("Adds every product in its own unit.");
    expect(chart).toHaveAccessibleDescription(/^12 past weeks/);
    // No dots (nothing was "needed" in this chart) and no band for weeks ahead.
    expect(chart.querySelectorAll("circle")).toHaveLength(0);
    expect(within(chart).queryByText("Forecast only")).not.toBeInTheDocument();
    // The axis names its unit on every tick.
    expect(within(chart.closest("div")!.parentElement!).getAllByText(/ %$/).length).toBeGreaterThan(1);
    // Except for a counted unit: no decimals, and the unit named.
    expect(tile("Waste")).toHaveTextContent("233 PCS");
    for (const name of ["Our engine", "Weekday average"]) {
      expect(screen.getAllByText(name).length).toBeGreaterThan(0);
    }
    expect(screen.queryByText("Needed (actual)")).not.toBeInTheDocument();

    const salmon = document.querySelector<HTMLElement>('tr[data-product="OWN-SALMON"]');
    expect(salmon).toHaveTextContent("Salmon fillet");
    expect(
      within(salmon!)
        .getAllByRole("cell")
        .map((cell) => {
          // The product picture is decorative (aria-hidden): only the cell's readable text counts.
          const copy = cell.cloneNode(true) as HTMLElement;
          copy.querySelectorAll("[aria-hidden]").forEach((node) => node.remove());
          return copy.textContent;
        }),
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

  it("tables the weekly error of the past weeks only, without amounts that mix units", async () => {
    renderApp("/forecast");
    const chart = await screen.findByRole("img", { name: "Weekly error per week, in %" });

    const rows = weekRows();
    expect(rows).toHaveLength(12);
    const cells = (row: HTMLElement) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent);
    expect(cells(rows[11])).toEqual(["Week 452 to 8 Nov 2026", "4.4 %", "11.5 %"]);

    // Pointing at a week reads out the same numbers.
    await userEvent.hover(chart.querySelectorAll('rect[fill="transparent"]')[11]);
    await waitFor(() => expect(document.body).toHaveTextContent(/Week 452 to 8 Nov 20264\.4 %Our engine11\.5 %Weekday average/));
  });

  it("plots a single product in its own unit, with the unit on the axis and the weeks ahead banded", async () => {
    const user = userEvent.setup();
    renderApp("/forecast");
    await user.click(await screen.findByRole("combobox", { name: "Show" }));
    await user.click(await screen.findByRole("option", { name: "Salmon fillet" }));

    const chart = await screen.findByRole("img", { name: "Needed and predicted per week, in KG" });
    expect(chart).toHaveAccessibleDescription(/^12 past weeks .* 4 future weeks with the forecast only\./);
    expect(chart.querySelectorAll("circle")).toHaveLength(12);
    expect(within(chart).getByText("Forecast only")).toBeInTheDocument();
    expect(within(chart.closest("div")!.parentElement!).getAllByText(/ KG$/).length).toBeGreaterThan(1);
    expect(weekRows()).toHaveLength(16);
  });

  it("follows the chosen product", async () => {
    const user = userEvent.setup();
    renderApp("/forecast");
    await user.click(await screen.findByRole("combobox", { name: "Show" }));
    const option = await screen.findByRole("option", { name: "Salmon fillet" });
    // Each product in the list has its picture; the picture is decorative, so the name is unchanged.
    expect(option.querySelector('[data-kind="fish and seafood"]')).not.toBeNull();
    await user.click(option);

    const heading = await screen.findByRole("heading", { level: 2, name: "Salmon fillet: the last 12 weeks" });
    expect(heading).toBeVisible();
    expect(heading.parentElement?.querySelector('[data-kind="fish and seafood"]')).not.toBeNull();
    // The trigger shows the chosen product with its picture too.
    expect(screen.getByRole("combobox", { name: "Show" }).querySelector('[data-kind="fish and seafood"]')).not.toBeNull();
    expect(tile("Waste")).toHaveTextContent("Our engine24 KGWeekday average72 KG");
    expect(screen.getByRole("img", { name: "Needed and predicted per week, in KG" })).toBeInTheDocument();
  });

  it("keeps 'about' and the amount together and names the axis unit", async () => {
    renderApp("/forecast");
    await screen.findByRole("heading", { level: 2, name: "Whole kitchen: the last 12 weeks" });
    // "about" never wraps away from its amount: one nowrap line.
    expect(within(tile("Short")).getByText("about €1,288.90")).toHaveClass("whitespace-nowrap");
  });

  it("writes Finnish percents with a comma, like the euros on the same page", async () => {
    // The language the person picked in Settings, stored before the app starts.
    localStorage.setItem("purchasing-language", "fi");
    updateLanguage("fi", false);
    renderApp("/forecast");
    expect(await screen.findByRole("heading", { level: 2, name: "Koko keittiö: viimeiset 12 viikkoa" })).toBeVisible();
    expect(tile("Viikkovirhe")).toHaveTextContent("Oma moottori4,5 %Viikonpäiväkeskiarvo12,9 %");
    expect(tile("Harha")).toHaveTextContent("Oma moottori+0,5 %");
    expect(tile("Puute")).toHaveTextContent("noin 1 288,90 €");
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
    expect(tile("Weekly error")).toHaveTextContent("Our engine5 %Weekday averageunknown");
    expect(tile("Bias")).toHaveTextContent("Our engine0 %Weekday averageunknown");
    // A tile that would only say "unknown" for both is left out.
    expect(screen.queryByRole("heading", { name: "Stock-out days" })).not.toBeInTheDocument();
    expect(tile("Waste")).toHaveTextContent("Our engine2Weekday averageunknown");
    expect(screen.getByText(/^Per product: unknown\./)).toBeInTheDocument();
    // Nothing under "By product": no heading over a single "unknown" line.
    expect(screen.queryByRole("heading", { name: "By product" })).not.toBeInTheDocument();
    // No euros sent: no sentence about what the engine wins is made up from nothing.
    expect(screen.queryByText(/In total the engine misses less/)).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Show" })).not.toBeInTheDocument();
  });

  it("calls a past week with no stock count unknown, not zero", async () => {
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

    // The kitchen mixes units: the chart is the weekly error of the weeks scored, so the gap week is a gap.
    const chart = await screen.findByRole("img", { name: "Weekly error per week, in %" });
    expect(chart).toHaveAccessibleDescription(/^3 past weeks/);

    const rows = weekRows();
    expect(rows.map((row) => row.dataset.week)).toEqual(["2026-W43", "2026-W44", "2026-W45"]);
    const gap = within(rows[1])
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    expect(gap.slice(1)).toEqual(["unknown", "unknown"]);
  });

  it("says what the engine wins and what it costs only when the gateway's euros show exactly that", async () => {
    const row = (wape: number, under: string, over: string) => ({
      predicted: 100, actual: 100, wape, bias: 0, under: null, over: null, series: 3, under_eur: under, over_eur: over, unpriced_series: 0,
      by_unit: [
        { unit: "KG", under: 1, over: 1, under_eur: under, over_eur: over },
        { unit: "L", under: 1, over: 1, under_eur: "0.00", over_eur: "0.00" },
      ],
    });
    const make = (engine: ReturnType<typeof row>, baseline: ReturnType<typeof row>) => ({
      methods: {
        engine: { total: engine, weeks: [{ week: "2026-W45", ...engine }] },
        "weekday-average": { total: baseline, weeks: [{ week: "2026-W45", ...baseline }] },
      },
    });
    renderApp(
      "/forecast",
      apiWith(async () => mapForecastAccuracy(make(row(0.05, "1413.80", "1155.00"), row(0.083, "1002.89", "2925.00")), { lines: [] })),
    );
    expect(
      await screen.findByText(
        "In total the engine misses less (WAPE 5 %) and its waste is about €1,155.00 against €2,925.00, at the cost of more short: about €1,413.80 against €1,002.89.",
      ),
    ).toBeInTheDocument();
    cleanup();

    // The engine wastes more: nothing is claimed.
    renderApp(
      "/forecast",
      apiWith(async () => mapForecastAccuracy(make(row(0.05, "1413.80", "3155.00"), row(0.083, "1002.89", "2925.00")), { lines: [] })),
    );
    await screen.findByRole("heading", { level: 2, name: "Whole kitchen: the last week" });
    expect(screen.queryByText(/In total the engine misses less/)).not.toBeInTheDocument();
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
    expect(await screen.findByRole("img", { name: "Weekly error per week, in %" })).toBeInTheDocument();
  });
});

describe("axisTicks", () => {
  it("gives round steps that cover the values", () => {
    expect(axisTicks(1276, 1622)).toEqual([1200, 1300, 1400, 1500, 1600, 1700]);
    expect(axisTicks(5, 5)).toEqual([5, 5.5]);
  });
});
