import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { translate, type TranslationVariables } from "@/lib/i18n";
import { orderTitle } from "@/lib/order-title";
import type { OrderLine } from "@/types";

const t = (text: string, vars?: TranslationVariables) => translate("en", text, vars);

function namedLine(line: OrderLine, name: string): OrderLine {
  return { ...line, product: { ...line.product, names: { en: name } } };
}

describe("orderTitle", () => {
  beforeEach(() => localStorage.clear());

  it("names the only product and its quantity", async () => {
    const order = await createMockApi().getOrder("ORD-1042");
    expect(orderTitle(order, t)).toBe("Arla 1 L lactose free fat free UHT milk drink × 51 pieces");
  });

  it("names both products on a two-line order", async () => {
    const order = await createMockApi().getOrder("ORD-1042");
    const lines = [namedLine(order.lines[0]!, "Milk"), namedLine(order.lines[0]!, "Cream")];
    expect(orderTitle({ ...order, lines }, t)).toBe("Milk × 51 pieces · Cream × 51 pieces");
  });

  it("keeps the first product and counts the rest on a four-line order", async () => {
    const order = await createMockApi().getOrder("ORD-1042");
    const lines = [1, 2, 3, 4].map((index) => namedLine(order.lines[0]!, `Product ${index}`));
    expect(orderTitle({ ...order, lines }, t)).toBe("Product 1 × 51 pieces +3 more");
  });

  it("uses plain case units in a compact multi-line title", async () => {
    const order = await createMockApi().getOrder("ORD-1042");
    const line = { ...order.lines[0]!, quantity: 3, product: { ...order.lines[0]!.product, salesUnit: "KI" } };
    const lines = [1, 2, 3].map((index) => namedLine(line, `Product ${index}`));
    expect(orderTitle({ ...order, lines }, t)).toBe("Product 1 × 3 cases +2 more");
  });

  it("uses the code when a line has no product name", async () => {
    const order = await createMockApi().getOrder("ORD-1042");
    const lines = [namedLine(order.lines[0]!, "")];
    expect(orderTitle({ ...order, lines }, t)).toBe(`${order.lines[0]!.product.id} × 51 pieces`);
  });

  it("uses the singular and leaves an unknown unit code alone", async () => {
    const order = await createMockApi().getOrder("ORD-1042");
    const line = { ...order.lines[0]!, quantity: 1, product: { ...order.lines[0]!.product, salesUnit: "KI" } };
    expect(orderTitle({ ...order, lines: [line] }, t)).toContain("× 1 case");
    expect(orderTitle({ ...order, lines: [{ ...line, product: { ...line.product, salesUnit: "BAG" } }] }, t)).toContain(
      "× 1 BAG",
    );
  });
});
