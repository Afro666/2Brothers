import type { ShelfPhotoRow } from "@/api/types";
import { ApiError } from "@/api/types";

/** The longest side of the photo that goes to the gateway, and its JPEG quality. */
export const MAX_SIDE = 1600;
const QUALITY = 0.85;
/** The gateway refuses a larger image with 413 IMAGE_TOO_LARGE (docs/contract.md). */
export const MAX_UPLOAD_BYTES = 4 * 1024 * 1024;

/** The size that fits inside `maxSide` with the same shape; a small photo is never enlarged. */
export function fitWithin(width: number, height: number, maxSide = MAX_SIDE): { width: number; height: number } {
  const scale = Math.min(1, maxSide / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

const unreadable = () =>
  new ApiError("NOT_AN_IMAGE", "This file is not a photo the browser can read. Choose a JPEG or PNG photo.");

async function decode(file: Blob): Promise<{ source: CanvasImageSource; width: number; height: number }> {
  if (typeof createImageBitmap === "function") {
    try {
      // "from-image": a phone photo taken upright stays upright.
      const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      return { source: bitmap, width: bitmap.width, height: bitmap.height };
    } catch {
      // Fall through: some browsers decode a format in <img> that createImageBitmap refuses.
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(unreadable());
      image.src = url;
    });
    return { source: image, width: image.naturalWidth, height: image.naturalHeight };
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * A phone photo is several megabytes: scale it down to 1600 px on the long side and encode
 * it as JPEG in the browser, before it goes to the gateway.
 */
export async function downscalePhoto(file: Blob): Promise<Blob> {
  if (file.type && !file.type.startsWith("image/")) throw unreadable();
  const { source, width, height } = await decode(file);
  if (!width || !height) throw unreadable();
  const size = fitWithin(width, height);
  const canvas = document.createElement("canvas");
  canvas.width = size.width;
  canvas.height = size.height;
  const context = canvas.getContext("2d");
  if (!context) throw unreadable();
  context.drawImage(source, 0, 0, size.width, size.height);
  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", QUALITY));
  if (!blob) throw unreadable();
  if (blob.size > MAX_UPLOAD_BYTES) {
    throw new ApiError("IMAGE_TOO_LARGE", "The photo is still larger than 4 MB after scaling. Take it from closer.");
  }
  return blob;
}

/**
 * The counts to put in the Stock page's drafts: one number per product on the stock list
 * with a COUNTED row. Two COUNTED rows for one product (two shelves) add up. A product
 * with any row that is not COUNTED gets no number: a partial count would be wrong.
 */
export function suggestedCounts(rows: ShelfPhotoRow[], onStockList: ReadonlySet<string>): Record<string, number> {
  const unsure = new Set(rows.filter((row) => row.kind !== "COUNTED" && row.productId).map((row) => row.productId));
  const counts: Record<string, number> = {};
  for (const row of rows) {
    if (row.kind !== "COUNTED" || row.count == null || !row.productId) continue;
    if (unsure.has(row.productId) || !onStockList.has(row.productId)) continue;
    counts[row.productId] = (counts[row.productId] ?? 0) + row.count;
  }
  return counts;
}
