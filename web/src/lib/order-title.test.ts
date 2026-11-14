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
    expect(orderTitle(order, t)).toBe("Arla 1 L lactose free fat free UHT milk drink × 51 ST");
  });

  it("names both products on a two-line order", async () => {
    const order = await createMockApi().getOrder("ORD-1042");
    const lines = [namedLine(order.lines[0]!, "Milk"), namedLine(order.lines[0]!, "Cream")];
    expect(orderTitle({ ...order, lines }, t)).toBe("Milk × 51 ST · Cream × 51 ST");
  });

  it("keeps the first product and counts the rest on a four-line order", async () => {
    const order = await createMockApi().getOrder("ORD-1042");
    const lines = [1, 2, 3, 4].map((index) => namedLine(order.lines[0]!, `Product ${index}`));
    expect(orderTitle({ ...order, lines }, t)).toBe("Product 1 × 51 ST +3 more");
  });

  it("uses the code when a line has no product name", async () => {
    const order = await createMockApi().getOrder("ORD-1042");
    const lines = [namedLine(order.lines[0]!, "")];
    expect(orderTitle({ ...order, lines }, t)).toBe(`${order.lines[0]!.product.id} × 51 ST`);
  });
});
