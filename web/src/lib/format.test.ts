import { describe, expect, it } from "vitest";

import { compareUrgency } from "@/components/purchasing/urgency-badge";

import { formatEur, formatStock, isLater, isPassed, isUnknownStock } from "./format";

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
    expect(formatStock(51, "ST")).toBe("51 ST");
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

describe("urgency order", () => {
  it("sorts unknown with the urgent ones, before 'runs out'", () => {
    const sorted = (["CAN_WAIT", "DUE_NOW", "UNKNOWN", "RUNS_OUT_BEFORE_NEXT_DELIVERY", "GUESTS_AFFECTED_TODAY"] as const)
      .slice()
      .sort(compareUrgency);
    expect(sorted).toEqual(["GUESTS_AFFECTED_TODAY", "UNKNOWN", "RUNS_OUT_BEFORE_NEXT_DELIVERY", "DUE_NOW", "CAN_WAIT"]);
  });
});
