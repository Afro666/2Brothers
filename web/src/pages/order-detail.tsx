import { useParams } from "@tanstack/react-router";
import { toast } from "sonner";

import { useApi } from "@/api";
import { AppShell } from "@/components/purchasing/app-shell";
import { AuditTimeline } from "@/components/purchasing/audit-timeline";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { MovProgress } from "@/components/purchasing/mov-progress";
import { OrderLinesTable } from "@/components/purchasing/order-lines-table";
import { DeliveryNotePhoto } from "@/components/purchasing/delivery-note-photo";
import { LabelPhotoCheck } from "@/components/purchasing/label-photo-check";
import { OrderResolutionPanel } from "@/components/purchasing/order-resolution-panel";
import { StatusBadge } from "@/components/purchasing/status-badge";
import { UrgencyBadge } from "@/components/purchasing/urgency-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatDate, formatDateTime, formatEur, shortOrderId } from "@/lib/format";
import { getLanguage, translate, useT } from "@/lib/i18n";
import { inclVatOf, inclVatText } from "@/lib/vat";
import { placedStatuses } from "@/lib/order-status";
import { orderTitle } from "@/lib/order-title";
import { useAsync } from "@/lib/use-async";
import type { Order, OrderReceipt } from "@/types";
import { supplierName } from "@/lib/supplier-name";

function OrderHistory({ orderId }: { orderId: string }) {
  const t = useT();
  const api = useApi();
  const state = useAsync(() => api.listAudit({ orderId }), [api, orderId]);

  if (state.status === "loading") return <LoadingState label={t("Loading order history")} />;
  if (state.status === "error") return <ErrorState message={state.error.message} onRetry={state.reload} />;
  if (state.data.length === 0) return <EmptyState title={t("No history yet")}>{t("Order history will appear here.")}</EmptyState>;
  return <AuditTimeline events={state.data} />;
}

async function copyReceipt(jws: string) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(jws);
      toast.success(translate(getLanguage(), "Receipt copied"));
      return;
    }
  } catch {}
  toast.error(translate(getLanguage(), "Copy failed. Select the receipt text and copy it."));
}

/** The signed receipt: claims decoded for display only. Anyone checks the signature with the public key. */
function SignedReceipt({ receipt, placedBy }: { receipt?: OrderReceipt | null; placedBy?: Order["placedBy"] }) {
  const t = useT();
  if (receipt === undefined) return null;
  return (
    <section aria-labelledby="receipt-heading" className="space-y-3 border-t border-dashed border-input pt-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 id="receipt-heading" className="text-base font-semibold">
          {t("Signed receipt")}
        </h3>
        {receipt ? <span className="stamp stamp-mark text-sm text-success">{t("Signed")}</span> : null}
      </div>
      {receipt ? (
        <>
          <p className="text-sm text-muted-foreground">{t("Signed by the gateway. Anyone can check it with the public key.")}</p>
          <dl className="grid gap-3 text-sm tabular-nums sm:grid-cols-2">
            <div>
              <dt className="label-caps">{t("Approved by")}</dt>
              <dd className="break-words">
                {receipt.approvedBy === "human" ? t("a person") : (receipt.approvedBy ?? t("unknown"))}
              </dd>
            </div>
            <div>
              <dt className="label-caps">{t("Signed at")}</dt>
              <dd>{t(formatDateTime(receipt.signedAt))}</dd>
            </div>
            <div>
              <dt className="label-caps">{t("Signed total")}</dt>
              <dd className="font-mono">{t(formatEur(receipt.total))}</dd>
            </div>
            <div>
              <dt className="label-caps">{t("Supplier")}</dt>
              <dd className="break-words">
                {receipt.supplierOutcome === "NOT_SENT"
                  ? t("Nothing sent to the supplier yet")
                  : t(receipt.supplierOutcome ?? "unknown")}
              </dd>
              {receipt.supplierNote ? (
                <dd className="mt-1 break-words text-xs text-muted-foreground">{receipt.supplierNote}</dd>
              ) : null}
            </div>
          </dl>
          <Button type="button" variant="outline" size="sm" onClick={() => void copyReceipt(receipt.jws)}>
            {t("Copy receipt")}
          </Button>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          {placedBy === "demo-seed"
            ? t("Placed by the demo seed for the delivery demo. No person approved it, so it has no signed receipt.")
            : t("No signed receipt for this order")}
        </p>
      )}
    </section>
  );
}

function OrderDocket({ order, supplierNames }: { order: Order; supplierNames: Map<string, string> }) {
  const t = useT();
  const title = orderTitle(order, t);
  const suppliers = Array.from(
    new Set([
      ...order.lines.map((line) => line.product.vendorName).filter((name) => name.length > 0),
      ...order.supplierMustConfirm
        .map((supplierId) => ({ supplierId, name: supplierName(supplierId, supplierNames) }))
        .filter(({ supplierId, name }) => name !== supplierId)
        .map(({ name }) => name),
    ]),
  );
  return (
    <Tabs defaultValue="lines">
      <TabsList>
        <TabsTrigger value="lines">{t("Lines")}</TabsTrigger>
        <TabsTrigger value="history">{t("History")}</TabsTrigger>
      </TabsList>
      <TabsContent value="lines">
        <Card className="docket mx-auto w-full max-w-[34rem] gap-0 py-0">
          <div className="space-y-5 p-4 sm:p-6">
            <header className="space-y-2">
              <p className="label-caps">{t("Kitchen Buyer")}</p>
              {suppliers.length > 0 ? <p className="text-sm text-muted-foreground">{suppliers.join(" · ")}</p> : null}
              <h2 className="text-[19px] leading-[25px] font-[650] [overflow-wrap:anywhere]">{title}</h2>
              <p className="text-sm">
                <span className="label-caps mr-2">{t("Delivery")}</span>
                {order.withoutProposal && order.deliveryDate === null ? t("not recorded") : t(formatDate(order.deliveryDate))}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <code className="max-w-full font-mono text-xs break-all select-text text-muted-foreground" title={order.id}>
                  {shortOrderId(order.id)}
                </code>
                <StatusBadge status={order.status} notSent={order.receipt?.supplierOutcome === "NOT_SENT"} />
                {placedStatuses.has(order.status) ? null : <UrgencyBadge urgency={order.urgency} />}
              </div>
              {order.supplierOrderRef ? (
                <p className="text-sm [overflow-wrap:anywhere]">
                  <span className="label-caps mr-2">{t("Supplier order reference")}</span>
                  <span className="font-mono text-xs">{order.supplierOrderRef}</span>
                </p>
              ) : null}
            </header>
            <section aria-labelledby="order-lines-heading" className="space-y-3 border-t border-dashed border-input pt-4">
              <h3 id="order-lines-heading" className="label-caps">
                {t("Lines")}
              </h3>
              <OrderLinesTable lines={order.lines} now={new Date()} variant="receipt" offerDetails={!order.withoutProposal} />
              {order.withoutProposal ? (
                <p className="text-xs text-muted-foreground">
                  {t("This order was recorded without its proposal, so the offer details are not shown.")}
                </p>
              ) : null}
            </section>
            <dl className="space-y-2 border-t border-dashed border-input pt-4 text-sm">
              <div className="flex items-baseline justify-between gap-4">
                <dt className="text-muted-foreground">{t("Total ex VAT")}</dt>
                <dd className="text-right font-mono tabular-nums">{t(formatEur(order.totalExVat))}</dd>
              </div>
              {order.vat !== null || order.withoutProposal ? (
                <div className="flex items-baseline justify-between gap-4">
                  <dt className="text-muted-foreground">{t("VAT")}</dt>
                  <dd className="text-right font-mono tabular-nums">
                    {order.vat === null ? t("unknown") : t(formatEur(order.vat))}
                  </dd>
                </div>
              ) : null}
              {order.deliveryFee !== null && order.deliveryFee > 0 ? (
                <div className="flex items-baseline justify-between gap-4">
                  <dt className="text-muted-foreground">{t("Delivery fee")}</dt>
                  <dd className="text-right font-mono tabular-nums">{t(formatEur(order.deliveryFee))}</dd>
                </div>
              ) : null}
              <div className="flex items-baseline justify-between gap-4 border-t border-dashed border-input pt-3 text-base font-semibold">
                <dt>{t("Total incl VAT")}</dt>
                <dd className="text-right font-mono text-lg tabular-nums">
                  {/* docs/contract.md: with a VAT unknown, `expected_total` is not a total incl VAT. */}
                  {order.withoutProposal && order.vat === null && order.inclVat === undefined
                    ? t("unknown")
                    : inclVatOf(order) !== null
                      ? t(formatEur(inclVatOf(order)))
                      : inclVatText(order, t, formatEur)}
                </dd>
              </div>
            </dl>
            <MovProgress mov={order.mov} />
            <SignedReceipt receipt={order.receipt} placedBy={order.placedBy} />
          </div>
        </Card>
      </TabsContent>
      <TabsContent value="history">
        <div className="mx-auto w-full max-w-[34rem]">
          <OrderHistory orderId={order.id} />
        </div>
      </TabsContent>
    </Tabs>
  );
}

export function OrderDetailPage() {
  const t = useT();
  const { orderId } = useParams({ from: "/orders/$orderId" });
  const api = useApi();
  const state = useAsync(() => api.getOrder(orderId), [api, orderId]);
  const suppliers = useAsync(() => api.listSuppliers(), [api]);
  const supplierNames = new Map(
    suppliers.status === "ready" ? suppliers.data.map((supplier) => [supplier.id, supplier.name]) : [],
  );

  return (
    <AppShell activeId="orders">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="page-title [overflow-wrap:anywhere]">
            {state.status === "ready" ? orderTitle(state.data, t) : t("Order")}
          </h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t("The lines, the totals and every step taken for this order.")}
          </p>
        </header>
        {state.status === "loading" ? <LoadingState /> : null}
        {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
        {state.status === "ready" ? (
          <>
            {state.data.supplierMustConfirm.length > 0 ? (
              <div className="space-y-2 rounded-md border border-warning/40 bg-warning-surface p-4 text-warning">
                {state.data.supplierMustConfirm.map((supplierId) => (
                  <p key={supplierId} className="text-sm font-medium">
                    {t("Waiting for {supplier} to confirm. Call or e-mail them: this order was sent without a stock confirmation.", {
                      supplier: supplierName(supplierId, supplierNames),
                    })}
                  </p>
                ))}
              </div>
            ) : null}
            {state.data.status === "UNCONFIRMED" || state.data.status === "SENT_READ_FAILED" ? (
              <OrderResolutionPanel order={state.data} onChanged={state.reload} />
            ) : null}
            <OrderDocket order={state.data} supplierNames={supplierNames} />
            {state.data.status === "PLACED" ? <DeliveryNotePhoto key={state.data.id} order={state.data} /> : null}
            {state.data.status === "PLACED" ? <LabelPhotoCheck key={`label-${state.data.id}`} order={state.data} /> : null}
          </>
        ) : null}
      </div>
    </AppShell>
  );
}
