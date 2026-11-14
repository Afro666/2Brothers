import { formatNumber, peopleUnit } from "@/lib/format";
import type { TranslationVariables } from "@/lib/i18n";
import type { Order, OrderLine } from "@/types";

type Translate = (text: string, vars?: TranslationVariables) => string;

function quantityText(line: OrderLine): string {
  return `${formatNumber(line.quantity)} ${peopleUnit(line.product.salesUnit, line.quantity)}`;
}

/** "Name × 5 pieces" for an order with one line; "Name, 5 kg" for one of several, so the × reads as a value, not a product. */
function lineTitle(line: OrderLine, t: Translate, many: boolean): string {
  const name = line.product.names.en || line.product.id;
  const quantity = quantityText(line);
  return many ? t("{name}, {quantity}", { name, quantity }) : t("{name} × {quantity}", { name, quantity });
}

export function orderTitle(order: Pick<Order, "lines">, t: Translate): string {
  if (order.lines.length === 0) return t("Order");
  const first = lineTitle(order.lines[0]!, t, order.lines.length > 1);
  if (order.lines.length === 1) return first;
  if (order.lines.length === 2) return t("{first} · {second}", { first, second: lineTitle(order.lines[1]!, t, true) });
  return `${first} ${t("+{count} more", { count: order.lines.length - 1 })}`;
}
