import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { useApi } from "@/api";
import type { DeliveryLot, DeliveryNoteRead } from "@/api/types";
import { Button } from "@/components/ui/button";
import { formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { downscalePhoto } from "@/lib/shelf-photo";
import type { Order } from "@/types";

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
  useEffect(() => () => { revision.current += 1; }, []);
  const allowed = status === "signed-in" && session?.kind === "human" && (session.role === "approver" || session.role === "chef");
  const names = new Map(order.lines.map((line) => [line.product.id, line.product.names.en]));
  const label = (id: string) => id === "unknown" ? t("unknown") : names.get(id) ?? id;
  const amount = (n: number | null, unit: string) => n == null ? t("unknown") : `${formatNumber(n)} ${unit}`;
  const statuses = { RECEIVED: t("Received"), SHORT: t("Short delivery"), MISSING: t("Missing"), UNKNOWN: t("unknown"),
    SUBSTITUTE: t("Substitute"), EXTRA: t("Not ordered"), UNREADABLE: t("Unreadable") };
  const lotText = (row: DeliveryLot) => t("Lot: {lot}; best before: {date}; printed quantity: {quantity}", {
    lot: row.lot === "unknown" ? t("unknown") : row.lot,
    date: row.bestBefore === "unknown" ? t("unknown") : row.bestBefore,
    quantity: amount(row.quantity, row.unit),
  });
  const pending = result?.notOrdered.some((line, i) => line.needsApproval && choices[i] === undefined) ?? false;

  async function read(file?: File) {
    if (!file || reading || !allowed) return;
    const turn = ++revision.current;
    setReading(true); setError(null); setResult(null); setChoices({});
    try {
      const answer = await api.readDeliveryNote(order.id, await downscalePhoto(file), session?.role === "chef" ? "chef" : "human");
      if (revision.current === turn) setResult(answer);
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
        <p className="max-w-prose text-sm text-muted-foreground">{t("Nemotron reads the note and compares it with this order. Check every quantity before updating stock.")}</p>
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
          <p className="font-semibold">{label(line.productId)} — {statuses[line.status]}</p>
          <p>{t("Ordered: {ordered}; received: {received}; missing: {missing}", {
            ordered: amount(line.ordered, line.baseUnit), received: amount(line.received, line.baseUnit), missing: amount(line.missing, line.baseUnit),
          })}</p>
          {line.lots.map((row, n) => <p className="text-muted-foreground" key={n}>{lotText(row)}</p>)}
        </li>)}
      </ul>
      {result.notOrdered.map((line, i) => <div key={i} className="space-y-2 rounded border border-warning/40 p-3 text-sm">
        <p className="font-semibold">{label(line.productId)} — {statuses[line.status]}</p>
        <p>{lotText(line)}</p>
        {line.needsApproval ? <fieldset className="space-y-2">
          <legend>{t("Was this substitute received for {product}?", { product: label(line.replaces) })}</legend>
          <div className="flex gap-2">
            <Button type="button" size="sm" variant={choices[i] === true ? "default" : "outline"} aria-pressed={choices[i] === true} onClick={() => setChoices((old) => ({ ...old, [i]: true }))}>{t("Yes, received")}</Button>
            <Button type="button" size="sm" variant={choices[i] === false ? "default" : "outline"} aria-pressed={choices[i] === false} onClick={() => setChoices((old) => ({ ...old, [i]: false }))}>{t("No, not received")}</Button>
          </div>
        </fieldset> : null}
      </div>)}
      <p className="text-sm text-muted-foreground">{t("Nothing has been saved. Substitute choices are not saved approvals. Check allergens before use, then count current stock separately.")}</p>
      {pending ? <><p className="text-sm text-warning">{t("Answer yes or no for each substitute first.")}</p><Button disabled>{t("Update counted stock")}</Button></> :
        <Button asChild><Link to="/stock">{t("Update counted stock")}</Link></Button>}
    </div> : null}
  </section>;
}
