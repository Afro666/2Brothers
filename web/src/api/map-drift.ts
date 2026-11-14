import { ApiError } from "@/api/types";
import type { DriftKind, DriftReport, DriftWarning } from "@/types";

const KINDS: readonly DriftKind[] = ["portion_creep", "cost_creep"];

function number(value: unknown, field: string): number {
  const parsed = typeof value === "string" ? Number(value) : value;
  if (typeof parsed !== "number" || !Number.isFinite(parsed)) {
    throw new ApiError(
      "INVALID_RESPONSE",
      `drift warning has no valid "${field}".`,
    );
  }
  return parsed;
}

function warning(raw: Record<string, unknown>): DriftWarning {
  const kind = raw.kind as DriftKind;
  if (!KINDS.includes(kind))
    throw new ApiError(
      "INVALID_RESPONSE",
      `unknown drift kind "${String(raw.kind)}".`,
    );
  if (typeof raw.product_id !== "string" || typeof raw.why !== "string") {
    throw new ApiError(
      "INVALID_RESPONSE",
      "drift warning needs product_id and why.",
    );
  }
  return {
    productId: raw.product_id,
    productName: typeof raw.product_name === "string" ? raw.product_name : null,
    kind,
    change: number(raw.change, "change"),
    unit: typeof raw.unit === "string" ? raw.unit : "units",
    qtyPer100: number(raw.qty_per_100, "qty_per_100"),
    baselineQty: number(raw.baseline_qty, "baseline_qty"),
    spendPer100: number(raw.spend_per_100, "spend_per_100"),
    baselineSpend: number(raw.baseline_spend, "baseline_spend"),
    baselineWeeks: number(raw.baseline_weeks, "baseline_weeks"),
    why: raw.why,
    ...(typeof raw.kitchen_id === "string"
      ? {
          kitchenId: raw.kitchen_id,
          kitchenName:
            typeof raw.kitchen_name === "string" ? raw.kitchen_name : null,
        }
      : {}),
  };
}

/** `GET /drift` and `GET /demand/drift` bodies (docs/contract.md, "Standing-order drift"). */
export function mapDrift(body: unknown): DriftReport {
  const raw = body as { week?: unknown; warnings?: unknown } | null;
  if (typeof raw?.week !== "string" || !Array.isArray(raw.warnings)) {
    throw new ApiError(
      "INVALID_RESPONSE",
      "drift answer needs week and warnings.",
    );
  }
  return {
    week: raw.week,
    warnings: raw.warnings.map((entry) =>
      warning(entry as Record<string, unknown>),
    ),
  };
}
