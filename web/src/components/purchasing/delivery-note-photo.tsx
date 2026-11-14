import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/api";
import type { DeliveryClaim, DeliveryLot, DeliveryNoteRead } from "@/api/types";
import { ProductThumb } from "@/components/purchasing/product-thumb";
import { Button } from "@/components/ui/button";
import { formatEur, formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { downscalePhoto } from "@/lib/shelf-photo";
import type { Order, Product } from "@/types";
import { NemotronMark } from "@/components/nemotron-mark";

export function DeliveryNotePhoto({ order }: { order: Order }) {
  const t = useT();
  const api = useApi();
  const { session, status } = useSession();
  const input = useRef<HTMLInputElement>(null);
  const revision = useRef(0);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DeliveryNoteRead | null>(null);
  const [choices, setChoices] = useState<Record<number, boolean>>({});
  const [catalogProducts, setCatalogProducts] = useState<Record<string, Product>>({});
  useEffect(() => () => { revision.current += 1; }, []);
  const allowed = status === "signed-in" && session?.kind === "human" && (session.role === "approver" || session.role === "chef");
  const products = new Map(order.lines.map((line) => [line.product.id, line.product]));
  // A placed order without its proposal names a product by its code only (#1198): look it up then.
  const known = (id: string): Product | undefined => {
    const product = products.get(id);
    return product && product.names.en !== id ? product : undefined;
  };
  const productOf = (id: string): Product | undefined => known(id) ?? catalogProducts[id] ?? products.get(id);
  const label = (id: string) => id === "unknown" ? t("unknown") : productOf(id)?.names.en ?? id;
  const thumb = (id: string) => {
    const product = productOf(id);
    return <ProductThumb en={product?.names.en} fi={product?.names.fi} brand={product?.brand} size="sm" />;
  };
  const amount = (n: number | null, unit: string) => n == null ? t("unknown") : `${formatNumber(n)} ${unit}`;
  const statuses = { RECEIVED: t("Received"), SHORT: t("Short delivery"), MISSING: t("Missing"), UNKNOWN: t("unknown"),
    SUBSTITUTE: t("Substitute"), EXTRA: t("Not ordered"), UNREADABLE: t("Unreadable") };
  const lotText = (row: DeliveryLot) => t("Lot: {lot}; best before: {date}; printed quantity: {quantity}", {
    lot: row.lot === "unknown" ? t("unknown") : row.lot,
    date: row.bestBefore === "unknown" ? t("unknown") : row.bestBefore,
    quantity: amount(row.quantity, row.unit),
  });
  const claim = result?.claim ?? null;
  const supplier = claim?.supplierName ?? t("the supplier");
  const claimHeadline = (c: DeliveryClaim) => {
    const amount = formatEur(c.totalEur);
    if (c.quantity != null && c.unit === "KI") return t(c.quantity === 1 ? "{count} case short: {amount} to claim from {supplier}"
      : "{count} cases short: {amount} to claim from {supplier}", { count: formatNumber(c.quantity), amount, supplier });
    if (c.quantity != null && c.unit) return t("{count} {unit} short: {amount} to claim from {supplier}", { count: formatNumber(c.quantity), unit: c.unit, amount, supplier });
    return t("{count} lines short or missing: {amount} to claim from {supplier}", { count: String(c.lines), amount, supplier });
  };
  /** Plain text for a person to send to the supplier: every number is the gateway's, none is computed here. */
  function claimText(read: DeliveryNoteRead, c: DeliveryClaim): string {
    const rows = read.lines.filter((line) => line.status === "SHORT" || line.status === "MISSING").map((line) => {
      const unit = line.orderUnit ?? line.baseUnit;
      const missingQty = line.orderUnit && line.missingOrderQty != null ? line.missingOrderQty : line.missing;
      return `- ${t("{product} ({code}): {status}, ordered {ordered}, missing {missing}, {price} each = {value}", {
        product: label(line.productId), code: line.productId, status: statuses[line.status],
        ordered: amount(line.orderUnit ? line.orderQuantity : line.ordered, unit), missing: amount(missingQty, line.orderUnit ? unit : line.baseUnit),
        price: line.unitPrice == null ? t("price unknown") : formatEur(line.unitPrice),
        value: line.claimEur == null ? t("value unknown") : formatEur(line.claimEur),
      })}`;
    });
    return [
      t("Claim for a short delivery to {supplier}", { supplier }),
      t("Order: {id}", { id: read.orderId }),
      t("Note: {reference}; delivery date: {date}", { reference: read.orderRef, date: read.deliveryDate }),
      ...rows,
      t("Total to claim: {amount} (ex VAT, at the order's prices)", { amount: formatEur(c.totalEur) }),
      ...(c.notValued ? [t("{count} more lines could not be valued; check them by hand.", { count: String(c.notValued) })] : []),
    ].join("\n");
  }
  async function copyClaim() {
    if (!result || !claim) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(claimText(result, claim));
        toast.success(t("Claim copied. Nothing was sent to {supplier}.", { supplier }));
        return;
      }
    } catch {}
    toast.error(t("Copy failed. Write the claim down from the screen."));
  }
  const pending = result?.notOrdered.some((line, i) => line.needsApproval && choices[i] === undefined) ?? false;

  async function read(file?: File) {
    if (!file || reading || !allowed) return;
    const turn = ++revision.current;
    setReading(true); setError(null); setResult(null); setChoices({});
    try {
      const answer = await api.readDeliveryNote(order.id, await downscalePhoto(file), session?.role === "chef" ? "chef" : "human");
      if (revision.current !== turn) return;
      setResult(answer);
      const missing = [...new Set([...answer.lines, ...answer.notOrdered].map((line) => line.productId))].filter((id) => id !== "unknown" && !known(id));
      if (missing.length) void api.getProducts(missing).then((found) => {
        if (revision.current === turn) setCatalogProducts(Object.fromEntries(found.map((product) => [product.id, product])));
      }, () => undefined);
    } catch (cause) {
      if (revision.current === turn) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (revision.current === turn) setReading(false);
    }
  }

  return <section className="space-y-4 rounded-lg border bg-card p-4" aria-labelledby="delivery-note-title">
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="space-y-1">
        <h2 id="delivery-note-title" className="text-base font-semibold">{t("Photo of the delivery note")}</h2>
        <p className="max-w-prose text-sm text-muted-foreground"><NemotronMark />{t("Nemotron reads the note and compares it with this order. Check every quantity before updating stock.")}</p>
      </div>
      <Button type="button" disabled={!allowed || reading} onClick={() => input.current?.click()}>{t("Choose a delivery note photo")}</Button>
      <input ref={input} type="file" accept="image/jpeg,image/png" className="sr-only" aria-label={t("Choose a delivery note photo")}
        disabled={!allowed || reading} onChange={(e) => { const file = e.currentTarget.files?.[0]; e.currentTarget.value = ""; void read(file); }} />
    </div>
    {!allowed && status !== "loading" ? <p className="text-sm text-muted-foreground">{t("A chef or approver can read a delivery note.")}</p> : null}
    {reading ? <p role="status">{t("Reading the delivery note. This may take a few seconds.")}</p> : null}
    {error ? <p role="alert" className="text-sm text-destructive">{t("The note could not be read: {error}. Check the delivery by hand.", { error })}</p> : null}
    {result ? <div className="space-y-3">
      <p role="status" className="font-medium">{result.complete ? t("All ordered lines were read as received. Check them before saving stock.") : t("This delivery needs checking.")}</p>
      <p className="text-sm">{t("Note: {reference}; delivery date: {date}", { reference: result.orderRef, date: result.deliveryDate })}</p>
      {!result.lines.length ? <p>{t("No order lines were read. Check the delivery by hand.")}</p> : null}
      <ul className="divide-y">
        {result.lines.map((line, i) => <li key={`${line.productId}-${i}`} className="space-y-1 py-3 text-sm">
          <p className="flex items-center gap-2 font-semibold">{thumb(line.productId)}<span className="min-w-0 break-words">{label(line.productId)} — {statuses[line.status]}</span></p>
          <p>{t("Ordered: {ordered}; received: {received}; missing: {missing}", {
            ordered: amount(line.ordered, line.baseUnit), received: amount(line.received, line.baseUnit), missing: amount(line.missing, line.baseUnit),
          })}</p>
          {(line.status === "SHORT" || line.status === "MISSING") && line.claimEur != null ? <p>{t("To claim: {value}", { value: formatEur(line.claimEur) })}</p> : null}
          {line.lots.map((row, n) => <p className="text-muted-foreground" key={n}>{lotText(row)}</p>)}
        </li>)}
      </ul>
      {claim && (claim.lines > 0 || claim.notValued > 0) ? <section aria-labelledby="delivery-claim-title" className="space-y-2 rounded border border-destructive/40 p-3 text-sm">
        <p id="delivery-claim-title" className="text-base font-semibold">{claimHeadline(claim)}</p>
        <p className="text-muted-foreground">{t("At this order's prices, ex VAT. The app computes the amount, not the model. Nothing is sent to {supplier}.", { supplier })}</p>
        {claim.notValued ? <p className="text-warning">{t("{count} more lines could not be valued; check them by hand.", { count: String(claim.notValued) })}</p> : null}
        {result.notOrdered.some((line) => line.needsApproval) ? <p>{t("A substitute you accept is not taken off this amount.")}</p> : null}
        <Button type="button" variant="outline" size="sm" onClick={() => void copyClaim()}>{t("Copy the claim")}</Button>
      </section> : null}
      {result.notOrdered.map((line, i) => <div key={i} className="space-y-2 rounded border border-warning/40 p-3 text-sm">
        <p className="flex items-center gap-2 font-semibold">{thumb(line.productId)}<span className="min-w-0 break-words">{label(line.productId)} — {statuses[line.status]}</span></p>
        <p>{lotText(line)}</p>
        {line.needsApproval ? <fieldset className="space-y-2">
          <legend>{t("Was this substitute received for {product}?", { product: label(line.replaces) })}</legend>
          <div className="flex gap-2">
            <Button type="button" size="sm" variant={choices[i] === true ? "default" : "outline"} aria-pressed={choices[i] === true} onClick={() => setChoices((old) => ({ ...old, [i]: true }))}>{t("Yes, received")}</Button>
            <Button type="button" size="sm" variant={choices[i] === false ? "default" : "outline"} aria-pressed={choices[i] === false} onClick={() => setChoices((old) => ({ ...old, [i]: false }))}>{t("No, not received")}</Button>
          </div>
        </fieldset> : null}
      </div>)}
      <p className="text-sm text-muted-foreground">{t("No stock count has been changed. Substitute choices are not saved approvals. Check allergens before use, then count current stock separately.")}</p>
      {pending ? <><p className="text-sm text-warning">{t("Answer yes or no for each substitute first.")}</p><Button disabled>{t("Update counted stock")}</Button></> :
        <Button asChild><Link to="/stock">{t("Update counted stock")}</Link></Button>}
    </div> : null}
  </section>;
}
