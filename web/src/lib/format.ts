/**
 * Formatting helpers. Every time is shown in Helsinki time, the zone of
 * Valio's server and of the restaurant, whatever the browser's zone is.
 */
import { getAppearance } from "@/lib/appearance";
import { getLanguage } from "@/lib/i18n";

/** Valio's "stock not measured" values (docs/valio-data.md). Never show them as stock. */
export const UNKNOWN_STOCK_SENTINELS: readonly number[] = [999999, 9999999999];

export function isUnknownStock(amount: number | null | undefined): boolean {
  return amount == null || UNKNOWN_STOCK_SENTINELS.includes(amount);
}

type OfferStock = { availableAmount: number | null; stockConfirmed?: boolean; salesUnit: string };

/** Stock is unconfirmed unless it is measured, or the supplier confirmed it without giving the amount. */
export function isStockUnconfirmed(offer: OfferStock): boolean {
  return isUnknownStock(offer.availableAmount) && !offer.stockConfirmed;
}

export function formatOfferStock(offer: OfferStock): string {
  return isUnknownStock(offer.availableAmount) && offer.stockConfirmed
    ? "confirmed"
    : formatStock(offer.availableAmount, offer.salesUnit);
}

const TZ = "Europe/Helsinki";

// The viewer picks the number and date format in Settings > Appearance.
const NUMBER_LOCALE = { comma: "en-IE", space: "fi-FI" } as const;
const eur = {
  comma: new Intl.NumberFormat(NUMBER_LOCALE.comma, { style: "currency", currency: "EUR" }),
  space: new Intl.NumberFormat(NUMBER_LOCALE.space, { style: "currency", currency: "EUR" }),
};
const num = {
  comma: new Intl.NumberFormat(NUMBER_LOCALE.comma),
  space: new Intl.NumberFormat(NUMBER_LOCALE.space),
};

export function formatEur(value: number | null): string {
  return value == null ? "price unknown" : eur[getAppearance().numberFormat].format(value);
}

export function formatNumber(value: number): string {
  return num[getAppearance().numberFormat].format(value);
}

/** Units a kitchen weighs or measures; every other unit (PCS, ST, KI, ...) is counted. */
const MEASURED_UNITS = new Set(["KG", "G", "L", "DL", "CL", "ML"]);

/**
 * A shortfall rounded up, so it is never understated: a whole number for counted
 * units, at most one decimal for weights and volumes. "1,922 PCS", "41.5 KG".
 */
export function formatShortfall(amount: number, unit: string): string {
  const step = MEASURED_UNITS.has(unit.toUpperCase()) ? 10 : 1;
  // The small epsilon keeps float noise (41.4 * 10 = 413.99...) from rounding up a step.
  const rounded = Math.ceil(amount * step - 1e-9) / step;
  return `${formatNumber(rounded)} ${unit}`;
}

/** Stock in sales units, or "unknown" for a sentinel / missing value. */
export function formatStock(amount: number | null | undefined, unit: string): string {
  if (isUnknownStock(amount)) return "unknown";
  return `${formatNumber(amount as number)} ${unit}`;
}

const weekdayFmt = {
  en: new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: TZ }),
  fi: new Intl.DateTimeFormat("fi-FI", { weekday: "short", timeZone: TZ }),
};
const dayMonthFmt = new Intl.DateTimeFormat("fi-FI", { day: "numeric", month: "numeric", timeZone: TZ });
const dateFmt = {
  dmy: new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: TZ }),
  mdy: new Intl.DateTimeFormat("en-US", { weekday: "short", day: "numeric", month: "short", timeZone: TZ }),
};
const finnishDayFmt = new Intl.DateTimeFormat("fi-FI", { day: "numeric", timeZone: TZ });
const finnishMonthNumberFmt = new Intl.DateTimeFormat("fi-FI", { month: "numeric", timeZone: TZ });
const FINNISH_MONTHS = [
  "tammik.",
  "helmik.",
  "maalisk.",
  "huhtik.",
  "toukok.",
  "kesäk.",
  "heinäk.",
  "elok.",
  "syysk.",
  "lokak.",
  "marrask.",
  "jouluk.",
];

function dateText(date: Date): string {
  const language = getLanguage();
  const format = getAppearance().dateFormat;
  if (format === "numeric") return `${weekdayFmt[language].format(date)} ${dayMonthFmt.format(date)}`;
  if (language === "en") return dateFmt[format].format(date);
  const day = finnishDayFmt.format(date);
  const month = FINNISH_MONTHS[Number(finnishMonthNumberFmt.format(date)) - 1];
  const weekday = weekdayFmt.fi.format(date);
  return format === "dmy" ? `${weekday} ${day}. ${month}` : `${weekday}, ${month} ${day}`;
}

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
  return value == null ? "unknown" : dateText(toDate(value));
}

export function formatDateTime(value: string | null): string {
  if (value == null) return "unknown";
  const date = toDate(value);
  return `${dateText(date)}, ${timeFmt.format(date)}`;
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
export function formatPack(salesUnit: string, baseUnitsPerSalesUnit: number | null, baseUnit: string): string {
  if (baseUnitsPerSalesUnit == null) return `${salesUnit} (pack size unknown)`;
  return `${salesUnit} = ${formatNumber(baseUnitsPerSalesUnit)} ${baseUnit}`;
}
