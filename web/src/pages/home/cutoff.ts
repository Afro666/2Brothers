import type { Supplier } from "@/types";

const HELSINKI = "Europe/Helsinki";
const helsinkiDateTime = new Intl.DateTimeFormat("en-CA", {
  timeZone: HELSINKI,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function helsinkiParts(date: Date): { year: number; month: number; day: number; hour: number; minute: number } {
  const values = Object.fromEntries(helsinkiDateTime.formatToParts(date).map(({ type, value }) => [type, value]));
  return {
    year: Number(values.year),
    month: Number(values.month),
    day: Number(values.day),
    hour: Number(values.hour),
    minute: Number(values.minute),
  };
}

function helsinkiOffsetMs(instant: Date): number {
  const local = helsinkiParts(instant);
  return Date.UTC(local.year, local.month - 1, local.day, local.hour, local.minute) - instant.getTime();
}

function dateKey(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** Returns the next future supplier cut-off; wall-clock terms are Helsinki time. */
export function nextCutoff(supplier: Supplier, now: Date): Date | null {
  if (!supplier.orderDays?.length || !supplier.cutoffTime) return null;
  const [hour, minute] = supplier.cutoffTime.split(":").map(Number);
  const today = helsinkiParts(now);

  for (let offset = 0; offset <= 7; offset += 1) {
    const day = new Date(Date.UTC(today.year, today.month - 1, today.day + offset));
    const weekday = day.getUTCDay() || 7;
    if (!supplier.orderDays.includes(weekday)) continue;

    const [year, month, dayOfMonth] = dateKey(day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate())
      .split("-")
      .map(Number);
    const wallClock = Date.UTC(year, month - 1, dayOfMonth, hour, minute);
    let instant = new Date(wallClock - helsinkiOffsetMs(new Date(wallClock)));
    instant = new Date(wallClock - helsinkiOffsetMs(instant));
    if (instant.getTime() > now.getTime()) return instant;
  }
  return null;
}
