import { useState } from "react";
import { toast } from "sonner";

import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { PhotoMark, ShelfPhotoCount } from "@/components/purchasing/shelf-photo-count";
import { useApi } from "@/api";
import type { StockCount } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { auditActorForRole, useRole } from "@/lib/role";
import { cn } from "@/lib/utils";
import { useAsync } from "@/lib/use-async";
import type { StockItem } from "@/types";

export interface RowDraft {
  /** What the user typed; kept even when the save fails. */
  value: string;
  notCounted: boolean;
}

type Drafts = Record<string, RowDraft>;

function draftFor(drafts: Drafts, productId: string): RowDraft {
  return drafts[productId] ?? { value: "", notCounted: false };
}

/** Accepts plain decimals only: Number("") and Number("0x10") must not slip through. */
function parseCount(value: string): number | null {
  const text = value.trim();
  if (!/^[+-]?(\d+(\.\d*)?|\.\d+)$/.test(text)) return null;
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

/** Why a touched row cannot be saved, or null when it can. */
export function rowError(draft: RowDraft | undefined, t: ReturnType<typeof useT> = (text) => text): string | null {
  if (!draft || draft.notCounted) return null;
  if (draft.value.trim() === "") return t("Enter a count or mark the product as not counted.");
  const number = parseCount(draft.value);
  if (number == null) return t("Enter a number.");
  if (number < 0) return t("A count cannot be negative.");
  return null;
}

type CountsResult = { counts: StockCount[]; invalid: number };

/** Only rows the user touched go to the API, and only once every one of them is valid. */
function touchedCounts(rows: StockItem[], drafts: Drafts): CountsResult {
  const counts: StockCount[] = [];
  let invalid = 0;
  for (const row of rows) {
    const draft = drafts[row.productId];
    if (!draft) continue;
    if (rowError(draft)) {
      invalid += 1;
      continue;
    }
    counts.push({ productId: row.productId, onHand: draft.notCounted ? null : parseCount(draft.value) });
  }
  return { counts, invalid };
}

function OnHand({ item, className }: { item: StockItem; className?: string }) {
  const t = useT();
  if (item.onHand == null) {
    return (
      <span className={cn("font-medium text-warning", className)} title={t("Nobody has counted this product yet")}>
        {t("not counted")}
      </span>
    );
  }
  return (
    <span className={cn("tabular-nums", className)}>
      {item.unit === "PCS" ? `${formatNumber(item.onHand)} pcs` : `${formatNumber(item.onHand)} ${item.unit}`}
    </span>
  );
}

function OnOrder({ item }: { item: StockItem }) {
  const t = useT();
  if (item.onOrder == null) {
    return (
      <span className="font-medium text-warning" title={t("Open orders are not counted in kitchen units yet")}>
        {t("unknown")}
      </span>
    );
  }
  return (
    <>
      {formatNumber(item.onOrder)} {item.unit}
    </>
  );
}

export function StockPage() {
  const t = useT();
  const api = useApi();
  const { role } = useRole();
  const actor = auditActorForRole(role);
  const stock = useAsync(() => api.getStock(), [api]);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  /** Products whose draft came from the shelf photo and was not changed by the person since. */
  const [fromPhoto, setFromPhoto] = useState<ReadonlySet<string>>(new Set());

  const rows = stock.status === "ready" ? stock.data : [];
  const uncounted = rows.filter((row) => row.onHand == null).length;
  const { counts: pending, invalid: invalidCount } = touchedCounts(rows, drafts);
  const canSave = pending.length > 0 && invalidCount === 0 && !saving;

  function updateDraft(productId: string, change: Partial<RowDraft>) {
    setDrafts((current) => {
      const next = { ...draftFor(current, productId), ...change };
      if (next.value.trim() === "" && !next.notCounted) {
        // An emptied row goes back to untouched, so it does not block Save for the others.
        const { [productId]: _cleared, ...rest } = current;
        return rest;
      }
      return { ...current, [productId]: next };
    });
    setFromPhoto((ids) => (ids.has(productId) ? new Set([...ids].filter((id) => id !== productId)) : ids));
    setSaveError(null);
  }

  /** Counts read from a shelf photo become drafts to check. Nothing is saved here. */
  function fillFromPhoto(counts: Record<string, number>) {
    const read = Object.entries(counts).map(([id, count]) => [id, String(Math.round(count * 1000) / 1000)] as const);
    setDrafts((current) => ({
      ...current,
      ...Object.fromEntries(read.map(([id, value]) => [id, { value, notCounted: false }])),
    }));
    // Keep the mark on drafts an earlier, unsaved photo filled: they are still unchecked model counts.
    setFromPhoto((ids) => new Set([...ids, ...read.map(([id]) => id)]));
    setSaveError(null);
  }

  async function saveCounts() {
    if (pending.length === 0 || invalidCount > 0 || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      await api.submitStockCount(pending, actor);
      setDrafts({});
      setFromPhoto(new Set());
      stock.reload();
      toast.success(t("Count saved"), { testId: "stock-count-saved-toast" });
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell activeId="stock">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">{t("Stock count")}</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t("What is on hand and on order. A product nobody counted is unknown, not zero.")}
          </p>
        </header>
        {stock.status === "loading" ? <LoadingState label={t("Loading stock")} /> : null}
        {stock.status === "error" ? <ErrorState message={stock.error.message} onRetry={stock.reload} /> : null}
        {stock.status === "ready" && rows.length === 0 ? (
          <EmptyState title={t("No stock to count")}>{t("Products you order will appear here for counting.")}</EmptyState>
        ) : null}
        {stock.status === "ready" && rows.length > 0 ? (
          <div className="space-y-4">
            <p
              className={cn(
                "text-sm tabular-nums",
                uncounted > 0 ? "font-medium text-warning" : "text-muted-foreground",
              )}
            >
              {uncounted > 0
                ? t("{uncounted} of {total} not counted: treated as unknown, not as zero", { uncounted, total: rows.length })
                : t("All {count} products counted", { count: rows.length })}
            </p>

            <ShelfPhotoCount items={rows} actor={actor} disabled={saving} onCounts={fillFromPhoto} />

            <Card>
              <CardContent>
                <div className="hidden md:block">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("Product")}</TableHead>
                        <TableHead>{t("Unit")}</TableHead>
                        <TableHead className="text-right">{t("On hand")}</TableHead>
                        <TableHead className="text-right">{t("On order")}</TableHead>
                        <TableHead>{t("Last delivery")}</TableHead>
                        <TableHead>{t("Counted at")}</TableHead>
                        <TableHead>{t("Count")}</TableHead>
                        <TableHead>{t("Not counted")}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {rows.map((item) => {
                        const draft = draftFor(drafts, item.productId);
                        const error = rowError(drafts[item.productId], t);
                        const countId = `stock-count-${item.productId}`;
                        const unknownId = `stock-unknown-${item.productId}`;
                        const errorId = `stock-error-${item.productId}`;
                        return (
                          <TableRow key={item.productId}>
                            <TableCell>
                              <div className="font-medium">{item.productName}</div>
                              <div className="text-xs text-muted-foreground">{item.productId}</div>
                            </TableCell>
                            <TableCell>{item.unit}</TableCell>
                            <TableCell className="text-right">
                              <OnHand item={item} />
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              <OnOrder item={item} />
                            </TableCell>
                            <TableCell>{formatDate(item.lastDelivery)}</TableCell>
                            <TableCell>{formatDateTime(item.countedAt)}</TableCell>
                            <TableCell>
                              <label className="flex items-center gap-2 text-xs font-medium" htmlFor={countId}>
                                {t("Count")}
                                <Input
                                  id={countId}
                                  type="text"
                                  inputMode="decimal"
                                  autoComplete="off"
                                  className="h-8 w-24"
                                  aria-label={t("{product} count in {unit}", { product: item.productName, unit: item.unit })}
                                  aria-invalid={error != null}
                                  aria-describedby={error ? errorId : undefined}
                                  value={draft.notCounted ? "" : draft.value}
                                  disabled={draft.notCounted || saving}
                                  onChange={(event) =>
                                    updateDraft(item.productId, { value: event.currentTarget.value })
                                  }
                                />
                              </label>
                              {fromPhoto.has(item.productId) ? <PhotoMark /> : null}
                              {error ? (
                                <p id={errorId} role="alert" className="mt-1 text-xs text-destructive">
                                  {error}
                                </p>
                              ) : null}
                            </TableCell>
                            <TableCell>
                              <span className="flex items-center gap-2">
                                <Checkbox
                                  id={unknownId}
                                  aria-label={t("{product} not counted", { product: item.productName })}
                                  checked={draft.notCounted}
                                  disabled={saving}
                                  onCheckedChange={(checked) =>
                                    updateDraft(item.productId, { notCounted: checked === true })
                                  }
                                />
                                <label htmlFor={unknownId} className="text-sm">
                                  {t("Not counted")}
                                </label>
                              </span>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>

                <ul className="divide-y md:hidden">
                  {rows.map((item) => {
                    const draft = draftFor(drafts, item.productId);
                    const error = rowError(drafts[item.productId], t);
                    const countId = `stock-count-m-${item.productId}`;
                    const unknownId = `stock-unknown-m-${item.productId}`;
                    const errorId = `stock-error-m-${item.productId}`;
                    return (
                      <li key={item.productId} className="space-y-3 py-3">
                        <div>
                          <div className="font-medium">{item.productName}</div>
                          <div className="text-xs text-muted-foreground">
                            {item.productId} · {item.unit}
                          </div>
                        </div>
                        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                          <dt className="text-muted-foreground">{t("On hand")}</dt>
                          <dd className="text-right">
                            <OnHand item={item} />
                          </dd>
                          <dt className="text-muted-foreground">{t("On order")}</dt>
                          <dd className="text-right tabular-nums">
                            <OnOrder item={item} />
                          </dd>
                          <dt className="text-muted-foreground">{t("Last delivery")}</dt>
                          <dd className="text-right">{formatDate(item.lastDelivery)}</dd>
                          <dt className="text-muted-foreground">{t("Counted at")}</dt>
                          <dd className="text-right">{formatDateTime(item.countedAt)}</dd>
                        </dl>
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                          <label className="flex items-center gap-2 text-sm font-medium" htmlFor={countId}>
                            {t("Count")}
                            <Input
                              id={countId}
                              type="text"
                              inputMode="decimal"
                              autoComplete="off"
                              className="h-8 w-24"
                              aria-label={t("{product} count in {unit}", { product: item.productName, unit: item.unit })}
                              aria-invalid={error != null}
                              aria-describedby={error ? errorId : undefined}
                              value={draft.notCounted ? "" : draft.value}
                              disabled={draft.notCounted || saving}
                              onChange={(event) => updateDraft(item.productId, { value: event.currentTarget.value })}
                            />
                          </label>
                          <span className="flex items-center gap-2">
                            <Checkbox
                              id={unknownId}
                              aria-label={t("{product} not counted", { product: item.productName })}
                              checked={draft.notCounted}
                              disabled={saving}
                              onCheckedChange={(checked) =>
                                updateDraft(item.productId, { notCounted: checked === true })
                              }
                            />
                            <label htmlFor={unknownId} className="text-sm">
                              {t("Not counted")}
                            </label>
                          </span>
                        </div>
                        {fromPhoto.has(item.productId) ? <PhotoMark /> : null}
                        {error ? (
                          <p id={errorId} role="alert" className="text-xs text-destructive">
                            {error}
                          </p>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              </CardContent>
            </Card>

            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={saveCounts} disabled={!canSave} aria-busy={saving || undefined}>
                {saving ? t("Saving count") : t("Save count")}
              </Button>
              {pending.length === 0 && invalidCount === 0 ? (
                <p className="text-sm text-muted-foreground">{t("Enter a count or mark a product as not counted.")}</p>
              ) : null}
              {invalidCount > 0 ? (
                <p className="text-sm font-medium text-destructive">
                  {invalidCount === 1
                    ? t("Fix the count marked below before saving.")
                    : t("Fix the {count} counts marked below before saving.", { count: invalidCount })}
                </p>
              ) : null}
            </div>
            {saveError ? (
              <p role="alert" className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
                {saveError}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
