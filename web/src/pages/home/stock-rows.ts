import type { DemandLine, StockItem } from "@/types";

export type StockRow =
  | { kind: "short"; productId: string; productName: string; unit: string; shortfall: number; onOrderUnknown: boolean; cover: number }
  | { kind: "not_counted"; productId: string; productName: string };

/** How many rows the Home tile shows; the rest is one link to /stock. */
export const HOME_STOCK_ROWS = 5;

/**
 * The products to check for the next 7 days, most urgent first: shortages by the share of
 * the need that stock covers (least covered first), then products nobody counted.
 * On order unknown: the count alone decides, and the row says so.
 */
export function stockToCheck(stock: StockItem[], demand: DemandLine[]): StockRow[] {
  const needed = new Map<string, number>();
  for (const line of demand) needed.set(line.productId, (needed.get(line.productId) ?? 0) + line.need);
  const short: StockRow[] = [];
  const notCounted: StockRow[] = [];
  for (const item of stock) {
    if (item.onHand === null) {
      notCounted.push({ kind: "not_counted", productId: item.productId, productName: item.productName });
      continue;
    }
    const need = needed.get(item.productId) ?? 0;
    const have = item.onHand + (item.onOrder ?? 0);
    if (need > have) {
      short.push({
        kind: "short",
        productId: item.productId,
        productName: item.productName,
        unit: item.unit,
        shortfall: need - have,
        onOrderUnknown: item.onOrder === null,
        cover: Math.max(0, have) / need,
      });
    }
  }
  const counted = new Set(stock.map((item) => item.productId));
  const seen = new Set<string>();
  for (const line of demand) {
    if (counted.has(line.productId) || seen.has(line.productId)) continue;
    seen.add(line.productId);
    notCounted.push({ kind: "not_counted", productId: line.productId, productName: line.productName });
  }
  short.sort((a, b) =>
    a.kind === "short" && b.kind === "short" ? a.cover - b.cover || b.shortfall - a.shortfall : 0,
  );
  return [...short, ...notCounted];
}
