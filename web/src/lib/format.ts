/**
 * Formatting helpers. Every time is shown in Helsinki time, the zone of
 * Valio's server and of the restaurant, whatever the browser's zone is.
 * React components evaluating these helpers must subscribe with useLanguage or useT
 * so localized output updates without remounting the page or reloading its data.
 */
import { getAppearance } from "@/lib/appearance";
import { getLanguage, translate } from "@/lib/i18n";

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

/**
 * The stored choice, or the language's own form when nothing was chosen ("space": Finnish
 * writes "1 000,50 €"). A choice the person made always wins.
 */
function numberFormat(): keyof typeof NUMBER_LOCALE {
  return getAppearance().numberFormat === "space" || (getAppearance().numberFormat !== "comma" && getLanguage() === "fi")
    ? "space"
    : "comma";
}

export function formatEur(value: number | null): string {
  return value == null ? "price unknown" : eur[numberFormat()].format(value);
}

export function formatNumber(value: number): string {
  return num[numberFormat()].format(value);
}

export const COUNTED_AMOUNT_UNITS = new Set(["PCS", "ST", "PC", "KPL", "CS", "BAG", "BOX", "PACK", "KI"]);

export function formatAmount(value: number, unit: string): string {
  const measured = !COUNTED_AMOUNT_UNITS.has(unit.toUpperCase());
  const step = measured ? 0.1 : 1;
  // The size is rounded, the sign is kept: -0.95 KG is -1 KG, and a small negative is not "< 0.1".
  const size = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (size !== 0 && size < step) return `${value < 0 ? "> -" : "< "}${formatNumber(step)} ${peopleUnit(unit, step)}`;
  const rounded = measured ? Math.round(size * 10) / 10 : Math.round(size);
  return `${sign}${formatNumber(rounded)} ${peopleUnit(unit, rounded)}`;
}

export function shortOrderId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}

/** Units a kitchen weighs or measures; every other unit (PCS, ST, KI, ...) is counted. */
export const MEASURED_UNITS = new Set(["KG", "G", "L", "DL", "CL", "ML"]);

/** Unit words in one place; an unrecognized catalog code stays as it is. */
const PEOPLE_UNITS: Record<string, { one: string; many: string }> = {
  KG: { one: "kg", many: "kg" },
  G: { one: "g", many: "g" },
  // #1982: litres read "L" everywhere, as the gateway and the catalog write them.
  L: { one: "L", many: "L" },
  DL: { one: "dl", many: "dl" },
  CL: { one: "cl", many: "cl" },
  ML: { one: "ml", many: "ml" },
  ST: { one: "piece", many: "pieces" },
  PCS: { one: "piece", many: "pieces" },
  KI: { one: "case", many: "cases" },
  BOT: { one: "bottle", many: "bottles" },
  PRK: { one: "pack", many: "packs" },
};

export function peopleUnit(unit: string, amount = 2): string {
  const words = PEOPLE_UNITS[unit.toUpperCase()];
  return words ? translate(getLanguage(), amount === 1 ? words.one : words.many) : unit;
}

/** A number and a raw unit code after it, as a gateway sentence writes them: "698 ST", "1.5 KG". */
const QUANTITY_WITH_CODE = new RegExp(`(\\d+(?:\\.\\d+)?) (${Object.keys(PEOPLE_UNITS).join("|")})\\b`, "g");

/**
 * #1982: a gateway sentence shown as it is ("698 ST of ... = 698 L"), with each raw unit code after a
 * number in the same words as the rest of the page ("698 pieces of ... = 698 L"). Nothing else changes.
 */
export function plainUnits(sentence: string): string {
  return sentence.replace(QUANTITY_WITH_CODE, (_match, amount: string, code: string) => `${amount} ${peopleUnit(code, Number(amount))}`);
}

/**
 * A shortfall rounded up, so it is never understated: a whole number for counted
 * units, at most one decimal for weights and volumes. "1,922 pcs", "41.5 kg".
 */
export function formatShortfall(amount: number, unit: string): string {
  const step = MEASURED_UNITS.has(unit.toUpperCase()) ? 10 : 1;
  // The small epsilon keeps float noise (41.4 * 10 = 413.99...) from rounding up a step.
  const rounded = Math.ceil(amount * step - 1e-9) / step;
  return `${formatNumber(rounded)} ${peopleUnit(unit, rounded)}`;
}

/**
 * An amount for people, rounded to the nearest step: one decimal for weights and volumes,
 * whole pieces for counted units. "12.226 KG" reads "12.2 kg". A text that is not a number stays.
 */
export function formatQuantity(amount: number | string, unit: string): string {
  const value = typeof amount === "number" ? amount : Number(amount);
  if (typeof amount === "string" && (!amount.trim() || !Number.isFinite(value))) return `${amount} ${peopleUnit(unit)}`;
  const step = MEASURED_UNITS.has(unit.toUpperCase()) ? 10 : 1;
  const rounded = Math.round(value * step) / step;
  return `${formatNumber(rounded)} ${peopleUnit(unit, rounded)}`;
}

/** Stock in sales units, or "unknown" for a sentinel / missing value. */
export function formatStock(amount: number | null | undefined, unit: string): string {
  if (isUnknownStock(amount)) return "unknown";
  return `${formatNumber(amount as number)} ${peopleUnit(unit, amount as number)}`;
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

function dateText(date: Date, chosen?: "dmy" | "numeric" | "mdy"): string {
  const language = getLanguage();
  const format = chosen ?? getAppearance().dateFormat;
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

/** "Sun 15 Nov": the day in words under a native date field, whatever format the browser picks. */
export function formatDayAndDate(value: string | null): string {
  return value == null ? "unknown" : dateText(toDate(value), "dmy");
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

/** One decimal in the viewer's number format: "4,9 %" in Finnish, "4.9 %" in English. */
export function formatPercentDecimal(fraction: number | null, signed = false, missing = "unknown"): string {
  if (fraction == null) return missing;
  const percent = num[numberFormat()].format(Math.round(fraction * 1000) / 10);
  return `${signed && fraction > 0 ? "+" : ""}${percent} %`;
}

/** A counted amount without decimals ("668 PCS"): a count of pieces is not 668.35 pieces. */
export function formatCount(value: number): string {
  return formatNumber(Math.round(value));
}

/** "1 case = 3 l": the total content (`baseUnitsPerSalesUnit`, L/KG or a piece count) of one sales unit. */
export function formatPack(salesUnit: string, baseUnitsPerSalesUnit: number | null, baseUnit: string): string {
  if (baseUnitsPerSalesUnit == null) return `${peopleUnit(salesUnit, 1)} (${translate(getLanguage(), "pack size unknown")})`;
  // No measure (no net content, not sold by weight): the count is pieces.
  return `1 ${peopleUnit(salesUnit, 1)} = ${formatNumber(baseUnitsPerSalesUnit)} ${peopleUnit(baseUnit || "ST", baseUnitsPerSalesUnit)}`;
}
