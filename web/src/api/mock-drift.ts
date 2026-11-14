import type { DriftReport } from "@/types";

/**
 * Demo drift for week 2026-W46 (Monday 2026-11-09), in the shape `store.drift` returns.
 * The kitchen: milk portions creep, coffee got dearer. Valio sees two consenting kitchens.
 */
export function driftMock(): DriftReport {
  return {
    week: "2026-11-09",
    warnings: [
      {
        productId: "462775",
        productName: "Arla lactose-free milk 1 L",
        kind: "portion_creep",
        change: 0.4,
        unit: "ST",
        qtyPer100: 14,
        baselineQty: 10,
        spendPer100: 35.98,
        baselineSpend: 25.7,
        baselineWeeks: 4,
        why: "14.0 ST per 100 guests last week, 10.0 on average over the 4 weeks before (+40%). Check portions before this order renews.",
      },
      {
        productId: "461332",
        productName: "Kulta Katriina filter coffee 5 x 1 kg",
        kind: "cost_creep",
        change: 0.3,
        unit: "KI",
        qtyPer100: 1,
        baselineQty: 1,
        spendPer100: 13,
        baselineSpend: 10,
        baselineWeeks: 4,
        why: "EUR 13.00 per 100 guests last week, EUR 10.00 on average over the 4 weeks before (+30%) for the same amount. The price went up.",
      },
    ],
  };
}

export function supplierDriftMock(): DriftReport {
  const [milk, coffee] = driftMock().warnings;
  return {
    week: "2026-11-09",
    warnings: [
      { ...milk, kitchenId: "K04", kitchenName: "K04 Hotel Aurora Helsinki" },
      {
        ...coffee,
        change: 0.22,
        spendPer100: 12.2,
        why: "EUR 12.20 per 100 guests last week, EUR 10.00 on average over the 4 weeks before (+22%) for the same amount. The price went up.",
        kitchenId: "K07",
        kitchenName: "K07 Hospital kitchen Turku",
      },
    ],
  };
}
