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
import { OrderResolutionPanel } from "@/components/purchasing/order-resolution-panel";
import { StatusBadge } from "@/components/purchasing/status-badge";
import { UrgencyBadge } from "@/components/purchasing/urgency-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatDate, formatDateTime, formatEur } from "@/lib/format";
import { getLanguage, translate, useT } from "@/lib/i18n";
import { useAsync } from "@/lib/use-async";
import type { OrderReceipt } from "@/types";

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
function SignedReceipt({ receipt }: { receipt: OrderReceipt | null }) {
  const t = useT();
  return (
    <section aria-labelledby="receipt-heading" className="space-y-2 border-t pt-4">
      <h3 id="receipt-heading" className="text-base font-semibold">
        {t("Signed receipt")}
      </h3>
      {receipt ? (
        <>
          <p className="text-sm text-muted-foreground">{t("Signed by the gateway. Anyone can check it with the public key.")}</p>
          <dl className="grid gap-3 text-sm tabular-nums sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">{t("Approved by")}</dt>
              <dd className="break-words">{receipt.approvedBy ?? t("unknown")}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("Signed at")}</dt>
              <dd>{formatDateTime(receipt.signedAt)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">{t("Signed total")}</dt>
              <dd>{formatEur(receipt.total)}</dd>
            </div>
          </dl>
          <Button type="button" variant="outline" size="sm" onClick={() => void copyReceipt(receipt.jws)}>
            {t("Copy receipt")}
          </Button>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          {t("No signed receipt (this order is from before receipts, or signing was not possible)")}
        </p>
      )}
    </section>
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
          <h1 className="text-2xl font-semibold">{t("Order {id}", { id: orderId })}</h1>
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
                      supplier: supplierNames.get(supplierId) ?? supplierId,
                    })}
                  </p>
                ))}
              </div>
            ) : null}
            {state.data.status === "UNCONFIRMED" || state.data.status === "SENT_READ_FAILED" ? (
              <OrderResolutionPanel order={state.data} onChanged={state.reload} />
            ) : null}
            <Card>
            <div className="space-y-4 px-6">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-semibold">{state.data.id}</h2>
                <StatusBadge status={state.data.status} />
                <UrgencyBadge urgency={state.data.urgency} />
              </div>
              <dl className="grid gap-3 text-sm tabular-nums sm:grid-cols-3">
                <div>
                  <dt className="text-muted-foreground">{t("Delivery")}</dt>
                  <dd>{t(formatDate(state.data.deliveryDate))}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{t("Total ex VAT")}</dt>
                  <dd>{t(formatEur(state.data.totalExVat))}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{t("Total incl VAT")}</dt>
                  <dd>{formatEur(state.data.totalInclVat)}</dd>
                </div>
                {state.data.supplierOrderRef ? (
                  <div className="sm:col-span-3">
                    <dt className="text-muted-foreground">{t("Supplier order reference")}</dt>
                    <dd className="break-all">{state.data.supplierOrderRef}</dd>
                  </div>
                ) : null}
              </dl>
              {state.data.receipt !== undefined ? <SignedReceipt receipt={state.data.receipt} /> : null}
            </div>
            <CardContent>
              <Tabs defaultValue="lines">
                <TabsList>
                  <TabsTrigger value="lines">{t("Lines")}</TabsTrigger>
                  <TabsTrigger value="history">{t("History")}</TabsTrigger>
                </TabsList>
                <TabsContent value="lines" className="space-y-5">
                  <OrderLinesTable lines={state.data.lines} now={new Date()} />
                  <MovProgress mov={state.data.mov} />
                </TabsContent>
                <TabsContent value="history">
                  <OrderHistory orderId={state.data.id} />
                </TabsContent>
              </Tabs>
            </CardContent>
            </Card>
            {state.data.status === "PLACED" ? <DeliveryNotePhoto key={state.data.id} order={state.data} /> : null}
          </>
        ) : null}
      </div>
    </AppShell>
  );
}
