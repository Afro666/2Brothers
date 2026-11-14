import { Link } from "@tanstack/react-router";

import { useApi } from "@/api";
import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { StatusBadge } from "@/components/purchasing/status-badge";
import { UrgencyBadge } from "@/components/purchasing/urgency-badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatDate, formatEur } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useAsync } from "@/lib/use-async";

export function OrdersPage() {
  const t = useT();
  const api = useApi();
  const state = useAsync(() => api.listOrders());

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
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold">{order.id}</span>
                        <StatusBadge status={order.status} />
                        <UrgencyBadge urgency={order.urgency} />
                      </div>
                      <p className="text-sm tabular-nums text-muted-foreground">
                        {t("Delivery {date} · {amount} incl VAT", {
                          date: t(formatDate(order.deliveryDate)),
                          amount: formatEur(order.totalInclVat),
                        })}
                      </p>
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
