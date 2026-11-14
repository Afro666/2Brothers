import { describe, expect, it } from "vitest";

import { mapDrift } from "@/api/map-drift";

const warning = {
  product_id: "462775",
  kind: "portion_creep",
  change: 0.4,
  unit: "ST",
  qty_per_100: 14,
  baseline_qty: 10,
  spend_per_100: 35.98,
  baseline_spend: "25.70",
  baseline_weeks: 4,
  why: "14.0 ST per 100 guests last week",
};

describe("mapDrift", () => {
  it("maps the contract shape, numbers from strings too", () => {
    const report = mapDrift({ week: "2026-11-09", warnings: [warning] });
    expect(report.week).toBe("2026-11-09");
    expect(report.warnings[0]).toMatchObject({
      productId: "462775",
      productName: null,
      baselineSpend: 25.7,
    });
    expect(report.warnings[0].kitchenId).toBeUndefined();
  });

  it("keeps the kitchen on the supplier side", () => {
    const report = mapDrift({
      week: "2026-11-09",
      warnings: [{ ...warning, kitchen_id: "K04", kitchen_name: "Hotel" }],
    });
    expect(report.warnings[0]).toMatchObject({
      kitchenId: "K04",
      kitchenName: "Hotel",
    });
  });

  it("refuses an unknown kind or a missing number", () => {
    expect(() =>
      mapDrift({ week: "w", warnings: [{ ...warning, kind: "drop" }] }),
    ).toThrow(/unknown drift kind/);
    expect(() =>
      mapDrift({ week: "w", warnings: [{ ...warning, change: null }] }),
    ).toThrow(/change/);
    expect(() => mapDrift({ warnings: [] })).toThrow(/week/);
  });
});
