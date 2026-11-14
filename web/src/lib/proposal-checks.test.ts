import { describe, expect, it } from "vitest";

import { statusChips } from "@/lib/proposal-checks";
import { approval, orders } from "@/mocks/milk-case";
import type { Order } from "@/types";

const NOW = new Date("2026-11-13T21:00:00+02:00");

/** Three lines: the first has stock nobody reports, the other two are confirmed. */
function threeLines(): Order {
  const [line] = orders.needsApproval.lines;
  const confirmed = (id: string) => ({
    ...line,
    product: { ...line.product, id },
    offer: { ...line.offer, availableAmount: line.quantity, closingTime: null },
  });
  return {
    ...orders.needsApproval,
    lines: [
      { ...line, product: { ...line.product, id: "own-salmon" }, offer: { ...line.offer, availableAmount: 999999, closingTime: null } },
      confirmed("460643"),
      confirmed("460708"),
    ],
  };
}

function confirmChips(request: typeof approval, order: Order) {
  return statusChips({ request: { ...request, reasons: [] }, order, now: NOW, heldByRecall: false, leftOut: 0 })
    .filter((chip) => chip.key.startsWith("confirm"))
    .map(({ text, values }) => ({ text, values }));
}

describe("statusChips: who must confirm stock", () => {
  it("names the other supplier with its count, and not Valio, when the unconfirmed line is that supplier's", () => {
    const request = {
      ...approval,
      suppliersToConfirm: [{ supplierId: "sup-demo-fish", name: "Baltic Catch Fish Wholesale (demo)", count: 1 }],
    };
    expect(confirmChips(request, threeLines())).toEqual([
      { text: "{supplier} must confirm {count}", values: { supplier: "Baltic Catch Fish Wholesale (demo)", count: 1 } },
    ]);
  });

  it("counts for Valio only the unconfirmed lines that no other supplier's block holds", () => {
    const order = threeLines();
    order.lines[1].offer.availableAmount = 999999;
    const request = {
      ...approval,
      suppliersToConfirm: [{ supplierId: "sup-demo-fish", name: "Baltic Catch", count: 1 }],
    };
    expect(confirmChips(request, order)).toEqual([
      { text: "Valio must confirm {count}", values: { count: 1 } },
      { text: "{supplier} must confirm {count}", values: { supplier: "Baltic Catch", count: 1 } },
    ]);
  });

  it("keeps the Valio count when no supplier block says whose the line is", () => {
    expect(confirmChips({ ...approval, suppliersToConfirm: [] }, threeLines())).toEqual([
      { text: "Valio must confirm {count}", values: { count: 1 } },
    ]);
  });

  it("names a supplier without a count when the gateway gave none", () => {
    const request = { ...approval, suppliersToConfirm: [{ supplierId: "sup-bakery", name: "Leipomo Demo" }] };
    expect(confirmChips(request, { ...threeLines(), lines: threeLines().lines.slice(1) })).toEqual([
      { text: "{supplier} must confirm", values: { supplier: "Leipomo Demo" } },
    ]);
  });

  it("takes Valio's count from Valio's own block when the order lines disagree (#1899)", () => {
    // The order lines show one unconfirmed line; the gateway's blocks say Valio has two and the fish supplier one.
    const request = {
      ...approval,
      valioToConfirm: 2,
      suppliersToConfirm: [{ supplierId: "sup-demo-fish", name: "Baltic Catch", count: 1 }],
    };
    expect(confirmChips(request, threeLines())).toEqual([
      { text: "Valio must confirm {count}", values: { count: 2 } },
      { text: "{supplier} must confirm {count}", values: { supplier: "Baltic Catch", count: 1 } },
    ]);
  });

  it("shows no Valio chip when Valio's block has no unknown-stock lines, even if an order line looks unconfirmed", () => {
    const request = { ...approval, valioToConfirm: 0, suppliersToConfirm: [] };
    expect(confirmChips(request, threeLines())).toEqual([]);
  });
});
