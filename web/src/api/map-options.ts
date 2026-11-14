import { mapMoney } from "@/api/map";
import { ApiError } from "@/api/types";
import type { OfferTier, ProductLabel, ProposalOption, ProposalOptionLine } from "@/types";

const TIERS: readonly string[] = ["good", "better", "best"] satisfies OfferTier[];
const SOURCES: readonly string[] = ["confirmed", "original", "supplier", "catalog"];
const LABELS: readonly string[] = [
  "EU_ORGANIC_FARMING",
  "GOODS_FROM_FINLAND_BLUE_SWAN",
  "FINNISH_HEART_SYMBOL",
] satisfies ProductLabel[];

type Row = Record<string, unknown>;

function invalid(what: string): never {
  throw new ApiError("INVALID_RESPONSE", `substitute_options: ${what}.`);
}

function row(value: unknown, what: string): Row {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid(`${what} must be an object`);
  return value as Row;
}

function text(value: unknown, what: string): string {
  if (typeof value !== "string" || !value) invalid(`${what} must be a nonempty string`);
  return value as string;
}

/** A value every line must state; one line without it makes the whole option unknown. */
function everyLine<T>(lines: Row[], read: (line: Row) => T | null): T[] | null {
  const values = lines.map(read);
  return values.every((value) => value !== null) ? (values as T[]) : null;
}

/**
 * Contract `substitute_options` (docs/contract.md, "Chef substitute choices") to UI options.
 * Whatever the gateway does not send stays unknown (null, or false for stock), never zero.
 * `currentOfferId` is the proposal's own `offer_id`; `names` gives product names by id.
 *
 * Read from each line when present: `cutoff_passed` (offer line), `reason_codes`, `reliability`,
 * `carbon_kg_co2e_per_kg` and `labels` (#274, named as on the product row), and `unit_price`
 * (the gateway sends it per `unit`; the contract does not list it yet). Only an explicit `true`
 * from the gateway marks an option as recommended.
 */
export function mapProposalOptions(
  value: unknown,
  currentOfferId?: string,
  names?: ReadonlyMap<string, string>,
): ProposalOption[] {
  if (value == null) return [];
  if (!Array.isArray(value)) invalid("must be an array");
  return (value as unknown[]).map((item) => {
    const option = row(item, "an option");
    if (!TIERS.includes(option.tier as string)) invalid("tier must be good, better or best");
    if (option.source != null && !SOURCES.includes(option.source as string)) invalid("source is not known");
    if (option.currency !== "EUR") invalid("currency must be EUR");
    // Contract: a choice never selects, approves or places itself.
    if (option.requires_chef_approval !== true) invalid("requires_chef_approval must be true");
    if (!Array.isArray(option.lines) || option.lines.length === 0) invalid("lines must be a nonempty array");
    const rawLines = (option.lines as unknown[]).map((line) => row(line, "a line"));
    const lines: ProposalOptionLine[] = rawLines.map((line) => {
      const productId = text(line.product_id, "product_id");
      return {
        productId,
        productName: names?.get(productId) ?? null,
        quantity: mapMoney(line.quantity, "quantity"),
        unit: text(line.unit, "unit"),
        unitPrice: line.unit_price == null ? null : mapMoney(line.unit_price, "unit_price"),
      };
    });
    const reliability = everyLine(rawLines, (line) =>
      typeof line.reliability === "number" && line.reliability >= 0 && line.reliability <= 1 ? line.reliability : null,
    );
    const carbon = everyLine(rawLines, (line) =>
      typeof line.carbon_kg_co2e_per_kg === "number" && Number.isFinite(line.carbon_kg_co2e_per_kg)
        ? line.carbon_kg_co2e_per_kg
        : null,
    );
    const labels = everyLine(rawLines, (line) => (Array.isArray(line.labels) ? (line.labels as unknown[]) : null));
    const held = option.held == null ? null : row(option.held, "held");
    return {
      id: text(option.offer_id, "offer_id"),
      tier: option.tier as OfferTier,
      source: (option.source ?? null) as ProposalOption["source"],
      kind: rawLines.some((line) => Array.isArray(line.reason_codes) && line.reason_codes.includes("PARTIAL_STOCK"))
        ? "PARTIAL"
        : "FULL",
      lines,
      totalInclVat: mapMoney(option.expected_total, "expected_total"),
      stockConfirmed: option.stock_confirmed === true && rawLines.every((line) => line.unknown_stock === false),
      cutoffPassed: rawLines.some((line) => line.cutoff_passed === true)
        ? true
        : rawLines.every((line) => line.cutoff_passed === false)
          ? false
          : null,
      // The contract has no cut-off time on an offer line.
      cutoffAt: null,
      deliveryReliability: reliability && Math.min(...reliability),
      co2KgPerKg: carbon && { min: Math.min(...carbon), max: Math.max(...carbon) },
      labels:
        labels &&
        (LABELS.filter((label) => labels.every((lineLabels) => lineLabels.includes(label))) as ProductLabel[]),
      tradeOff: text(option.why, "why"),
      recommended: option.recommended === true,
      held: held && { quantity: mapMoney(held.quantity, "held.quantity"), unit: text(held.unit, "held.unit") },
      chosen: currentOfferId != null && option.offer_id === currentOfferId,
    };
  });
}
