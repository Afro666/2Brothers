import { describe, expect, it } from "vitest";

import { isoWeekOf, weekDates } from "@/lib/week";

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
});
