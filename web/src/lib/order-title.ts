import { formatNumber, MEASURED_UNITS, peopleUnit } from "@/lib/format";
import type { TranslationVariables } from "@/lib/i18n";
import type { Order, OrderLine } from "@/types";

type Translate = (text: string, vars?: TranslationVariables) => string;

/** "…5kg MSC × 15 kg" reads as 5 kg times 15 kg (#1803): a name with a size before a weighed quantity takes a comma. */
const SIZE_IN_NAME = /\d\s*(?:kg|g|l|dl|cl|ml)\b/i;

function lineTitle(line: OrderLine, t: Translate): string {
  const vars = {
    name: line.product.names.en || line.product.id,
    quantity: `${formatNumber(line.quantity)} ${peopleUnit(line.product.salesUnit, line.quantity)}`,
  };
  return MEASURED_UNITS.has(line.product.salesUnit.toUpperCase()) && SIZE_IN_NAME.test(vars.name)
    ? t("{name}, {quantity}", vars)
    : t("{name} × {quantity}", vars);
}

export function orderTitle(order: Pick<Order, "lines">, t: Translate): string {
  if (order.lines.length === 0) return t("Order");
  const first = lineTitle(order.lines[0]!, t);
  if (order.lines.length === 1) return first;
  if (order.lines.length === 2) return t("{first} · {second}", { first, second: lineTitle(order.lines[1]!, t) });
  return `${first} ${t("+{count} more", { count: order.lines.length - 1 })}`;
}
