import { Check, Trash2, TriangleAlert } from "lucide-react";
import { useState, type ReactNode } from "react";

import { ProductThumb } from "@/components/purchasing/product-thumb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  formatDate,
  formatDateTime,
  formatEur,
  formatNumber,
  formatOfferStock,
  formatPercent,
  isLater,
  isPassed,
  isStockUnconfirmed,
} from "@/lib/format";
import { useT } from "@/lib/i18n";
import { TONE_CLASSES, type Tone } from "@/lib/tone";
import { cn } from "@/lib/utils";
import type { DeliverySource, OrderLine } from "@/types";

const CHIP = "inline-flex items-center gap-1 rounded-sm border px-1.5 py-px text-xs font-medium whitespace-nowrap";

/** A "why" longer than this folds to two lines with a toggle; shorter ones show in full. */
const WHY_FOLD = 56;

/** The quantity controls of one line, when the proposal can be changed. */
export interface LineEditing {
  busy: boolean;
  value: (line: OrderLine) => string;
  onType: (line: OrderLine, value: string) => void;
  onUpdate: (line: OrderLine) => void;
  onRemove: (line: OrderLine) => void;
  inputId: (line: OrderLine) => string;
  /** #1301: true while the line's Remove waits for its confirm; its quantity is then fixed. */
  removing?: (line: OrderLine) => boolean;
  /** #1301: the id of the line's Remove, so the confirm can give focus back to it. */
  removeId?: (line: OrderLine) => string;
  /** #1301: the reason chips and the Remove confirm under a line, or null. */
  below?: (line: OrderLine) => ReactNode;
}

/** A product that a gateway reason names but that is not a line: the engine left it out. */
export interface LeftOutProduct {
  product: string;
  reason: string;
  /** The reason's untranslated detail sentence ("" when none). */
  detail: string;
}

/** One per-product "What to check" sentence and its detail, both untranslated. */
export interface ProductCheck {
  text: string;
  detail: string;
}

/** A check as the reader's language shows it: sentence, then its detail. */
function checkText({ text, detail }: ProductCheck, t: T): string {
  return detail ? `${t(text)} ${t(detail)}` : t(text);
}

type T = ReturnType<typeof useT>;

function stockState(line: OrderLine, confirmBy: string, t: T): { tone: Tone; text: string } {
  if (line.offer.salesBlock) return { tone: "danger", text: t("Not available") };
  if (isStockUnconfirmed(line.offer)) return { tone: "warning", text: t("{supplier} must confirm", { supplier: confirmBy }) };
  return { tone: "success", text: t(formatOfferStock(line.offer)) };
}

export function StockChip({ line, confirmBy }: { line: OrderLine; confirmBy: string }) {
  const t = useT();
  const state = stockState(line, confirmBy, t);
  return (
    <span data-stock={state.tone} className={cn(CHIP, TONE_CLASSES[state.tone])}>
      {state.text}
    </span>
  );
}

/** One shown delivery value and where it came from (#1453). */
export interface SourcedValue {
  label: string;
  source: DeliverySource | null | undefined;
}

/**
 * One muted "(demo)" for a cell that holds a value the demo invented (#1453): never
 * Valio's or a supplier's number. However many of the cell's values are demo values, the
 * note shows once; its title names which ones.
 */
export function DemoNote({ values }: { values: readonly SourcedValue[] }) {
  const t = useT();
  const demo = values.filter((value) => value.source === "demo").map((value) => value.label);
  if (demo.length === 0) return null;
  const which = t("Demo data: {facts}", { facts: demo.join(", ") });
  return (
    <span data-demo title={which} className="font-normal text-muted-foreground">
      {" "}({t("demo")})
    </span>
  );
}

/** Lead time in days, or null when no source knows it. */
export function leadTimeText(days: number | null | undefined, t: ReturnType<typeof useT>): string | null {
  if (days == null) return null;
  return days === 1 ? t("1 day") : t("{count} days", { count: days });
}

function CutoffText({ line, now }: { line: OrderLine; now: Date }) {
  const t = useT();
  const late = isLater(line.offer.availableDate, line.offer.requestedDate);
  const passed = isPassed(line.offer.closingTime, now);
  const lead = leadTimeText(line.offer.leadTimeDays, t);
  const reliability = line.offer.deliveryReliability;
  const hasFacts = lead != null || reliability != null;
  // Every value this cell shows, with its source: one "(demo)" at the end covers them all.
  const shown: SourcedValue[] = [
    ...(passed ? [] : [{ label: t("Order cut-off"), source: line.offer.cutoffSource }]),
    ...(lead != null ? [{ label: t("Lead time"), source: line.offer.leadTimeSource }] : []),
    ...(reliability != null ? [{ label: t("Delivery reliability"), source: line.offer.reliabilitySource }] : []),
  ];
  return (
    <span className="inline-flex flex-col items-start gap-0.5">
      {passed ? (
        <span data-closed className={cn(CHIP, TONE_CLASSES.danger)}>
          {t("Cut-off passed")}
        </span>
      ) : (
        <span className="text-xs text-muted-foreground tabular-nums">
          <span className="md:sr-only">{t("order by")} </span>
          {t(formatDateTime(line.offer.closingTime))}
          {hasFacts ? null : <DemoNote values={shown} />}
        </span>
      )}
      {hasFacts ? (
        <span className="text-[11px] leading-4 text-muted-foreground tabular-nums">
          {lead != null ? <span title={t("Lead time")}>{lead}</span> : null}
          {lead != null && reliability != null ? " · " : null}
          {reliability != null ? (
            <span title={t("Delivery reliability")}>
              {t("{percent} delivered", { percent: formatPercent(reliability) })}
            </span>
          ) : null}
          <DemoNote values={shown} />
        </span>
      ) : null}
      {late ? (
        <span className="text-xs font-medium text-warning">
          {t("arrives {date}", { date: t(formatDate(line.offer.availableDate)) })}
        </span>
      ) : null}
    </span>
  );
}

function WhyText({ why, product }: { why: string; product: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const long = why.length > WHY_FOLD;
  return (
    <div className="flex items-start gap-1">
      <p title={why} className={cn("min-w-0 text-xs leading-4 text-muted-foreground", !open && "line-clamp-2")}>
        {why}
      </p>
      {long ? (
        <button
          type="button"
          aria-expanded={open}
          aria-label={open ? t("Show less of why for {product}", { product }) : t("Show all of why for {product}", { product })}
          onClick={() => setOpen((shown) => !shown)}
          className="shrink-0 rounded-sm px-1 text-xs font-medium text-foreground underline underline-offset-2 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/70"
        >
          {open ? t("less") : t("more")}
        </button>
      ) : null}
    </div>
  );
}

/**
 * The lines of one proposal as a dense table: one row per product, so a menu plan of
 * 30 lines reads like a purchase order. On a phone each row folds to two lines (name,
 * quantity and total; then stock, cut-off and why) without a sideways scroll. `checks`
 * are the gateway's per-product "What to check" sentences, shown on that product's row.
 */
export function ProposalLines({
  lines,
  now,
  confirmBy,
  checks,
  leftOut = [],
  editing,
}: {
  lines: OrderLine[];
  now: Date;
  /** Who confirms unknown stock ("Valio", or a manual supplier). */
  confirmBy: string;
  checks: ReadonlyMap<string, ProductCheck[]>;
  leftOut?: LeftOutProduct[];
  editing?: LineEditing;
}) {
  const t = useT();
  // One grid for the header and every row, so the columns line up like a table. On a phone
  // each row is two short lines: picture, name, quantity and total; then stock, cut-off, why.
  const columns = editing
    ? "md:grid-cols-[minmax(10rem,1.2fr)_7.25rem_4.25rem_5rem_7.75rem_10rem_minmax(7.5rem,1.4fr)_1.75rem]"
    : "md:grid-cols-[minmax(10rem,1.2fr)_5rem_4.25rem_5rem_7.75rem_10rem_minmax(7.5rem,1.4fr)]";
  const head = "label-caps whitespace-nowrap";
  return (
    <div className="space-y-3">
      <div role="table" aria-label={t("Order lines")} className="text-sm" data-testid="proposal-lines">
        <div role="rowgroup" className="max-md:sr-only">
          <div role="row" className={cn("grid items-end gap-x-2 border-b pb-1.5", columns)}>
            <span role="columnheader" className={head}>{t("Product")}</span>
            <span role="columnheader" className={head}>{t("Qty")}</span>
            <span role="columnheader" className={cn(head, "text-right")}>{t("Price")}</span>
            <span role="columnheader" className={cn(head, "text-right")}>{t("Total")}</span>
            <span role="columnheader" className={head}>{t("Stock")}</span>
            <span role="columnheader" className={head}>{t("Delivery")}</span>
            <span role="columnheader" className={head}>{t("Why this much")}</span>
            {editing ? (
              <span role="columnheader" className="sr-only">
                {t("Remove")}
              </span>
            ) : null}
          </div>
        </div>
        <div role="rowgroup">
          {lines.map((line) => {
            const { product, offer } = line;
            const name = product.names.en || product.id;
            const notes = checks.get(product.id) ?? [];
            const value = editing?.value(line) ?? String(line.quantity);
            const number = Number(value);
            const valid = Number.isInteger(number) && number >= 1;
            const removing = editing?.removing?.(line) ?? false;
            const below = editing?.below?.(line);
            const update = () => {
              if (editing && valid && number !== line.quantity && !editing.busy && !removing) editing.onUpdate(line);
            };
            return (
              <div
                role="row"
                key={product.id}
                data-testid="proposal-line"
                className={cn(
                  "grid grid-cols-[minmax(0,1fr)_7.75rem] items-center gap-x-2 gap-y-1 border-b border-dashed border-input py-1.5 last:border-b-0 md:hover:bg-muted/40",
                  columns,
                )}
              >
                <div role="cell" className="col-start-1 row-start-1 min-w-0 md:col-auto md:row-auto">
                  <div className="flex min-w-0 items-center gap-2">
                    <ProductThumb en={product.names.en} fi={product.names.fi} brand={product.brand} size="sm" />
                    <div className="min-w-0">
                      <div className="line-clamp-2 text-[13px] leading-4 font-medium [overflow-wrap:anywhere]" title={name}>
                        {name}
                      </div>
                      <div className="truncate font-mono text-[11px] leading-4 text-muted-foreground">
                        {product.brand ? <>{product.brand} · </> : null}
                        {product.id}
                      </div>
                    </div>
                  </div>
                  {notes.map((note) => (
                    <div key={`${note.text}-${note.detail}`} className="mt-0.5 flex items-start gap-1 pl-10 text-xs leading-4 text-warning">
                      <TriangleAlert className="mt-px size-3 shrink-0" aria-hidden />
                      <span className="[overflow-wrap:anywhere]">{checkText(note, t)}</span>
                    </div>
                  ))}
                </div>
                <div role="cell" className="col-start-2 row-start-1 justify-self-end md:col-auto md:row-auto md:justify-self-start">
                  {editing ? (
                    <form
                      className="flex items-center gap-1"
                      onSubmit={(event) => {
                        event.preventDefault();
                        update();
                      }}
                    >
                      <label className="sr-only" htmlFor={editing.inputId(line)}>
                        {t("Quantity for {product} ({unit})", { product: name, unit: product.salesUnit })}
                      </label>
                      <Input
                        id={editing.inputId(line)}
                        type="number"
                        min={1}
                        step={1}
                        value={value}
                        disabled={editing.busy || removing}
                        onChange={(event) => editing.onType(line, event.target.value)}
                        className="h-8 w-16 px-1.5 text-right font-mono tabular-nums"
                      />
                      <span className="w-5 font-mono text-[11px] text-muted-foreground">{product.salesUnit}</span>
                      <Button
                        type="submit"
                        size="icon"
                        variant="ghost"
                        className="size-7"
                        disabled={editing.busy || removing || !valid || number === line.quantity}
                        aria-label={t("Update {product}", { product: name })}
                        title={t("Update")}
                      >
                        <Check aria-hidden />
                      </Button>
                    </form>
                  ) : (
                    <span className="font-mono whitespace-nowrap tabular-nums">
                      {formatNumber(line.quantity)} {product.salesUnit}
                    </span>
                  )}
                </div>
                <div role="cell" className="hidden text-right font-mono whitespace-nowrap tabular-nums md:block">
                  {t(formatEur(offer.priceExVat))}
                </div>
                <div role="cell" className="col-start-2 row-start-2 justify-self-end text-right font-mono font-semibold whitespace-nowrap tabular-nums md:col-auto md:row-auto md:justify-self-stretch">
                  <span className="sr-only">{t("Line total ex VAT")}: </span>
                  {t(formatEur(line.lineTotal))}
                </div>
                <div role="cell" className="col-start-1 row-start-2 flex flex-wrap items-center gap-x-2 gap-y-1 md:col-auto md:row-auto">
                  <StockChip line={line} confirmBy={confirmBy} />
                  <span className="md:hidden">
                    <CutoffText line={line} now={now} />
                  </span>
                </div>
                <div role="cell" className="hidden md:block">
                  <CutoffText line={line} now={now} />
                </div>
                {/* With the remove button the why keeps to the first track: sharing one track would add implicit columns. */}
                <div role="cell" className={cn("row-start-3 min-w-0 md:col-auto md:row-auto", editing ? "col-start-1" : "col-span-2")}>
                  <WhyText why={line.why} product={name} />
                </div>
                {editing ? (
                  <div role="cell" className="col-start-2 row-start-3 justify-self-end md:col-auto md:row-auto">
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="size-7 text-muted-foreground hover:text-danger"
                      id={editing.removeId?.(line)}
                      disabled={editing.busy}
                      // A disclosure when Remove asks first: it stays mounted, so focus stays on it.
                      aria-expanded={editing.removing ? removing : undefined}
                      aria-label={t("Remove {product}", { product: name })}
                      title={t("Remove")}
                      onClick={() => editing.onRemove(line)}
                    >
                      <Trash2 aria-hidden />
                    </Button>
                  </div>
                ) : null}
                {below ? (
                  <div role="cell" className="col-span-full pt-1">
                    {below}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
      <p className="text-right font-mono text-[11px] text-muted-foreground">{t("All prices ex VAT")}</p>
      {leftOut.length > 0 ? (
        <section className="space-y-1" aria-label={t("Left out of this order")}>
          <h5 className="label-caps">{t("Left out of this order ({count})", { count: leftOut.length })}</h5>
          <ul className="divide-y divide-dashed divide-input text-xs">
            {leftOut.map((item) => (
              <li key={`${item.product}-${item.reason}-${item.detail}`} className="flex flex-wrap gap-x-2 py-1">
                <span className="font-medium [overflow-wrap:anywhere]">{item.product}</span>
                <span className="text-muted-foreground [overflow-wrap:anywhere]">{checkText({ text: item.reason, detail: item.detail }, t)}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
