import { formatNumber } from "@/lib/format";
import type { TranslationVariables } from "@/lib/i18n";
import type { Order, OrderLine } from "@/types";

type Translate = (text: string, vars?: TranslationVariables) => string;

function lineTitle(line: OrderLine, t: Translate): string {
  return t("{name} × {quantity}", {
    name: line.product.names.en || line.product.id,
    quantity: `${formatNumber(line.quantity)} ${line.product.salesUnit}`,
  });
}

export function orderTitle(order: Pick<Order, "lines">, t: Translate): string {
  if (order.lines.length === 0) return t("Order");
  const first = lineTitle(order.lines[0]!, t);
  if (order.lines.length === 1) return first;
  if (order.lines.length === 2) return t("{first} · {second}", { first, second: lineTitle(order.lines[1]!, t) });
  return `${first} ${t("+{count} more", { count: order.lines.length - 1 })}`;
}
