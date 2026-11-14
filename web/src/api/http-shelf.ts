import { decimal, type Json, object, rows } from "@/api/gateway-map";
import type { Api, ShelfPhotoRead, ShelfPhotoRow } from "@/api/types";
import { ApiError } from "@/api/types";

/** The gateway request of api/http.ts: a path under the base URL, the parsed JSON back. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

const KINDS: readonly ShelfPhotoRow["kind"][] = ["COUNTED", "PLEASE_COUNT", "UNMATCHED"];
const CONFIDENCE: readonly ShelfPhotoRow["confidence"][] = ["high", "medium", "low"];

function invalid(what: string): never {
  throw new ApiError("INVALID_RESPONSE", `The gateway sent ${what} in an unexpected shape.`);
}

const textOrNull = (value: unknown): string | null => (typeof value === "string" && value ? value : null);

/**
 * One row of the answer. Unknown is never a number: only a COUNTED row keeps `packs` and
 * `count`, whatever the gateway sent, and a COUNTED row without a usable count is refused.
 */
function mapRow(raw: Json): ShelfPhotoRow {
  const kind = KINDS.find((known) => known === raw.row) ?? invalid("a shelf row kind");
  const confidence = CONFIDENCE.find((known) => known === raw.confidence) ?? invalid("a shelf row confidence");
  const counted = kind === "COUNTED";
  const matched = kind !== "UNMATCHED";
  const count = counted ? decimal(raw.count, "a shelf count") : null;
  const productId = matched ? textOrNull(raw.product_id) : null;
  const unit = matched ? textOrNull(raw.unit) : null;
  if (counted && (count == null || count < 0 || !productId || !unit || !Number.isInteger(raw.packs))) {
    invalid("a counted shelf row");
  }
  return {
    kind,
    productId,
    productName: matched ? textOrNull(raw.product_name) : null,
    label: typeof raw.label === "string" ? raw.label : "",
    confidence,
    packs: counted ? (raw.packs as number) : null,
    packSize: matched ? decimal(raw.pack_size, "a pack size") : null,
    count,
    unit,
  };
}

/** `POST /v1/kitchens/{k}/stock/photo` (docs/contract.md, "Count from a shelf photo"). */
export function mapShelfPhoto(body: unknown): ShelfPhotoRead {
  const raw = object(body, "the shelf photo answer");
  if (typeof raw.model !== "string" || !raw.model) invalid("the shelf photo model");
  return {
    model: raw.model,
    durationMs: typeof raw.duration_ms === "number" ? raw.duration_ms : 0,
    rows: rows(body, "rows").map(mapRow),
  };
}

/** The photo's bytes as base64, in pieces: one `String.fromCharCode` call cannot take megabytes. */
export async function blobToBase64(blob: Blob): Promise<string> {
  const buffer = await new Promise<ArrayBuffer>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(new ApiError("NOT_AN_IMAGE", "The photo could not be read from this device."));
    reader.readAsArrayBuffer(blob);
  });
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let start = 0; start < bytes.length; start += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(start, start + 0x8000));
  }
  return btoa(binary);
}

/**
 * "Count from a photo" against the real gateway (gateway/stock_photo.py). The gateway hands
 * the photo to Nemotron 3.5 Super VL and answers rows to confirm. The route stores no count.
 */
export function createShelfHttp(call: GatewayCall, kitchen: string): Pick<Api, "readShelfPhoto"> {
  return {
    async readShelfPhoto(photo, actor) {
      return mapShelfPhoto(
        await call(`${kitchen}/stock/photo`, {
          method: "POST",
          headers: { "X-User": actor },
          body: JSON.stringify({ image_base64: await blobToBase64(photo) }),
        }),
      );
    },
  };
}
