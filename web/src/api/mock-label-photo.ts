import type { LabelPhotoRead } from "@/api/types";

/** The mock's pause before it answers, so the "reading" state shows as it does live. */
export const LABEL_PHOTO_MOCK_DELAY_MS = 900;

/**
 * A sample of what the gateway answers for the prepared demo photo (docs/contract.md, "Check a
 * package's allergen label from a photo"): the "may contain" line names peanuts, which the demo
 * kitchen excludes.
 */
export function labelPhotoSample(orderId: string, productId: string): LabelPhotoRead {
  return {
    model: "nemotron-3.5-super-vl",
    durationMs: 3100,
    orderId,
    productId,
    inOrder: true,
    outcome: "EXCLUDED_ALLERGEN",
    message: "The label declares peanuts, which this kitchen excludes. Do not use it; ask a person.",
    productCheck: "CONFIRMED_BY_NAME",
    label: {
      productName: null,
      ean: null,
      contains: [{ word: "MAITO", code: "AM" }],
      mayContain: [{ word: "maapähkinää", code: "AP" }],
      unknownWords: [],
    },
    excludedHits: [{ code: "AP", level: "MAY_CONTAIN" }],
    differences: [{ code: "AP", kind: "LABEL_ADDS", text: "The label lists peanuts (may contain); the catalog does not." }],
    catalogAllergenData: "KNOWN",
    pleaseCheck: [],
  };
}

/** The mock reads no photo: every photo gets the sample after a short pause. It stores nothing. */
export async function readLabelPhotoMock(orderId: string, productId: string): Promise<LabelPhotoRead> {
  await new Promise((resolve) => setTimeout(resolve, LABEL_PHOTO_MOCK_DELAY_MS));
  return labelPhotoSample(orderId, productId);
}
