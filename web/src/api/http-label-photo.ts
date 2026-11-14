import { type Json, object, rows } from "@/api/gateway-map";
import { blobToBase64 } from "@/api/http-shelf";
import {
  ApiError,
  type Api,
  type LabelPhotoOutcome,
  type LabelPhotoRead,
  type LabelPleaseCheck,
  type LabelProductCheck,
  type LabelWord,
} from "@/api/types";

/** The gateway request of api/http.ts: a path under the base URL, the parsed JSON back. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

const OUTCOMES: readonly LabelPhotoOutcome[] = ["EXCLUDED_ALLERGEN", "PLEASE_CHECK", "DIFFERS", "CATALOG_UNKNOWN", "AGREES"];
const CHECKS: readonly LabelProductCheck[] = ["CONFIRMED_BY_EAN", "CONFIRMED_BY_NAME", "MISMATCH", "NOT_CONFIRMED"];
const REASONS: readonly LabelPleaseCheck[] = ["NO_STATEMENT_READ", "WORD_UNKNOWN", "PRODUCT_MISMATCH", "PRODUCT_NOT_CONFIRMED"];

const invalid = (): never => {
  throw new ApiError("INVALID_RESPONSE", "The label answer is invalid. Read the label yourself.");
};
const text = (v: unknown): string => (typeof v === "string" && v ? v : invalid());
const textOrNull = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const one = <T extends string>(list: readonly T[], v: unknown): T => list.find((known) => known === v) ?? invalid();
const words = (r: Json): LabelWord => ({ word: text(r.word), code: text(r.code) });

/** `POST /v1/kitchens/{k}/orders/{o}/label/photo` (docs/contract.md, "Check a package's allergen label from a photo"). */
export function mapLabelPhoto(body: unknown, orderId: string, productId: string): LabelPhotoRead {
  const raw = object(body, "the label answer");
  if (raw.order_id !== orderId || raw.product_id !== productId) invalid();
  const label = object(raw.label, "the label");
  const unknown: unknown[] = Array.isArray(label.unknown_words) ? label.unknown_words : invalid();
  if (!Array.isArray(raw.please_check)) invalid();
  const pleaseCheck = (raw.please_check as unknown[]).map((v) => one(REASONS, v));
  const productCheck = one(CHECKS, raw.product_check);
  const unknownWords = unknown.filter((w): w is string => typeof w === "string" && w !== "");
  // docs/contract.md: these cases are always "please check"; do not trust the gateway to say so.
  const must: LabelPleaseCheck[] = [];
  if (productCheck === "MISMATCH") must.push("PRODUCT_MISMATCH");
  if (productCheck === "NOT_CONFIRMED") must.push("PRODUCT_NOT_CONFIRMED");
  if (unknownWords.length) must.push("WORD_UNKNOWN");
  for (const reason of must) if (!pleaseCheck.includes(reason)) pleaseCheck.push(reason);
  let outcome = one(OUTCOMES, raw.outcome);
  // A reason to check never reads as agreement, whatever the outcome field says.
  if (pleaseCheck.length && (outcome === "AGREES" || outcome === "DIFFERS" || outcome === "CATALOG_UNKNOWN")) outcome = "PLEASE_CHECK";
  const catalog = raw.catalog_allergen_data === "KNOWN" ? "KNOWN" : raw.catalog_allergen_data === "UNKNOWN" ? "UNKNOWN" : invalid();
  const excludedHits = rows(body, "excluded_hits").map((r): LabelPhotoRead["excludedHits"][number] => ({
    code: text(r.code),
    level: r.level === "CONTAINS" || r.level === "MAY_CONTAIN" ? r.level : invalid(),
  }));
  if (excludedHits.length) outcome = "EXCLUDED_ALLERGEN";
  return {
    model: text(raw.model),
    durationMs: typeof raw.duration_ms === "number" && raw.duration_ms >= 0 ? raw.duration_ms : null,
    orderId,
    productId,
    inOrder: raw.in_order !== false,
    outcome,
    message: typeof raw.message === "string" ? raw.message : "",
    productCheck,
    label: {
      productName: textOrNull(label.product_name),
      ean: textOrNull(label.ean),
      contains: rows(label, "contains").map(words),
      mayContain: rows(label, "may_contain").map(words),
      unknownWords,
    },
    excludedHits,
    differences: rows(body, "differences").map((r): LabelPhotoRead["differences"][number] => ({
      code: text(r.code),
      kind: r.kind === "LABEL_ADDS" || r.kind === "CATALOG_ADDS" ? r.kind : invalid(),
      text: text(r.text),
    })),
    catalogAllergenData: catalog,
    pleaseCheck,
  };
}

export function createLabelPhotoHttp(call: GatewayCall, kitchen: string): Pick<Api, "readLabelPhoto"> {
  return {
    async readLabelPhoto(orderId, productId, photo, actor) {
      return mapLabelPhoto(
        await call(`${kitchen}/orders/${encodeURIComponent(orderId)}/label/photo`, {
          method: "POST",
          headers: { "X-User": actor },
          body: JSON.stringify({ image_base64: await blobToBase64(photo), product_id: productId }),
        }),
        orderId,
        productId,
      );
    },
  };
}
