import { describe, expect, it } from "vitest";

import { CODE_LABELS, codeLabel, plainReason } from "@/lib/codes";

describe("codeLabel", () => {
  it("gives the over-budget warning a plain title and says it does not block", () => {
    expect(codeLabel("OVER_BUDGET_WARNING")).toEqual({
      title: "Above the weekly budget",
      detail: "A warning, not a block: you can still approve.",
    });
  });

  it("has a plain sentence for every warning and reason code the engine and gateway send", () => {
    const codes = [
      "OVER_BUDGET_WARNING",
      "CERTAINTY_PREMIUM_HIGH",
      "PARTIAL_STOCK",
      "STOCK_UNKNOWN",
      "PACK_SIZE_DERIVED",
      "LOT_SIZE_ROUNDED",
      "SUBSTITUTE_FAT_LEVEL",
      "SUBSTITUTE_NEEDS_OK",
      "EVENT_LINE",
      "ALLERGEN_RULE",
      "ALLERGEN_DATA_MISSING",
      "CLOSING_PASSED",
      "STOCK_COUNT_MISSING",
      "STANDING_ORDER_DRIFT",
      "STOCKOUT_ADJUSTED",
      "MOV_PADDED",
      "COVER_CEILING",
      "POSITION_OK",
      "BLOCKED_BY_RECALL",
    ];
    for (const code of codes) {
      const label = CODE_LABELS[code];
      expect(label, code).toBeDefined();
      expect(label.title).not.toMatch(/[A-Z]{2,}_/);
      expect(label.detail.length).toBeGreaterThan(10);
    }
  });

  it("turns an unknown code into words, never the raw code", () => {
    expect(codeLabel("NEW_THING_WARNING")).toEqual({
      title: "New thing warning",
      detail: "The gateway flagged this. Check the order before you approve.",
    });
  });
});

describe("plainReason", () => {
  it("replaces a code inside a gateway reason with its plain title", () => {
    expect(plainReason("472710: ALLERGEN_RULE: the kitchen excludes AN, AP")).toBe(
      "472710: Excluded allergen: the kitchen excludes AN, AP",
    );
  });

  it("uses the product name when it is known", () => {
    expect(plainReason("472710: ALLERGEN_RULE: the kitchen excludes AN", new Map([["472710", "Peanut butter"]]))).toBe(
      "Peanut butter: Excluded allergen: the kitchen excludes AN",
    );
  });

  it("leaves a plain sentence alone", () => {
    expect(plainReason("15 KG of the request cannot be covered for this date.")).toBe(
      "15 KG of the request cannot be covered for this date.",
    );
  });
});
