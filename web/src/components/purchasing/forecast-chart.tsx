import { type ReactNode, useId, useState } from "react";

import { formatNumber } from "@/lib/format";
import { weekRangeLabel } from "@/lib/week";
import type { ForecastWeek } from "@/types";

/** Plot area in px; the week numbers sit under it. Across, everything is a percentage, so it fits any width. */
const HEIGHT = 240;
const TOP = 28;
const BOTTOM = 204;

const ENGINE = "var(--primary)";
/** Lighter than the accent in light mode and darker in dark mode, so the two lines differ without hue. */
const BASELINE = "color-mix(in oklab, var(--muted-foreground) 70%, var(--card))";
const ACTUAL = "var(--foreground)";

const compact = new Intl.NumberFormat("en-IE", { notation: "compact" });

export function formatQuantity(value: number | null, unit: string | null, missing = "unknown"): string {
  return value == null ? missing : `${formatNumber(value)}${unit ? ` ${unit}` : ""}`;
}

/** Round axis steps (1, 2 or 5 times a power of ten), about four of them, covering `min` to `max`. */
export function axisTicks(min: number, max: number): number[] {
  const rough = (max - min || 1) / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map((factor) => factor * power).find((candidate) => candidate >= rough) ?? 10 * power;
  const first = Math.floor(min / step);
  const last = Math.max(Math.ceil(max / step), first + 1);
  return Array.from({ length: last - first + 1 }, (_, index) => (first + index) * step);
}

function Key({ color, dot = false }: { color: string; dot?: boolean }) {
  return (
    <span
      aria-hidden
      className={dot ? "inline-block size-2 rounded-full" : "inline-block h-0.5 w-4 rounded-full align-middle"}
      style={{ background: color }}
    />
  );
}

function TipRow({ label, value, children }: { label: string; value: string; children: ReactNode }) {
  return (
    <p className="flex items-center gap-1.5">
      {children}
      <span className="font-medium tabular-nums">{value}</span>
      <span className="text-muted-foreground">{label}</span>
    </p>
  );
}

/**
 * Needed against predicted per week: dots for what the kitchen needed, the accent line for our
 * engine, the grey line for the weekday average. Weeks ahead sit in a "Forecast only" band.
 */
export function ForecastChart({ weeks, unit }: { weeks: ForecastWeek[]; unit: string | null }) {
  const titleId = useId();
  const descId = useId();
  const [active, setActive] = useState<number | null>(null);

  const values = weeks.flatMap((week) => [week.actual, week.engine, week.baseline]).filter((value) => value != null);
  if (values.length === 0) return null;
  const ticks = axisTicks(Math.min(...values), Math.max(...values));
  const low = ticks[0];
  const span = ticks[ticks.length - 1] - low;
  const count = weeks.length;
  const center = (index: number) => ((index + 0.5) / count) * 100;
  const y = (value: number) => BOTTOM - ((value - low) / span) * (BOTTOM - TOP);
  const firstAhead = weeks.findIndex((week) => week.ahead);
  const past = firstAhead === -1 ? count : firstAhead;

  // shortcut: a method with a single week draws no line; the table below still gives its number.
  const line = (key: "engine" | "baseline", stroke: string) =>
    weeks.slice(1).map((week, index) => {
      const from = weeks[index][key];
      const to = week[key];
      return from == null || to == null ? null : (
        <line
          key={`${key}-${week.week}`}
          x1={`${center(index)}%`}
          y1={y(from)}
          x2={`${center(index + 1)}%`}
          y2={y(to)}
          stroke={stroke}
          strokeWidth={2}
          strokeLinecap="round"
        />
      );
    });

  const shown = active == null ? null : weeks[active];
  return (
    <div className="space-y-3">
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <li className="flex items-center gap-1.5">
          <Key color={ACTUAL} dot />
          Needed (actual)
        </li>
        <li className="flex items-center gap-1.5">
          <Key color={ENGINE} />
          Our engine
        </li>
        <li className="flex items-center gap-1.5">
          <Key color={BASELINE} />
          Weekday average
        </li>
      </ul>
      <div className="flex">
        <div
          aria-hidden
          className="relative w-10 shrink-0 text-[11px] text-muted-foreground tabular-nums"
          style={{ height: HEIGHT }}
        >
          {ticks.map((tick) => (
            <span key={tick} className="absolute right-1.5 -translate-y-1/2" style={{ top: y(tick) }}>
              {compact.format(tick)}
            </span>
          ))}
        </div>
        <div className="relative min-w-0 flex-1">
          <svg
            role="img"
            aria-labelledby={titleId}
            aria-describedby={descId}
            width="100%"
            height={HEIGHT}
            className="block overflow-visible"
            onPointerLeave={() => setActive(null)}
          >
            <title id={titleId}>{`Needed and predicted per week${unit ? `, in ${unit}` : ""}`}</title>
            <desc id={descId}>
              {`${past} past weeks with what the kitchen needed and both forecasts. ` +
                `${count - past} future weeks with the forecast only. The table below has the same numbers.`}
            </desc>
            {past < count ? (
              <>
                <rect
                  x={`${(past / count) * 100}%`}
                  width={`${((count - past) / count) * 100}%`}
                  y={0}
                  height={BOTTOM}
                  fill="var(--muted)"
                />
                <text
                  x={`${((past + count) / 2 / count) * 100}%`}
                  y={16}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[11px]"
                >
                  Forecast only
                </text>
              </>
            ) : null}
            {ticks.map((tick) => (
              <line key={tick} x1="0" x2="100%" y1={y(tick)} y2={y(tick)} stroke="var(--border)" />
            ))}
            {active != null ? (
              <line
                x1={`${center(active)}%`}
                x2={`${center(active)}%`}
                y1={TOP - 8}
                y2={BOTTOM}
                stroke="var(--muted-foreground)"
                strokeOpacity={0.5}
              />
            ) : null}
            {line("baseline", BASELINE)}
            {line("engine", ENGINE)}
            {weeks.map((week, index) =>
              week.actual == null ? null : (
                <circle
                  key={week.week}
                  cx={`${center(index)}%`}
                  cy={y(week.actual)}
                  r={4}
                  fill={ACTUAL}
                  stroke="var(--card)"
                  strokeWidth={2}
                />
              ),
            )}
            {weeks.map((week, index) => (
              <text
                key={week.week}
                x={`${center(index)}%`}
                y={HEIGHT - 12}
                textAnchor="middle"
                className="fill-muted-foreground text-[11px] tabular-nums"
              >
                {Number(week.week.slice(6))}
              </text>
            ))}
            {weeks.map((week, index) => (
              <rect
                key={week.week}
                x={`${(index / count) * 100}%`}
                width={`${100 / count}%`}
                y={0}
                height={HEIGHT}
                fill="transparent"
                onPointerEnter={() => setActive(index)}
              />
            ))}
          </svg>
          {shown && active != null ? (
            <div
              className="pointer-events-none absolute top-0 z-10 space-y-1 rounded-md border bg-popover px-2.5 py-1.5 text-xs whitespace-nowrap text-popover-foreground shadow-md"
              style={
                active < count / 2
                  ? { left: `calc(${center(active)}% + 8px)` }
                  : { right: `calc(${100 - center(active)}% + 8px)` }
              }
            >
              <p>
                <span className="font-medium">Week {Number(shown.week.slice(6))}</span>
                <span className="block text-muted-foreground">{weekRangeLabel(shown.week)}</span>
              </p>
              <TipRow label="Needed" value={formatQuantity(shown.actual, unit, shown.ahead ? "not yet" : "unknown")}>
                <Key color={ACTUAL} dot />
              </TipRow>
              <TipRow label="Our engine" value={formatQuantity(shown.engine, unit)}>
                <Key color={ENGINE} />
              </TipRow>
              <TipRow label="Weekday average" value={formatQuantity(shown.baseline, unit)}>
                <Key color={BASELINE} />
              </TipRow>
            </div>
          ) : null}
        </div>
      </div>
      <p className="text-center text-xs text-muted-foreground">Week of the year</p>
    </div>
  );
}
