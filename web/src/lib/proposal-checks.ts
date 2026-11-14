import type { LeftOutProduct, ProductCheck } from "@/components/purchasing/proposal-lines";
import { isPassed, isStockUnconfirmed } from "@/lib/format";
import type { Tone } from "@/lib/tone";
import type { ApprovalRequest, MandateReason, Order, OrderLine } from "@/types";

/** A product code as the gateway writes it in a reason ("463132: ..."). */
const PRODUCT_CODE = /^\d{4,}$/;
/** "Valio Eila milk 1 L (462775)": a name with its code (#1130). */
const NAMED_CODE = /\((\d{4,})\)$/;

export interface SplitChecks {
  /** Sentences about one product of the order, by product id: shown on that row. */
  perLine: Map<string, ProductCheck[]>;
  /** Products a reason names that are not on the order: the engine left them out. */
  leftOut: LeftOutProduct[];
  /** Reasons about the whole proposal. */
  general: MandateReason[];
}

function lineFor(prefix: string, lines: OrderLine[]): OrderLine | undefined {
  const code = NAMED_CODE.exec(prefix)?.[1];
  return lines.find(
    (line) => prefix === line.product.id || prefix === line.product.names.en || code === line.product.id,
  );
}

/**
 * Splits a proposal's "What to check" reasons into the product rows they are about, the
 * products the engine left out, and the proposal-wide rest. A gateway reason about one
 * product reads "<id or name>: <sentence>" (gateway/service.py, lib/codes.ts plainReason).
 */
export function splitChecks(reasons: MandateReason[], lines: OrderLine[]): SplitChecks {
  const perLine = new Map<string, ProductCheck[]>();
  const leftOut: LeftOutProduct[] = [];
  const general: MandateReason[] = [];
  for (const reason of reasons) {
    const match = /^([^:]+): (.+)$/s.exec(reason.rule);
    const prefix = match?.[1].trim();
    const rest = match?.[2].trim();
    const line = prefix && rest ? lineFor(prefix, lines) : undefined;
    if (line && rest) {
      const check: ProductCheck = { text: rest, detail: reason.detail };
      perLine.set(line.product.id, [...(perLine.get(line.product.id) ?? []), check]);
    } else if (prefix && rest && (PRODUCT_CODE.test(prefix) || NAMED_CODE.test(prefix))) {
      leftOut.push({ product: prefix, reason: rest, detail: reason.detail });
    } else {
      general.push(reason);
    }
  }
  return { perLine, leftOut, general };
}

/** A compact proposal's status chip: untranslated words and their values. */
export interface StatusChip {
  key: string;
  tone: Tone;
  text: string;
  values?: Record<string, string | number>;
}

/** Every chip text, for the Finnish dictionary check. */
export const CHIP_TEXTS = [
  "Held by a recall",
  "Not available {count}",
  "Cut-off passed {count}",
  "Allergen data missing",
  "Over budget",
  "Valio must confirm {count}",
  "{supplier} must confirm",
  "{count} products left out",
] as const;

const BUDGET = /budget/i;
const ALLERGEN_MISSING = "Allergen data missing";

/**
 * The few status chips a compact proposal shows, most serious first. Words come back
 * untranslated with their values: the card translates them.
 */
export function statusChips({
  request,
  order,
  now,
  heldByRecall,
  leftOut,
}: {
  request: ApprovalRequest;
  order?: Order;
  now: Date;
  heldByRecall: boolean;
  leftOut: number;
}): StatusChip[] {
  const lines = order?.lines ?? [];
  const chips: StatusChip[] = [];
  if (heldByRecall) chips.push({ key: "recall", tone: "danger", text: "Held by a recall" });
  const blocked = lines.filter((line) => line.offer.salesBlock).length;
  if (blocked) chips.push({ key: "blocked", tone: "danger", text: "Not available {count}", values: { count: blocked } });
  const closed = lines.filter((line) => isPassed(line.offer.closingTime, now)).length;
  if (closed) chips.push({ key: "cutoff", tone: "danger", text: "Cut-off passed {count}", values: { count: closed } });
  if (request.reasons.some((reason) => reason.rule === ALLERGEN_MISSING)) {
    chips.push({ key: "allergen", tone: "danger", text: "Allergen data missing" });
  }
  if (request.reasons.some((reason) => BUDGET.test(reason.rule))) {
    chips.push({ key: "budget", tone: "warning", text: "Over budget" });
  }
  const unconfirmed = lines.filter((line) => !line.offer.salesBlock && isStockUnconfirmed(line.offer)).length;
  if (unconfirmed) {
    chips.push({ key: "confirm", tone: "warning", text: "Valio must confirm {count}", values: { count: unconfirmed } });
  }
  for (const supplier of request.suppliersToConfirm) {
    chips.push({ key: `confirm-${supplier.supplierId}`, tone: "warning", text: "{supplier} must confirm", values: { supplier: supplier.name } });
  }
  if (leftOut) chips.push({ key: "left-out", tone: "neutral", text: "{count} products left out", values: { count: leftOut } });
  return chips;
}
