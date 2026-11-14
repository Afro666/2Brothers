import type { ShelfPhotoRead } from "@/api/types";

/**
 * What the gateway answers for the synthetic test photo agent/fixtures/shelf/shelf.png:
 * Nemotron's recorded real reply (agent/fixtures/shelf/shelf.reply.json, 2026-11-14) matched
 * to the fixture kitchen. Four products counted; the half hidden box has no number.
 */
export const SHELF_FIXTURE: ShelfPhotoRead = {
  model: "nemotron-3.5-super-vl",
  durationMs: 2200,
  rows: [
    {
      kind: "COUNTED",
      productId: "462775",
      productName: "Arla 1 L lactose free fat free UHT",
      label: "Arla lactose free 1L",
      confidence: "high",
      packs: 7,
      packSize: 1,
      count: 7,
      unit: "L",
    },
    {
      kind: "COUNTED",
      productId: "463335",
      productName: "Valio Eila 3% 1 L",
      label: "Valio Eila 3% 1L",
      confidence: "high",
      packs: 6,
      packSize: 1,
      count: 6,
      unit: "L",
    },
    {
      kind: "COUNTED",
      productId: "462921",
      productName: "Valio Eila organic 1 L",
      label: "Valio Eila organic 1L",
      confidence: "high",
      packs: 4,
      packSize: 1,
      count: 4,
      unit: "L",
    },
    {
      kind: "COUNTED",
      productId: "463038",
      productName: "Valio Eila 10 L novobox",
      label: "Valio Eila 10 L novobox",
      confidence: "high",
      packs: 2,
      packSize: 10,
      count: 20,
      unit: "L",
    },
    {
      kind: "UNMATCHED",
      productId: null,
      productName: null,
      label: "Arla L m",
      confidence: "low",
      packs: null,
      packSize: null,
      count: null,
      unit: null,
    },
  ],
};

/** The mock reads no photo: every photo gets the recorded rows of the fixture. It saves nothing. */
export async function readShelfPhotoMock(): Promise<ShelfPhotoRead> {
  return structuredClone(SHELF_FIXTURE);
}
