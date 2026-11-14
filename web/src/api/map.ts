import { ApiError } from "@/api/types";

/**
 * The contract sends money as a decimal string ("149.02"). The UI types use
 * numbers, so this is the one place a decimal string becomes a number.
 */
export function mapMoney(value: unknown, label = "amount"): number {
  if (typeof value !== "string" || !/^-?\d+(\.\d+)?$/.test(value)) {
    throw new ApiError("INVALID_RESPONSE", `${label} must be a decimal string.`);
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new ApiError("INVALID_RESPONSE", `${label} is not a finite number.`);
  return parsed;
}

/**
 * Audit text names products by id ("51 ST of 462775"). People read names, so
 * each known id becomes its name; an id with no known name stays as it is.
 */
export function nameProducts(text: string, names: ReadonlyMap<string, string>): string {
  return text.replace(/\b\d{6,}\b/g, (id) => names.get(id) ?? id);
}
