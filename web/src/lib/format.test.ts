import { afterEach, describe, expect, it } from "vitest";

import { getAppearance, loadAppearance, setAppearance } from "@/lib/appearance";

import { compareUrgency } from "@/components/purchasing/urgency-badge";

import { updateLanguage } from "@/lib/i18n";

import { formatAmount, formatDayAndDate, formatEur, formatNumber, formatPack, formatQuantity, formatShortfall, formatStock, isLater, isPassed, isUnknownStock } from "./format";

describe("stock sentinels", () => {
  it("treats both Valio sentinels and a missing value as unknown", () => {
    expect(isUnknownStock(999999)).toBe(true);
    expect(isUnknownStock(9999999999)).toBe(true);
    expect(isUnknownStock(null)).toBe(true);
    expect(isUnknownStock(51)).toBe(false);
    expect(isUnknownStock(0)).toBe(false);
  });

  it("never prints the sentinel", () => {
    expect(formatStock(999999, "KI")).toBe("unknown");
    expect(formatStock(9999999999, "ST")).toBe("unknown");
    expect(formatStock(51, "ST")).toBe("51 pieces");
  });
});

describe("closing time", () => {
  const now = new Date("2026-11-13T21:00:00+02:00");
  it("is passed at or before now, and a missing one is not passed", () => {
    expect(isPassed("2026-11-12T15:00:00+02:00", now)).toBe(true);
    expect(isPassed("2026-11-13T21:00:00+02:00", now)).toBe(true);
    expect(isPassed("2026-11-15T17:00:00+02:00", now)).toBe(false);
    expect(isPassed(null, now)).toBe(false);
  });

  it("knows when an offer arrives after the asked date", () => {
    expect(isLater("2026-11-18", "2026-11-16")).toBe(true);
    expect(isLater("2026-11-16", "2026-11-16")).toBe(false);
    expect(isLater(null, "2026-11-16")).toBe(false);
  });
});

describe("money", () => {
  it("formats euros and says when a price is missing", () => {
    expect(formatEur(1947.5)).toBe("€1,947.50");
    expect(formatEur(null)).toBe("price unknown");
  });
});

describe("demand and stock amounts", () => {
  it("rounds counted and measured units, keeps thousands and never loses a tiny amount", () => {
    expect(formatAmount(6024.083, "PCS")).toBe("6,024 PCS");
    expect(formatAmount(12.26, "KG")).toBe("12.3 KG");
    expect(formatAmount(1987.64, "L")).toBe("1,987.6 L");
    expect(formatAmount(0.4, "BOX")).toBe("< 1 BOX");
    expect(formatAmount(0.04, "ML")).toBe("< 0.1 ML");
    expect(formatAmount(2.26, "UNKNOWN")).toBe("2.3 UNKNOWN");
    expect(formatAmount(0, "PCS")).toBe("0 PCS");
  });
});

describe("urgency order", () => {
  it("sorts unknown with the urgent ones, before 'runs out'", () => {
    const sorted = (["CAN_WAIT", "DUE_NOW", "UNKNOWN", "RUNS_OUT_BEFORE_NEXT_DELIVERY", "GUESTS_AFFECTED_TODAY"] as const)
      .slice()
      .sort(compareUrgency);
    expect(sorted).toEqual(["GUESTS_AFFECTED_TODAY", "UNKNOWN", "RUNS_OUT_BEFORE_NEXT_DELIVERY", "DUE_NOW", "CAN_WAIT"]);
  });
});

describe("amounts for people", () => {
  it("rounds a weight to one decimal and writes the unit in small letters", () => {
    expect(formatQuantity(12.226, "KG")).toBe("12.2 kg");
    expect(formatQuantity(151.64, "L")).toBe("151.6 l");
    expect(formatQuantity(3, "KG")).toBe("3 kg");
  });

  it("gives whole pieces for counted units", () => {
    expect(formatQuantity(87.341, "PCS")).toBe("87 pieces");
    expect(formatQuantity("12.6", "BAG")).toBe("13 BAG");
  });

  it("uses plain unit words and the singular only for exactly one", () => {
    expect(formatQuantity(1, "ST")).toBe("1 piece");
    expect(formatQuantity(2, "ST")).toBe("2 pieces");
    expect(formatQuantity(1, "PCS")).toBe("1 piece");
    expect(formatQuantity(1, "KI")).toBe("1 case");
    expect(formatQuantity(2, "KI")).toBe("2 cases");
    expect(formatQuantity(1, "BOT")).toBe("1 bottle");
    expect(formatQuantity(2, "PRK")).toBe("2 packs");
    expect(formatQuantity(2, "NEW_UNIT")).toBe("2 NEW_UNIT");
  });

  it("writes pack contents as a sentence with the numbers unchanged", () => {
    expect(formatPack("KI", 12, "KG")).toBe("1 case = 12 kg");
    expect(formatPack("BOT", 0.75, "L")).toBe("1 bottle = 0.75 l");
    expect(formatPack("PRK", 1, "ST")).toBe("1 pack = 1 piece");
  });

  it("keeps a text that is not a number as it is", () => {
    expect(formatQuantity("about 10", "KG")).toBe("about 10 kg");
  });

  it("rounds a shortfall up, never down", () => {
    expect(formatShortfall(1921.159, "PCS")).toBe("1,922 pieces");
    expect(formatShortfall(0.1, "KI")).toBe("1 case");
    expect(formatShortfall(41.41, "KG")).toBe("41.5 kg");
    expect(formatShortfall(41.4, "KG")).toBe("41.4 kg");
  });
});

describe("number format follows the language until the person picks one", () => {
  afterEach(() => {
    updateLanguage("en", false);
    loadAppearance();
    localStorage.clear();
  });

  it("writes Finnish numbers and money when the language is Finnish and nothing was chosen", () => {
    loadAppearance();
    expect(getAppearance().numberFormat).toBeNull();
    updateLanguage("fi", false);
    expect(formatEur(2099.41)).toBe("2\u00a0099,41\u00a0€");
    expect(formatNumber(2099.41)).toBe("2\u00a0099,41");
    expect(formatStock(1200, "KI")).toBe("1\u00a0200 laatikkoa");
    expect(formatQuantity(1, "KI")).toBe("1 laatikko");
    expect(formatQuantity(2, "BOT")).toBe("2 pulloa");
    expect(formatPack("PRK", 2, "ST")).toBe("1 pakkaus = 2 kpl");
  });

  it("keeps a choice the person made", () => {
    updateLanguage("fi", false);
    setAppearance({ numberFormat: "comma" });
    expect(formatEur(2099.41)).toBe("€2,099.41");
    updateLanguage("en", false);
    setAppearance({ numberFormat: "space" });
    expect(formatEur(2099.41)).toBe("2\u00a0099,41\u00a0€");
  });

  it("leaves English as it was", () => {
    loadAppearance();
    expect(formatEur(2099.41)).toBe("€2,099.41");
    expect(formatNumber(2099.41)).toBe("2,099.41");
  });
});

describe("formatAmount at the edges", () => {
  it("carries a rounded weight into the next whole number and the thousands", () => {
    expect(formatAmount(0.95, "KG")).toBe("1 KG");
    expect(formatAmount(999.96, "KG")).toBe("1,000 KG");
  });

  it("keeps the sign of a negative amount", () => {
    expect(formatAmount(-0.95, "KG")).toBe("-1 KG");
    expect(formatAmount(-12.4, "PCS")).toBe("-12 PCS");
    expect(formatAmount(-0.04, "L")).toBe("> -0.1 L");
  });
});

describe("day and date", () => {
  afterEach(() => {
    updateLanguage("en", false);
    loadAppearance();
  });

  it("names the weekday in words, so the date is clear whatever the browser's date field shows", () => {
    expect(formatDayAndDate("2026-11-16")).toBe("Mon 16 Nov");
    expect(formatDayAndDate(null)).toBe("unknown");
  });

  it("is the same in Finnish", () => {
    loadAppearance();
    updateLanguage("fi", false);
    expect(formatDayAndDate("2026-11-16")).toBe("ma 16. marrask.");
  });
});
