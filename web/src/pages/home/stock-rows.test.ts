import { describe, expect, it } from "vitest";

import { stockToCheck } from "@/pages/home/stock-rows";
import type { DemandLine, StockItem } from "@/types";

const item = (productId: string, onHand: number | null, onOrder: number | null = 0): StockItem => ({
  productId,
  productName: productId,
  unit: "KG",
  onHand,
  onOrder,
  countedAt: null,
  lastDelivery: null,
});
const need = (productId: string, amount: number): DemandLine => ({
  productId,
  productName: productId,
  unit: "KG",
  date: "2026-11-16",
  need: amount,
  why: "",
});

describe("stockToCheck", () => {
  it("puts the least covered shortage first, then products nobody counted", () => {
    const rows = stockToCheck(
      [item("half", 5), item("empty", 0), item("fine", 50), item("blank", null)],
      [need("half", 10), need("empty", 4), need("fine", 10), need("ghost", 1), need("ghost", 2)],
    );
    expect(rows.map((row) => row.productId)).toEqual(["empty", "half", "blank", "ghost"]);
    expect(rows[0]).toMatchObject({ kind: "short", shortfall: 4 });
  });

  it("counts stock on order, and says when on order is unknown", () => {
    const rows = stockToCheck([item("a", 2, 7), item("b", 2, null)], [need("a", 10), need("b", 10)]);
    expect(rows).toEqual([
      expect.objectContaining({ productId: "b", shortfall: 8, onOrderUnknown: true }),
      expect.objectContaining({ productId: "a", shortfall: 1, onOrderUnknown: false }),
    ]);
  });

  it("orders equal cover by the larger shortfall", () => {
    const rows = stockToCheck([item("small", 0), item("big", 0)], [need("small", 1), need("big", 9)]);
    expect(rows.map((row) => row.productId)).toEqual(["big", "small"]);
  });
});
