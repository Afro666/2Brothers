import { formatDate, formatNumber } from "@/lib/format";
import { isoWeekOf, weekDates } from "@/lib/week";
import { useAsync, type AsyncState } from "@/lib/use-async";
import type { Api } from "@/api/types";
import type { SupplierDemandRow } from "@/types";

import { SampleData } from "@/components/purchasing/sample-data";
import { useT } from "@/lib/i18n";
import { Tile, TileState } from "@/pages/home/tile";

export type SupplierDemandResult = { rows: SupplierDemandRow[]; week: string; fallback: boolean };

/** Loads supplier demand once for the Valio dashboard; both tiles share the result. */
export function useSupplierDemand(api: Api, now: Date): AsyncState<SupplierDemandResult> {
  return useAsync(() => loadSupplierDemand(api, now), [api, now.toISOString()]);
}

function loadSupplierDemand(api: Api, now: Date): Promise<SupplierDemandResult> {
  const today = now.toLocaleDateString("en-CA", { timeZone: "Europe/Helsinki" });
  const currentWeek = isoWeekOf(today);
  const [monday, , , , , , sunday] = weekDates(currentWeek);
  return api.getSupplierDemand(monday, sunday).then((rows) => {
    if (rows.length > 0) return { rows, week: currentWeek, fallback: false };

    const nextWeekDates = weekDates(isoWeekOf(addDays(sunday, 1)));
    const [nextMonday, , , , , , nextSunday] = nextWeekDates;
    return api.getSupplierDemand(nextMonday, nextSunday).then((nextRows) => ({
      rows: nextRows,
      week: isoWeekOf(nextMonday),
      fallback: true,
    }));
  });
}

function addDays(date: string, days: number): string {
  const value = new Date(`${date}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

const riskOrder: Record<SupplierDemandRow["risk"], number> = { SHORT: 0, AT_RISK: 1, UNKNOWN: 2, COVERED: 3 };

export function ShortageTile({ state, now }: { state: AsyncState<SupplierDemandResult>; now: Date }) {
  const t = useT();
  const currentWeek = isoWeekOf(now.toLocaleDateString("en-CA", { timeZone: "Europe/Helsinki" }));
  const shownWeek = state.status === "ready" ? state.data.week : currentWeek;
  const [weekMonday, , , , , , weekSunday] = weekDates(shownWeek);
  return (
    <Tile
      title={t("Shortage risk, week {week} · {start}–{end}", {
        week: Number(shownWeek.slice(-2)),
        start: formatDate(weekMonday),
        end: formatDate(weekSunday),
      })}
      href="/demand"
      linkLabel={t("Open demand view")}
    >
      <SampleData of="getSupplierDemand" />
      <TileState<SupplierDemandResult>
        status={state.status}
        error={state.error}
        reload={state.reload}
        data={state.status === "ready" ? state.data : null}
        empty={state.status === "ready" && state.data.rows.length === 0}
      >
        {({ rows, fallback }: { rows: SupplierDemandRow[]; fallback: boolean }) => {
          const counts = { SHORT: 0, UNKNOWN: 0, AT_RISK: 0 };
          rows.forEach((row) => {
            if (row.risk in counts) counts[row.risk as keyof typeof counts] += 1;
          });
          const worst = [...rows]
            .sort((a, b) => riskOrder[a.risk] - riskOrder[b.risk] || b.forecastDemand - a.forecastDemand)
            .slice(0, 5);
          return (
            <div className="space-y-4">
              {fallback && (
                <p className="text-sm text-muted-foreground">
                  {t("No forecasts for this week yet; showing next week.")}
                </p>
              )}
              <p className="text-sm tabular-nums">
                <span className="font-semibold">{counts.SHORT}</span> {t("SHORT")} ·{" "}
                <span className="font-semibold">{counts.UNKNOWN}</span> {t("UNKNOWN")} ·{" "}
                <span className="font-semibold">{counts.AT_RISK}</span> {t("AT_RISK")}
              </p>
              <ul className="space-y-3 text-sm">
                {worst.map((row) => (
                  <li key={`${row.productId}-${row.date}`} className="space-y-1">
                    <p className="font-medium">
                      {row.productName} · {formatDate(row.date)}
                    </p>
                    <p className="tabular-nums text-muted-foreground">
                      {t("Forecast {forecast} {unit}; available", {
                        forecast: formatNumber(row.forecastDemand),
                        unit: row.unit,
                      })}{" "}
                      {row.available === null ? (
                        <span className="unknown-value">{t("unknown")}</span>
                      ) : (
                        `${formatNumber(row.available)} ${row.unit}`
                      )}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          );
        }}
      </TileState>
    </Tile>
  );
}

export function KitchensTile({ state }: { state: AsyncState<SupplierDemandResult> }) {
  const t = useT();
  return (
    <Tile title={t("Kitchens sharing forecasts")} href="/demand" linkLabel={t("Open demand view")}>
      <SampleData of="getSupplierDemand" />
      <TileState<SupplierDemandRow[]>
        status={state.status}
        error={state.error}
        reload={state.reload}
        data={state.status === "ready" ? state.data.rows : null}
        empty={state.status === "ready" && state.data.rows.length === 0}
      >
        {(rows: SupplierDemandRow[]) => (
          <div>
            <p className="text-3xl font-semibold tabular-nums">{Math.max(...rows.map((row) => row.kitchens))}</p>
            <p className="mt-2 text-sm text-muted-foreground">
              {t("Only kitchens that agreed to share appear here.")}
            </p>
          </div>
        )}
      </TileState>
    </Tile>
  );
}
