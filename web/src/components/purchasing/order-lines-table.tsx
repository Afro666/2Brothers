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
  peopleUnit,
} from "@/lib/format";
import { useT } from "@/lib/i18n";
import { ProductThumb } from "./product-thumb";
import { cn } from "@/lib/utils";
import type { OrderLine } from "@/types";
import { ProductLink } from "@/components/purchasing/product-link";

/** What one line shows, computed once for both layouts. */
function lineFacts(line: OrderLine, now: Date) {
  const { product, offer } = line;
  const closed = isPassed(offer.closingTime, now);
  return {
    code: product.id,
    name: product.names.en || product.id,
    nameFi: product.names.fi,
    brand: product.brand,
    pack:
      product.baseUnitsPerSalesUnit == null
        ? null
        : formatPack(product.salesUnit, product.baseUnitsPerSalesUnit, product.baseUnit),
    salesUnit: peopleUnit(product.salesUnit, 1),
    quantity: `${formatNumber(line.quantity)} ${peopleUnit(product.salesUnit, line.quantity)}`,
    lineTotal: line.lineTotal,
    unitPrice: formatEur(offer.priceExVat),
    comparison:
      offer.comparisonPrice == null || offer.comparisonUnit == null
        ? "unknown"
        : `${formatEur(offer.comparisonPrice)} / ${peopleUnit(offer.comparisonUnit, 1)}`,
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

function PackText({ f }: { f: Facts }) {
  const t = useT();
  return (
    <>
      {f.pack ?? f.salesUnit}
      {f.pack == null ? <> <span className="unknown-value whitespace-normal">{t("pack size not in the catalog")}</span></> : null}
    </>
  );
}

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

function ReceiptLines({ facts }: { facts: Facts[] }) {
  const t = useT();
  return (
    <ul className="divide-y divide-dashed divide-input" aria-label={t("Lines")}>
      {facts.map((f) => (
        <li key={f.code} className="py-4 first:pt-0 last:pb-0">
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3">
            <div className="min-w-0">
              <div className="font-medium [overflow-wrap:anywhere]">{f.name}</div>
              <div className="mt-1 font-mono text-xs leading-5 break-words text-muted-foreground">
                {f.name !== f.code ? <>{f.code} · </> : null}
                <PackText f={f} />
              </div>
            </div>
            <div className="text-right font-mono text-sm tabular-nums">
              <div>
                <span className="sr-only">{t("Qty")}: </span>
                {f.quantity}
              </div>
              <div className="mt-1 font-semibold">
                <span className="sr-only">{t("Line total ex VAT")}: </span>
                {t(formatEur(f.lineTotal))}
              </div>
            </div>
          </div>
          <dl className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 text-xs">
            <dt className="text-muted-foreground">{t("Unit price ex VAT")}</dt>
            <dd className="text-right font-mono tabular-nums">{t(f.unitPrice)}</dd>
            <dt className="text-muted-foreground">{t("Compare")}</dt>
            <dd className="text-right font-mono tabular-nums">
              {f.comparison === "unknown" ? t("unknown") : f.comparison}
            </dd>
            <dt className="text-muted-foreground">{t("Stock")}</dt>
            <dd className="text-right">
              <StockText f={f} />
            </dd>
            <dt className="text-muted-foreground">{t("Available")}</dt>
            <dd className="text-right">
              <AvailableText f={f} />
            </dd>
            <dt className="text-muted-foreground">{t("Order by")}</dt>
            <dd className="text-right">
              <ClosingText f={f} />
            </dd>
          </dl>
          <p className="mt-3 text-xs text-muted-foreground [overflow-wrap:anywhere]">
            <span className="font-medium text-foreground">{t("Why: ")}</span>
            {f.why}
          </p>
        </li>
      ))}
    </ul>
  );
}

/**
 * The lines of one order. A table from `md` up; a list of stacked rows on a
 * phone, so nothing scrolls sideways at 390 px. Each line ends with the
 * engine's "why" sentence.
 */
export function OrderLinesTable({
  lines,
  now,
  variant = "default",
}: {
  lines: OrderLine[];
  now: Date;
  variant?: "default" | "receipt";
}) {
  const t = useT();
  const facts = lines.map((l) => lineFacts(l, now));
  if (variant === "receipt") return <ReceiptLines facts={facts} />;
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
                    <ProductThumb en={f.name} fi={f.nameFi} brand={f.brand} size="sm" />
                    <div>
                      <div className="font-medium"><ProductLink productId={f.code}>{f.name}</ProductLink></div>
                      {f.name !== f.code ? <div className="text-xs text-muted-foreground">{f.code}</div> : null}
                    </div>
                  </div>
                </TableCell>
                <TableCell><PackText f={f} /></TableCell>
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
              <div className="flex min-w-0 items-start gap-2">
                <ProductThumb en={f.name} fi={f.nameFi} brand={f.brand} size="sm" />
                <div className="min-w-0">
                <div className="font-medium"><ProductLink productId={f.code}>{f.name}</ProductLink></div>
                <div className="text-xs text-muted-foreground">
                    {f.name !== f.code ? <>{f.code} · </> : null}
                    <PackText f={f} />
                </div>
                </div>
              </div>
              <div className="shrink-0 text-right text-sm font-medium tabular-nums">{f.quantity}</div>
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
