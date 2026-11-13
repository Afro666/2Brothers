import { describe, expect, it } from "vitest";

import { isValidWeek, isoWeekOf, weekDates, weekLabel, weekRangeLabel } from "@/lib/week";

describe("ISO week helpers", () => {
  it("finds the ISO week for a date", () => {
    expect(isoWeekOf("2026-11-16")).toBe("2026-W47");
  });

  it("handles a year boundary", () => {
    expect(isoWeekOf("2027-01-01")).toBe("2026-W53");
    expect(weekDates("2026-W01")).toEqual([
      "2025-12-29",
      "2025-12-30",
      "2025-12-31",
      "2026-01-01",
      "2026-01-02",
      "2026-01-03",
      "2026-01-04",
    ]);
  });

  it("names the day range of a normal week", () => {
    expect(weekRangeLabel("2026-W47")).toBe("16 to 22 Nov 2026");
  });

  it("names both years when a week crosses New Year", () => {
    expect(weekDates("2026-W53").at(-1)).toBe("2027-01-03");
    expect(weekRangeLabel("2026-W53")).toBe("28 Dec 2026 to 3 Jan 2027");
  });

  it("labels a normal week and a week that crosses New Year", () => {
    expect(weekLabel("2026-W47")).toBe("Week 47, 16 to 22 Nov 2026");
    expect(weekLabel("2026-W53")).toBe("Week 53, 28 Dec 2026 to 3 Jan 2027");
  });

  it("accepts only real ISO weeks", () => {
    for (const week of ["2026-W47", "2026-W53", "2026-W01", "2024-W52"]) expect(isValidWeek(week)).toBe(true);
    for (const week of [
      "banana",
      "2026-W99",
      "2026-W00",
      "2026-47",
      "2026-w47",
      "2026-W47 ",
      "2025-W53",
      "2024-W53",
      "2026-W54",
      "",
    ])
      expect(isValidWeek(week)).toBe(false);
  });
});
