import { describe, expect, it } from "vitest";

import { CODE_LABELS, codeLabel, plainReason, translateReason } from "@/lib/codes";
import { translate } from "@/lib/i18n";

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

  it("explains a code that stands alone after the product id", () => {
    expect(plainReason("461332: BLOCKED_BY_RECALL")).toBe(
      "461332: Blocked by a recall. A product on this order matches a food recall. It cannot be approved.",
    );
  });

  it("leaves a plain sentence alone", () => {
    expect(plainReason("15 KG of the request cannot be covered for this date.")).toBe(
      "15 KG of the request cannot be covered for this date.",
    );
  });
});

describe("translateReason (#1169)", () => {
  const fi = (text: string) => translate("fi", text);

  it("has a Finnish entry for every code title", () => {
    for (const { title } of Object.values(CODE_LABELS)) expect(fi(title), title).not.toBe(title);
  });

  it("shows the Finnish title for a gateway reason in Finnish mode", () => {
    const names = new Map([["472710", "Kerma 1 L"]]);
    const shown = translateReason(plainReason("472710: ALLERGEN_RULE: the kitchen excludes AN", names), fi);
    expect(shown).toBe("Kerma 1 L: Poissuljettu allergeeni: the kitchen excludes AN");
  });

  it("translates the title and detail of a bare code reason", () => {
    const shown = translateReason(plainReason("461332: BLOCKED_BY_RECALL"), fi);
    expect(shown).toBe(`461332: ${fi("Blocked by a recall")}. ${fi(CODE_LABELS.BLOCKED_BY_RECALL.detail)}`);
    expect(shown).not.toContain("Blocked by a recall");
  });

  it("leaves English and unknown sentences as they are", () => {
    const reason = plainReason("472710: ALLERGEN_RULE: the kitchen excludes AN");
    expect(translateReason(reason, (text) => translate("en", text))).toBe(reason);
    expect(translateReason("Something else", fi)).toBe("Something else");
  });
});
