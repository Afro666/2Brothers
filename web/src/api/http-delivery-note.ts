import { decimal, object, rows, type Json } from "@/api/gateway-map";
import { blobToBase64 } from "@/api/http-shelf";
import { ApiError, type Api, type DeliveryLot, type DeliveryNoteLine, type DeliveryNoteOther, type DeliveryNoteRead } from "@/api/types";

const invalid = (): never => { throw new ApiError("INVALID_RESPONSE", "The delivery note answer is invalid. Check the delivery by hand."); };
const text = (v: unknown): string => typeof v === "string" && v ? v : invalid();
const quantity = (v: unknown): number | null => {
  if (v == null || v === "unknown") return null;
  const n = decimal(v, "a delivery quantity");
  return n != null && n >= 0 ? n : invalid();
};
const lot = (r: Json): DeliveryLot => ({ lot: typeof r.lot === "string" && r.lot.trim() ? r.lot : "unknown", bestBefore: text(r.best_before), quantity: quantity(r.quantity), unit: text(r.unit) });

export function mapDeliveryNote(body: unknown, orderId: string): DeliveryNoteRead {
  const raw = object(body, "the delivery note");
  if (raw.order_id !== orderId || raw.saved !== false || typeof raw.complete !== "boolean") invalid();
  const lines = rows(body, "lines").map((r): DeliveryNoteLine => {
    const status = r.status;
    if (status !== "RECEIVED" && status !== "SHORT" && status !== "MISSING" && status !== "UNKNOWN") return invalid();
    return { productId: text(r.product_id), status, ordered: quantity(r.ordered),
      received: status === "UNKNOWN" ? null : quantity(r.received),
      missing: status === "UNKNOWN" ? null : quantity(r.missing), baseUnit: text(r.base_unit), lots: rows(r, "lots").map(lot) };
  });
  const notOrdered = rows(body, "not_ordered").map((r): DeliveryNoteOther => {
    const status = r.status;
    if (status !== "SUBSTITUTE" && status !== "EXTRA" && status !== "UNREADABLE") return invalid();
    const replaces = typeof r.replaces === "string" && r.replaces ? r.replaces : status === "SUBSTITUTE" ? invalid() : "none";
    return { ...lot(r), productId: text(r.product_id), status, replaces,
      received: status === "UNREADABLE" ? null : quantity(r.received), baseUnit: text(r.base_unit), needsApproval: status === "SUBSTITUTE" };
  });
  const note = object(raw.note, "the note reference");
  return { orderId, model: text(raw.model), durationMs: typeof raw.duration_ms === "number" ? raw.duration_ms : 0,
    orderRef: text(note.order_ref), deliveryDate: text(note.delivery_date),
    complete: raw.complete === true && lines.length > 0 && lines.every((r) => r.status === "RECEIVED") && !notOrdered.length,
    lines, notOrdered };
}

export function createDeliveryNoteHttp(call: (path: string, init?: RequestInit) => Promise<unknown>, kitchen: string): Pick<Api, "readDeliveryNote"> {
  return { async readDeliveryNote(orderId, photo, actor) {
    return mapDeliveryNote(await call(`${kitchen}/orders/${encodeURIComponent(orderId)}/delivery-note/photo`, {
      method: "POST", headers: { "X-User": actor }, body: JSON.stringify({ image_base64: await blobToBase64(photo) }),
    }), orderId);
  } };
}
