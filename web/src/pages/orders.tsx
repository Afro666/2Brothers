import { Link } from "@tanstack/react-router";

import { useApi } from "@/api";
import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { StatusBadge } from "@/components/purchasing/status-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatDate, formatEur, shortOrderId } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { orderTitle } from "@/lib/order-title";
import { useAsync } from "@/lib/use-async";
import { supplierName } from "@/lib/supplier-name";

export function OrdersPage() {
  const t = useT();
  const api = useApi();
  const state = useAsync(() => api.listOrders());
  const suppliers = useAsync(() => api.listSuppliers(), [api]);
  const supplierNames = new Map(
    suppliers.status === "ready" ? suppliers.data.map((supplier) => [supplier.id, supplier.name]) : [],
  );

  return (
    <AppShell activeId="orders">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">{t("Order history")}</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t("Orders a person approved, and where each one stands.")}
          </p>
        </header>
        {state.status === "loading" ? <LoadingState /> : null}
        {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
        {state.status === "ready" && state.data.length === 0 ? (
          <EmptyState title={t("No orders yet")}>{t("Orders will appear here.")}</EmptyState>
        ) : null}
        {state.status === "ready" && state.data.length > 0 ? (
          <ul className="space-y-3">
            {state.data.map((order) => (
              <li key={order.id}>
                <Card>
                  <CardContent>
                    <Link
                      to="/orders/$orderId"
                      params={{ orderId: order.id }}
                      className="block space-y-3 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                        <div className="min-w-0">
                          <span className="block font-semibold [overflow-wrap:anywhere]">{orderTitle(order, t)}</span>
                          <code
                            className="mt-1 block max-w-full font-mono text-xs break-all text-muted-foreground"
                            title={order.id}
                          >
                            {shortOrderId(order.id)}
                          </code>
                        </div>
                        <p className="shrink-0 text-sm tabular-nums text-muted-foreground">
                          {t("Delivery {date} · {amount} incl VAT", {
                            date: t(formatDate(order.deliveryDate)),
                            amount: formatEur(order.totalInclVat),
                          })}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge status={order.status} />
                        {order.supplierMustConfirm.map((supplierId) => (
                          <Badge
                            key={supplierId}
                            variant="outline"
                            className="border-warning/40 bg-warning-surface text-warning"
                          >
                            {t("Call {supplier} to confirm", { supplier: supplierName(supplierId, supplierNames) })}
                          </Badge>
                        ))}
                      </div>
                    </Link>
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </AppShell>
  );
}
