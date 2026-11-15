import { readDeliveryFacts, type DeliveryFacts } from "@/api/delivery-facts";
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

/** A name field of a line (#1130): a nonempty string, else null (never invented). */
function nameOrNull(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
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

/** The line whose `value` is the extreme (smallest, or largest with `largest`), or undefined. */
function extreme(facts: DeliveryFacts[], value: (fact: DeliveryFacts) => number | null, largest = false) {
  return facts
    .filter((fact) => value(fact) != null)
    .reduce<DeliveryFacts | undefined>(
      (best, fact) =>
        best === undefined || (largest ? value(fact)! > value(best)! : value(fact)! < value(best)!) ? fact : best,
      undefined,
    );
}

/**
 * Contract `substitute_options` (docs/contract.md, "Chef substitute choices") to UI options.
 * Whatever the gateway does not send stays unknown (null, or false for stock), never zero.
 * `currentOfferId` is the proposal's own `offer_id`; `names` gives product names by id.
 *
 * Read from each line when present: `product_name`, `product_name_fi` and `brand` (#1130; the
 * line's own name wins over `names`), `cutoff_passed` (offer line), `reason_codes`, the delivery
 * facts `cutoff_at`, `lead_time_days` and `delivery_reliability` with their sources (#1453; the old
 * `reliability` only when a line has no `delivery_reliability`),
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
        productName: nameOrNull(line.product_name) ?? names?.get(productId) ?? null,
        productNameFi: nameOrNull(line.product_name_fi),
        brand: nameOrNull(line.brand),
        quantity: mapMoney(line.quantity, "quantity"),
        unit: text(line.unit, "unit"),
        unitPrice: line.unit_price == null ? null : mapMoney(line.unit_price, "unit_price"),
      };
    });
    // Cut-off, lead time and reliability to show (#1453). Reliability is the line's
    // `delivery_reliability`; a proposal stored before #1453 has only Valio's `reliability`.
    const facts = rawLines.map((line) => {
      const fact = readDeliveryFacts(line);
      if (fact.deliveryReliability != null) return fact;
      const old = line.reliability;
      return typeof old === "number" && old >= 0 && old <= 1
        ? { ...fact, deliveryReliability: old, reliabilitySource: "valio" as const }
        : fact;
    });
    const earliestCutoff = extreme(facts, (fact) => (fact.cutoffAt == null ? null : Date.parse(fact.cutoffAt)));
    const longestLead = extreme(facts, (fact) => fact.leadTimeDays, true);
    const weakest = extreme(facts, (fact) => fact.deliveryReliability);
    const carbon = everyLine(rawLines, (line) =>
      typeof line.carbon_kg_co2e_per_kg === "number" && Number.isFinite(line.carbon_kg_co2e_per_kg)
        ? line.carbon_kg_co2e_per_kg
        : null,
    );
    const labels = everyLine(rawLines, (line) => (Array.isArray(line.labels) ? (line.labels as unknown[]) : null));
    const held = option.held == null ? null : row(option.held, "held");
    // #1970: an option has no ex VAT total of its own; its lines have. Unknown when one line has none.
    const lineTotals = everyLine(rawLines, (line) => (line.total == null ? null : mapMoney(line.total, "line total")));
    return {
      id: text(option.offer_id, "offer_id"),
      tier: option.tier as OfferTier,
      source: (option.source ?? null) as ProposalOption["source"],
      kind: rawLines.some((line) => Array.isArray(line.reason_codes) && line.reason_codes.includes("PARTIAL_STOCK"))
        ? "PARTIAL"
        : "FULL",
      lines,
      totalInclVat: mapMoney(option.expected_total, "expected_total"),
      totalExVat: lineTotals && Math.round(lineTotals.reduce((sum, total) => sum + total, 0) * 100) / 100,
      stockConfirmed: option.stock_confirmed === true && rawLines.every((line) => line.unknown_stock === false),
      cutoffPassed: rawLines.some((line) => line.cutoff_passed === true)
        ? true
        : rawLines.every((line) => line.cutoff_passed === false)
          ? false
          : null,
      cutoffAt: earliestCutoff?.cutoffAt ?? null,
      cutoffSource: earliestCutoff?.cutoffSource ?? null,
      leadTimeDays: longestLead?.leadTimeDays ?? null,
      leadTimeSource: longestLead?.leadTimeSource ?? null,
      // The weakest line that states one (#1453): a line without a value does not hide the rest.
      deliveryReliability: weakest?.deliveryReliability ?? null,
      reliabilitySource: weakest?.reliabilitySource ?? null,
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
