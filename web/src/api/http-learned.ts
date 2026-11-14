import { object, rows, text } from "@/api/gateway-map";
import { ApiError, type Api } from "@/api/types";
import type { LearnedEvidence, LearnedFact, LearnedFactKind } from "@/types";

type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

function invalid(what: string): never {
  throw new ApiError("INVALID_RESPONSE", `The gateway sent ${what} in an unexpected shape.`);
}

function number(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) invalid(what);
  return value;
}

function optionalNumber(row: Record<string, unknown>, key: string, nullable = false): number | null | undefined {
  if (!Object.hasOwn(row, key) || row[key] === undefined) return undefined;
  if (nullable && row[key] === null) return null;
  return number(row[key], key);
}

function optionalBoolean(row: Record<string, unknown>, key: string): boolean | undefined {
  if (!Object.hasOwn(row, key) || row[key] === undefined) return undefined;
  if (typeof row[key] !== "boolean") invalid(key);
  return row[key];
}

function nullableText(value: unknown, what: string): string | null {
  return value == null ? null : text(value, what);
}

function mapEvidence(value: unknown): LearnedEvidence {
  const evidence = object(value, "learned evidence");
  const count = number(evidence.rows, "learned evidence rows");
  if (!Number.isInteger(count) || count < 0) invalid("learned evidence rows");
  return {
    rows: count,
    from: text(evidence.from, "learned evidence from"),
    to: text(evidence.to, "learned evidence to"),
    last: text(evidence.last, "learned evidence last"),
  };
}

const KINDS = new Set<LearnedFactKind>(["CORRECTION_RATIO", "DECLINED_PRODUCT", "SUPPLIER_LATE", "SUPPLIER_SHORT"]);

export function mapLearnedFact(value: unknown): LearnedFact {
  const row = object(value, "a learned fact");
  if (typeof row.kind !== "string" || !KINDS.has(row.kind as LearnedFactKind)) invalid("a learned fact kind");
  if (typeof row.active !== "boolean") invalid("a learned fact active flag");
  return {
    id: text(row.id, "a learned fact id"),
    kind: row.kind as LearnedFactKind,
    productId: nullableText(row.product_id, "a learned fact product_id"),
    supplierId: nullableText(row.supplier_id, "a learned fact supplier_id"),
    name: text(row.name, "a learned fact name"),
    value: number(row.value, "a learned fact value"),
    evidence: mapEvidence(row.evidence),
    since: text(row.since, "a learned fact since"),
    active: row.active,
    rawValue: optionalNumber(row, "raw_value") as number | undefined,
    applicable: optionalBoolean(row, "applicable"),
    meanDaysLate: optionalNumber(row, "mean_days_late") as number | undefined,
    onTimeRate: optionalNumber(row, "on_time_rate") as number | undefined,
    deliveries: optionalNumber(row, "deliveries") as number | undefined,
    meanLeadTime: optionalNumber(row, "mean_lead_time", true),
    sigmaLeadTime: optionalNumber(row, "sigma_lead_time", true),
  };
}

export function createLearnedHttp(
  call: GatewayCall,
  kitchen: string,
): Pick<Api, "listLearnedFacts" | "setLearnedFactActive"> {
  return {
    async listLearnedFacts() {
      return rows(await call(`${kitchen}/learned`), "facts").map(mapLearnedFact);
    },
    async setLearnedFactActive(id, active, actor) {
      const body = object(
        await call(`${kitchen}/learned/${encodeURIComponent(id)}`, {
          method: "PUT",
          headers: { "X-User": actor },
          body: JSON.stringify({ active }),
        }),
        "the updated learned fact",
      );
      return mapLearnedFact(object(body.fact, "the updated learned fact"));
    },
  };
}
