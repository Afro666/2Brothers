import { useParams } from "@tanstack/react-router";

import { useApi } from "@/api";
import { AppShell } from "@/components/purchasing/app-shell";
import { AuditTimeline } from "@/components/purchasing/audit-timeline";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { MovProgress } from "@/components/purchasing/mov-progress";
import { OrderLinesTable } from "@/components/purchasing/order-lines-table";
import { StatusBadge } from "@/components/purchasing/status-badge";
import { UrgencyBadge } from "@/components/purchasing/urgency-badge";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatDate, formatEur } from "@/lib/format";
import { useAsync } from "@/lib/use-async";

function OrderHistory({ orderId }: { orderId: string }) {
  const api = useApi();
  const state = useAsync(() => api.listAudit({ orderId }), [api, orderId]);

  if (state.status === "loading") return <LoadingState label="Loading order history" />;
  if (state.status === "error") return <ErrorState message={state.error.message} onRetry={state.reload} />;
  if (state.data.length === 0) return <EmptyState title="No history yet">Order history will appear here.</EmptyState>;
  return <AuditTimeline events={state.data} />;
}

export function OrderDetailPage() {
  const { orderId } = useParams({ from: "/orders/$orderId" });
  const api = useApi();
  const state = useAsync(() => api.getOrder(orderId), [api, orderId]);

  return (
    <AppShell activeId="orders">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">Order {orderId}</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            The lines, the totals and every step taken for this order.
          </p>
        </header>
        {state.status === "loading" ? <LoadingState /> : null}
        {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
        {state.status === "ready" ? (
          <Card>
            <div className="space-y-4 px-6">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-semibold">{state.data.id}</h2>
                <StatusBadge status={state.data.status} />
                <UrgencyBadge urgency={state.data.urgency} />
              </div>
              <dl className="grid gap-3 text-sm tabular-nums sm:grid-cols-3">
                <div>
                  <dt className="text-muted-foreground">Delivery</dt>
                  <dd>{formatDate(state.data.deliveryDate)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Total ex VAT</dt>
                  <dd>{formatEur(state.data.totalExVat)}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Total incl VAT</dt>
                  <dd>{formatEur(state.data.totalInclVat)}</dd>
                </div>
              </dl>
            </div>
            <CardContent>
              <Tabs defaultValue="lines">
                <TabsList>
                  <TabsTrigger value="lines">Lines</TabsTrigger>
                  <TabsTrigger value="history">History</TabsTrigger>
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
        ) : null}
      </div>
    </AppShell>
  );
}
