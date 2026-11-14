import { type Json, decimal, object, rows } from "@/api/gateway-map";
import { blobToBase64 } from "@/api/http-shelf";
import type { Api, PriceListRead, PriceListReason, PriceListRow } from "@/api/types";
import { ApiError } from "@/api/types";

/** The gateway request of api/http.ts: a path under the base URL, the parsed JSON back. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

const REASONS: readonly PriceListReason[] = [
  "NAME_UNREADABLE",
  "PRICE_UNREADABLE",
  "PRICE_UNIT_MISSING",
  "UNIT_UNKNOWN",
  "CURRENCY_UNKNOWN",
  "PACK_UNCLEAR",
  "VAT_UNKNOWN",
];
/** The reasons whose price the contract leaves empty: the price cannot be trusted. */
const NO_PRICE: ReadonlySet<PriceListReason> = new Set([
  "NAME_UNREADABLE",
  "PRICE_UNREADABLE",
  "PRICE_UNIT_MISSING",
  "UNIT_UNKNOWN",
  "CURRENCY_UNKNOWN",
]);

function invalid(what: string): never {
  throw new ApiError("INVALID_RESPONSE", `The gateway sent ${what} in an unexpected shape.`);
}

const textOrNull = (value: unknown): string | null => (typeof value === "string" && value.trim() ? value : null);
const measureOf = (value: unknown): "KG" | "L" | null => (value === "KG" || value === "L" ? value : null);

/**
 * One price-list row. A PLEASE_CHECK row keeps its unclear fields empty, even when the
 * gateway sent something there: the person fills them, the web never does.
 */
export function mapPriceListRow(raw: Json): PriceListRow {
  const status = raw.status === "READ" || raw.status === "PLEASE_CHECK" ? raw.status : invalid("a price list row status");
  const reasons = Array.isArray(raw.reasons)
    ? REASONS.filter((reason) => (raw.reasons as unknown[]).includes(reason))
    : [];
  const check = status === "PLEASE_CHECK";
  const draft = object(raw.draft, "a price list draft");
  const noPrice = check && reasons.some((reason) => NO_PRICE.has(reason));
  const noPack = check && reasons.includes("PACK_UNCLEAR");
  const unitKnown = !(check && (reasons.includes("UNIT_UNKNOWN") || reasons.includes("PRICE_UNIT_MISSING")));
  const priceEur = noPrice ? null : decimal(draft.unit_price_eur, "unit_price_eur");
  if (priceEur != null && priceEur <= 0) invalid("a price list price");
  let match: PriceListRow["match"] = null;
  if (raw.match != null) {
    const found = object(raw.match, "a price list match");
    const productId = textOrNull(found.product_id) ?? invalid("a price list match id");
    match = {
      productId,
      name: textOrNull(found.name) ?? productId,
      priceEur: decimal(found.unit_price_eur, "match unit_price_eur"),
      kind: found.kind === "SAME" || found.kind === "PRICE_CHANGED" ? found.kind : null,
    };
  }
  return {
    printed: {
      name: textOrNull(raw.name),
      price: textOrNull(raw.price_text),
      priceUnit: textOrNull(raw.price_unit_text),
      pack: textOrNull(raw.pack_text),
    },
    status,
    reasons,
    draft: {
      name: check && reasons.includes("NAME_UNREADABLE") ? null : textOrNull(draft.name),
      unit: unitKnown ? textOrNull(draft.unit) : null,
      baseUnit: noPack ? null : measureOf(draft.base_unit),
      packSize: noPack ? null : decimal(draft.pack_size_in_base_units, "pack_size_in_base_units"),
      priceEur,
    },
    match,
  };
}

/** `POST /v1/kitchens/{k}/suppliers/{s}/price-list/photo` (docs/contract.md, #1174). */
export function mapPriceListPhoto(body: unknown): PriceListRead {
  const raw = object(body, "the price list answer");
  if (typeof raw.model !== "string" || !raw.model) invalid("the price list model");
  return {
    model: raw.model,
    durationMs: typeof raw.duration_ms === "number" ? raw.duration_ms : 0,
    supplierId: typeof raw.supplier_id === "string" ? raw.supplier_id : "",
    currency: raw.currency === "EUR" ? "EUR" : null,
    vat: raw.vat === "INCLUDED" || raw.vat === "EXCLUDED" ? raw.vat : null,
    truncated: raw.truncated === true,
    rows: rows(body, "rows").map(mapPriceListRow),
  };
}

/**
 * "Add from a photo of the price list" against the real gateway (#1174). Nemotron 3.5 Super
 * VL reads the photo into draft rows; the route writes nothing, so no idempotency key.
 */
export function createPriceListHttp(call: GatewayCall, kitchen: string): Pick<Api, "readPriceListPhoto"> {
  return {
    async readPriceListPhoto(supplierId, photo, actor) {
      return mapPriceListPhoto(
        await call(`${kitchen}/suppliers/${encodeURIComponent(supplierId)}/price-list/photo`, {
          method: "POST",
          headers: { "X-User": actor },
          body: JSON.stringify({ image_base64: await blobToBase64(photo) }),
        }),
      );
    },
  };
}
