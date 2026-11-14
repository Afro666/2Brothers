import type { DeliverySource } from "@/types";

/**
 * Cut-off, lead time and delivery reliability of one line, for display only
 * (docs/contract.md "Cut-off, lead time and delivery reliability to show", #1453).
 * A proposal stored before #1453 has none of these fields: a missing or unreadable
 * value is null, never zero and never "on time".
 */
export interface DeliveryFacts {
  cutoffAt: string | null;
  cutoffSource: DeliverySource | null;
  leadTimeDays: number | null;
  leadTimeSource: DeliverySource | null;
  deliveryReliability: number | null;
  reliabilitySource: DeliverySource | null;
}

const CUTOFF_SOURCES: readonly DeliverySource[] = ["valio", "supplier_terms", "demo"];
const LEAD_TIME_SOURCES: readonly DeliverySource[] = ["supplier_terms", "demo"];
const RELIABILITY_SOURCES: readonly DeliverySource[] = ["valio", "demo"];

function source(value: unknown, allowed: readonly DeliverySource[]): DeliverySource | null {
  return allowed.includes(value as DeliverySource) ? (value as DeliverySource) : null;
}

function fraction(value: unknown): number | null {
  const number = typeof value === "string" && value.trim() ? Number(value) : value;
  return typeof number === "number" && Number.isFinite(number) && number >= 0 && number <= 1 ? number : null;
}

export function readDeliveryFacts(line: Record<string, unknown>): DeliveryFacts {
  const cutoffAt =
    typeof line.cutoff_at === "string" && Number.isFinite(Date.parse(line.cutoff_at)) ? line.cutoff_at : null;
  const lead = line.lead_time_days;
  const leadTimeDays = typeof lead === "number" && Number.isInteger(lead) && lead >= 0 ? lead : null;
  const deliveryReliability = fraction(line.delivery_reliability);
  return {
    cutoffAt,
    cutoffSource: cutoffAt == null ? null : source(line.cutoff_source, CUTOFF_SOURCES),
    leadTimeDays,
    leadTimeSource: leadTimeDays == null ? null : source(line.lead_time_source, LEAD_TIME_SOURCES),
    deliveryReliability,
    reliabilitySource: deliveryReliability == null ? null : source(line.reliability_source, RELIABILITY_SOURCES),
  };
}
