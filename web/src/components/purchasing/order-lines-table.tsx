import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  formatDate,
  formatDateTime,
  formatEur,
  formatNumber,
  formatOfferStock,
  formatPack,
  isLater,
  isPassed,
  isStockUnconfirmed,
} from "@/lib/format";
import { useT } from "@/lib/i18n";
import { ProductThumb } from "./product-thumb";
import { cn } from "@/lib/utils";
import type { OrderLine } from "@/types";

/** What one line shows, computed once for both layouts. */
function lineFacts(line: OrderLine, now: Date) {
  const { product, offer } = line;
  const closed = isPassed(offer.closingTime, now);
  return {
    code: product.id,
    name: product.names.en,
    pack:
      product.baseUnitsPerSalesUnit == null
        ? null
        : formatPack(product.salesUnit, product.baseUnitsPerSalesUnit, product.baseUnit),
    salesUnit: product.salesUnit,
    quantity: `${formatNumber(line.quantity)} ${product.salesUnit}`,
    unitPrice: formatEur(offer.priceExVat),
    comparison:
      offer.comparisonPrice == null || offer.comparisonUnit == null
        ? "unknown"
        : `${formatEur(offer.comparisonPrice)} / ${offer.comparisonUnit}`,
    stock: formatOfferStock(offer),
    stockUnknown: isStockUnconfirmed(offer),
    available: formatDate(offer.availableDate),
    late: isLater(offer.availableDate, offer.requestedDate),
    closing: formatDateTime(offer.closingTime),
    closed,
    blocked: offer.salesBlock,
    why: line.why,
  };
}

type Facts = ReturnType<typeof lineFacts>;

function StockText({ f }: { f: Facts }) {
  const t = useT();
  if (f.blocked) return <span className="font-medium text-danger">{t("sales block")}</span>;
  return f.stockUnknown ? (
    <span className="font-medium text-warning" title={t("Valio did not measure the stock for this product")}>
      {t("unknown")}
    </span>
  ) : (
    <span>{t(f.stock)}</span>
  );
}

function ClosingText({ f }: { f: Facts }) {
  const t = useT();
  return (
    <span className={cn(f.closed && "font-medium text-danger")} data-closed={f.closed || undefined}>
      {t(f.closing)}
      {f.closed ? t(" (passed)") : null}
    </span>
  );
}

function AvailableText({ f }: { f: Facts }) {
  const t = useT();
  return (
    <span className={cn(f.late && "font-medium text-warning")}>
      {t(f.available)}
      {f.late ? t(" (later than asked)") : null}
    </span>
  );
}

/**
 * The lines of one order. A table from `md` up; a list of stacked rows on a
 * phone, so nothing scrolls sideways at 390 px. Each line ends with the
 * engine's "why" sentence.
 */
export function OrderLinesTable({ lines, now }: { lines: OrderLine[]; now: Date }) {
  const t = useT();
  const facts = lines.map((l) => lineFacts(l, now));
  return (
    <div>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("Product")}</TableHead>
              <TableHead>{t("Pack")}</TableHead>
              <TableHead className="text-right">{t("Qty")}</TableHead>
              <TableHead className="text-right">{t("Unit price ex VAT")}</TableHead>
              <TableHead className="text-right">{t("Compare")}</TableHead>
              <TableHead>{t("Stock")}</TableHead>
              <TableHead>{t("Available")}</TableHead>
              <TableHead>{t("Order by")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {facts.map((f) => [
              <TableRow key={`${f.code}-main`} className="border-b-0">
                <TableCell>
                  <div className="flex items-center gap-2">
                    <ProductThumb en={f.name} size="sm" />
                    <div>
                      <div className="font-medium">{f.name}</div>
                      <div className="text-xs text-muted-foreground">{f.code}</div>
                    </div>
                  </div>
                </TableCell>
                <TableCell>{f.pack ?? t("{unit} (pack size unknown)", { unit: f.salesUnit })}</TableCell>
                <TableCell className="text-right tabular-nums">{f.quantity}</TableCell>
                <TableCell className="text-right tabular-nums">{t(f.unitPrice)}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {f.comparison === "unknown" ? t("unknown") : f.comparison}
                </TableCell>
                <TableCell>
                  <StockText f={f} />
                </TableCell>
                <TableCell>
                  <AvailableText f={f} />
                </TableCell>
                <TableCell>
                  <ClosingText f={f} />
                </TableCell>
              </TableRow>,
              <TableRow key={`${f.code}-why`} className="hover:bg-transparent">
                <TableCell colSpan={8} className="pt-0 whitespace-normal text-muted-foreground">
                  <span className="font-medium text-foreground">{t("Why: ")}</span>
                  {f.why}
                </TableCell>
              </TableRow>,
            ])}
          </TableBody>
        </Table>
      </div>

      <ul className="divide-y md:hidden">
        {facts.map((f) => (
          <li key={f.code} className="space-y-2 py-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="font-medium">{f.name}</div>
                <div className="text-xs text-muted-foreground">
                  {f.code} · {f.pack ?? t("{unit} (pack size unknown)", { unit: f.salesUnit })}
                </div>
              </div>
              <div className="text-right text-sm font-medium tabular-nums">{f.quantity}</div>
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
              <dt className="text-muted-foreground">{t("Unit price ex VAT")}</dt>
              <dd className="tabular-nums">{t(f.unitPrice)}</dd>
              <dt className="text-muted-foreground">{t("Compare")}</dt>
              <dd className="tabular-nums">{f.comparison === "unknown" ? t("unknown") : f.comparison}</dd>
              <dt className="text-muted-foreground">{t("Stock")}</dt>
              <dd>
                <StockText f={f} />
              </dd>
              <dt className="text-muted-foreground">{t("Available")}</dt>
              <dd>
                <AvailableText f={f} />
              </dd>
              <dt className="text-muted-foreground">{t("Order by")}</dt>
              <dd>
                <ClosingText f={f} />
              </dd>
            </dl>
            <p className="text-sm text-muted-foreground">
              <span className="font-medium text-foreground">{t("Why: ")}</span>
              {f.why}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
