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
import { cn } from "@/lib/utils";
import type { OrderLine } from "@/types";

/** What one line shows, computed once for both layouts. */
function lineFacts(line: OrderLine, now: Date) {
  const { product, offer } = line;
  const closed = isPassed(offer.closingTime, now);
  return {
    code: product.id,
    name: product.names.en,
    pack: formatPack(product.salesUnit, product.baseUnitsPerSalesUnit, product.baseUnit),
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
  if (f.blocked) return <span className="font-medium text-danger">sales block</span>;
  return f.stockUnknown ? (
    <span className="font-medium text-warning" title="Valio did not measure the stock for this product">
      unknown
    </span>
  ) : (
    <span>{f.stock}</span>
  );
}

function ClosingText({ f }: { f: Facts }) {
  return (
    <span className={cn(f.closed && "font-medium text-danger")} data-closed={f.closed || undefined}>
      {f.closing}
      {f.closed ? " (passed)" : null}
    </span>
  );
}

function AvailableText({ f }: { f: Facts }) {
  return (
    <span className={cn(f.late && "font-medium text-warning")}>
      {f.available}
      {f.late ? " (later than asked)" : null}
    </span>
  );
}

/**
 * The lines of one order. A table from `md` up; a list of stacked rows on a
 * phone, so nothing scrolls sideways at 390 px. Each line ends with the
 * engine's "why" sentence.
 */
export function OrderLinesTable({ lines, now }: { lines: OrderLine[]; now: Date }) {
  const facts = lines.map((l) => lineFacts(l, now));
  return (
    <div>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Product</TableHead>
              <TableHead>Pack</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Unit price ex VAT</TableHead>
              <TableHead className="text-right">Compare</TableHead>
              <TableHead>Stock</TableHead>
              <TableHead>Available</TableHead>
              <TableHead>Order by</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {facts.map((f) => [
              <TableRow key={`${f.code}-main`} className="border-b-0">
                <TableCell>
                  <div className="font-medium">{f.name}</div>
                  <div className="text-xs text-muted-foreground">{f.code}</div>
                </TableCell>
                <TableCell>{f.pack}</TableCell>
                <TableCell className="text-right tabular-nums">{f.quantity}</TableCell>
                <TableCell className="text-right tabular-nums">{f.unitPrice}</TableCell>
                <TableCell className="text-right tabular-nums">{f.comparison}</TableCell>
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
                  <span className="font-medium text-foreground">Why: </span>
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
                  {f.code} · {f.pack}
                </div>
              </div>
              <div className="text-right text-sm font-medium tabular-nums">{f.quantity}</div>
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Unit price ex VAT</dt>
              <dd className="tabular-nums">{f.unitPrice}</dd>
              <dt className="text-muted-foreground">Compare</dt>
              <dd className="tabular-nums">{f.comparison}</dd>
              <dt className="text-muted-foreground">Stock</dt>
              <dd>
                <StockText f={f} />
              </dd>
              <dt className="text-muted-foreground">Available</dt>
              <dd>
                <AvailableText f={f} />
              </dd>
              <dt className="text-muted-foreground">Order by</dt>
              <dd>
                <ClosingText f={f} />
              </dd>
            </dl>
            <p className="text-sm text-muted-foreground">
              <span className="font-medium text-foreground">Why: </span>
              {f.why}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
