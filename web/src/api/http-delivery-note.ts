import { decimal, object, rows, type Json } from "@/api/gateway-map";
import { blobToBase64 } from "@/api/http-shelf";
import { ApiError, type Api, type DeliveryClaim, type DeliveryLot, type DeliveryNoteLine, type DeliveryNoteOther, type DeliveryNoteRead } from "@/api/types";

const invalid = (): never => { throw new ApiError("INVALID_RESPONSE", "The delivery note answer is invalid"); };
const text = (v: unknown): string => typeof v === "string" && v ? v : invalid();
const quantity = (v: unknown): number | null => {
  if (v == null || v === "unknown") return null;
  const n = decimal(v, "a delivery quantity");
  return n != null && n >= 0 ? n : invalid();
};
const lot = (r: Json): DeliveryLot => ({ lot: typeof r.lot === "string" && r.lot.trim() ? r.lot : "unknown", bestBefore: text(r.best_before), quantity: quantity(r.quantity), unit: text(r.unit) });

export function mapDeliveryNote(body: unknown, orderId: string): DeliveryNoteRead {
  const raw = object(body, "the delivery note");
  if (raw.order_id !== orderId || typeof raw.saved !== "boolean" || typeof raw.complete !== "boolean") invalid();
  const lines = rows(body, "lines").map((r): DeliveryNoteLine => {
    const status = r.status;
    if (status !== "RECEIVED" && status !== "SHORT" && status !== "MISSING" && status !== "UNKNOWN") return invalid();
    return { productId: text(r.product_id), status, ordered: quantity(r.ordered),
      received: status === "UNKNOWN" ? null : quantity(r.received),
      missing: status === "UNKNOWN" ? null : quantity(r.missing), baseUnit: text(r.base_unit), lots: rows(r, "lots").map(lot),
      orderQuantity: quantity(r.order_quantity), orderUnit: typeof r.order_unit === "string" && r.order_unit ? r.order_unit : null,
      missingOrderQty: status === "UNKNOWN" ? null : quantity(r.missing_order_qty), unitPrice: quantity(r.unit_price),
      // Unknown is never a value: an UNKNOWN line has no claim, whatever the answer says.
      claimEur: status === "UNKNOWN" ? null : quantity(r.claim_eur) };
  });
  const notOrdered = rows(body, "not_ordered").map((r): DeliveryNoteOther => {
    const status = r.status;
    if (status !== "SUBSTITUTE" && status !== "EXTRA" && status !== "UNREADABLE") return invalid();
    const replaces = typeof r.replaces === "string" && r.replaces ? r.replaces : status === "SUBSTITUTE" ? invalid() : "none";
    return { ...lot(r), productId: text(r.product_id), status, replaces,
      received: status === "UNREADABLE" ? null : quantity(r.received), baseUnit: text(r.base_unit), needsApproval: status === "SUBSTITUTE" };
  });
  const note = object(raw.note, "the note reference");
  return { orderId, model: text(raw.model), durationMs: typeof raw.duration_ms === "number" ? raw.duration_ms : null,
    orderRef: text(note.order_ref), deliveryDate: text(note.delivery_date),
    complete: raw.complete === true && lines.length > 0 && lines.every((r) => r.status === "RECEIVED") && !notOrdered.length,
    lines, notOrdered, claim: claimOf(raw.claim) };
}

const count = (v: unknown): number => typeof v === "number" && Number.isInteger(v) && v >= 0 ? v : invalid();

function claimOf(value: unknown): DeliveryClaim | null {
  if (value == null) return null;
  const c = object(value, "the claim");
  const total = quantity(c.total_eur);
  if (total == null) return invalid();
  const unit = typeof c.unit === "string" && c.unit ? c.unit : null;
  const qty = unit ? quantity(c.quantity) : null;
  return { totalEur: total, lines: count(c.lines), quantity: qty, unit: qty == null ? null : unit,
    notValued: count(c.not_valued), supplierName: typeof c.supplier_name === "string" && c.supplier_name ? c.supplier_name : null };
}

export function createDeliveryNoteHttp(call: (path: string, init?: RequestInit) => Promise<unknown>, kitchen: string): Pick<Api, "readDeliveryNote"> {
  return { async readDeliveryNote(orderId, photo, actor) {
    return mapDeliveryNote(await call(`${kitchen}/orders/${encodeURIComponent(orderId)}/delivery-note/photo`, {
      method: "POST", headers: { "X-User": actor }, body: JSON.stringify({ image_base64: await blobToBase64(photo) }),
    }), orderId);
  } };
}
