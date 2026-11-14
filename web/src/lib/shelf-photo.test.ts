import { describe, expect, it } from "vitest";

import { SHELF_FIXTURE } from "@/api/mock-shelf";
import type { ShelfPhotoRow } from "@/api/types";
import { downscalePhoto, fitWithin, suggestedCounts } from "@/lib/shelf-photo";

const row = (change: Partial<ShelfPhotoRow>): ShelfPhotoRow => ({ ...SHELF_FIXTURE.rows[0], ...change });

describe("shelf photo", () => {
  it("scales a phone photo to 1600 px on the long side and never enlarges", () => {
    expect(fitWithin(4032, 3024)).toEqual({ width: 1600, height: 1200 });
    expect(fitWithin(3024, 4032)).toEqual({ width: 1200, height: 1600 });
    expect(fitWithin(1600, 1100)).toEqual({ width: 1600, height: 1100 });
    expect(fitWithin(800, 600)).toEqual({ width: 800, height: 600 });
    expect(fitWithin(10000, 3)).toEqual({ width: 1600, height: 1 });
  });

  it("refuses a file that is not an image before it is sent", async () => {
    await expect(downscalePhoto(new File(["%PDF-1.7"], "note.pdf", { type: "application/pdf" }))).rejects.toMatchObject({
      code: "NOT_AN_IMAGE",
    });
  });

  it("suggests the fixture's four counted products", () => {
    const all = new Set(["462775", "463335", "462921", "463038", "464179"]);
    expect(suggestedCounts(SHELF_FIXTURE.rows, all)).toEqual({ "462775": 7, "463335": 6, "462921": 4, "463038": 20 });
  });

  it("adds two counted rows up, and gives no number when any row is unsure", () => {
    const list = new Set(["462775", "463335"]);
    expect(suggestedCounts([row({ count: 7 }), row({ count: 3 })], list)).toEqual({ "462775": 10 });
    const unsure = row({ kind: "PLEASE_COUNT", packs: null, count: null });
    expect(suggestedCounts([row({ count: 7 }), unsure], list)).toEqual({});
    // A number on a row that is not COUNTED is never used.
    expect(suggestedCounts([row({ kind: "PLEASE_COUNT", count: 7 })], list)).toEqual({});
    expect(suggestedCounts([row({ kind: "UNMATCHED", productId: null, count: 7 })], list)).toEqual({});
  });

  it("fills nothing for a product that is not on the stock list", () => {
    expect(suggestedCounts(SHELF_FIXTURE.rows, new Set(["463335"]))).toEqual({ "463335": 6 });
  });
});
