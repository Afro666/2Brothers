/**
 * Formatting helpers. Every time is shown in Helsinki time, the zone of
 * Valio's server and of the restaurant, whatever the browser's zone is.
 */

/** Valio's "stock not measured" values (docs/valio-data.md). Never show them as stock. */
export const UNKNOWN_STOCK_SENTINELS: readonly number[] = [999999, 9999999999];

export function isUnknownStock(amount: number | null | undefined): boolean {
  return amount == null || UNKNOWN_STOCK_SENTINELS.includes(amount);
}

const TZ = "Europe/Helsinki";

const eur = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" });
const num = new Intl.NumberFormat("en-IE");

export function formatEur(value: number | null): string {
  return value == null ? "price unknown" : eur.format(value);
}

export function formatNumber(value: number): string {
  return num.format(value);
}

/** Stock in sales units, or "unknown" for a sentinel / missing value. */
export function formatStock(amount: number | null | undefined, unit: string): string {
  if (isUnknownStock(amount)) return "unknown";
  return `${num.format(amount as number)} ${unit}`;
}

const dateFmt = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: TZ,
});

const dateTimeFmt = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: TZ,
});

const timeFmt = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: TZ,
});

/** A `YYYY-MM-DD` date is read as noon Helsinki, so it never shifts a day. */
function toDate(value: string): Date {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00+02:00`) : new Date(value);
}

export function formatDate(value: string | null): string {
  return value == null ? "unknown" : dateFmt.format(toDate(value));
}

export function formatDateTime(value: string | null): string {
  return value == null ? "unknown" : dateTimeFmt.format(toDate(value));
}

export function formatTime(value: string): string {
  return timeFmt.format(toDate(value));
}

/** True when a cut-off is at or before `now`. A missing cut-off is not "passed". */
export function isPassed(closingTime: string | null, now: Date): boolean {
  return closingTime != null && new Date(closingTime).getTime() <= now.getTime();
}

/** True when the offer arrives after the date that was asked for. */
export function isLater(availableDate: string | null, requestedDate: string): boolean {
  return availableDate != null && availableDate.slice(0, 10) > requestedDate.slice(0, 10);
}

export function formatPercent(fraction: number | null): string {
  return fraction == null ? "unknown" : `${Math.round(fraction * 100)} %`;
}

/** "KI 12 × 1 L": the pack a sales unit holds, from the catalog `units[]`. */
export function formatPack(salesUnit: string, baseUnitsPerSalesUnit: number, baseUnit: string): string {
  return `${salesUnit} = ${formatNumber(baseUnitsPerSalesUnit)} ${baseUnit}`;
}
