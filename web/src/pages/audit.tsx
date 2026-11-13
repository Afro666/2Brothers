import { useState } from "react";

import { useApi } from "@/api";
import { ACTOR_LABEL, AuditTimeline, KIND_META } from "@/components/purchasing/audit-timeline";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAsync } from "@/lib/use-async";
import type { AuditEvent, AuditKind } from "@/types";
import { AppShell } from "@/components/purchasing/app-shell";

export function AuditPage() {
  const api = useApi();
  const state = useAsync(() => api.listAudit());
  const [order, setOrder] = useState("all");
  const [kind, setKind] = useState("all");
  const [actor, setActor] = useState("all");

  const events = state.status === "ready" ? state.data : [];
  const orders = [...new Set(events.flatMap((event) => (event.orderId ? [event.orderId] : [])))];
  const filtered = events.filter(
    (event) =>
      (order === "all" || event.orderId === order) &&
      (kind === "all" || event.kind === kind) &&
      (actor === "all" || event.actor === actor),
  );
  function clearFilters() {
    setOrder("all");
    setKind("all");
    setActor("all");
  }

  return (
    <AppShell activeId="audit">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">Audit log</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            Every step the Buyer, the gateway and people took, with who did it and why.
          </p>
        </header>
        {state.status === "loading" ? <LoadingState /> : null}
        {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
        {state.status === "ready" ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="grid gap-1 text-sm font-medium" htmlFor="audit-order">
                Order
                <Select value={order} onValueChange={setOrder}>
                  <SelectTrigger id="audit-order" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All orders</SelectItem>
                    {orders.map((id) => (
                      <SelectItem key={id} value={id}>
                        {id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <label className="grid gap-1 text-sm font-medium" htmlFor="audit-kind">
                Kind
                <Select value={kind} onValueChange={setKind}>
                  <SelectTrigger id="audit-kind" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All kinds</SelectItem>
                    {(Object.keys(KIND_META) as AuditKind[]).map((value) => (
                      <SelectItem key={value} value={value}>
                        {KIND_META[value].label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <label className="grid gap-1 text-sm font-medium" htmlFor="audit-actor">
                Actor
                <Select value={actor} onValueChange={setActor}>
                  <SelectTrigger id="audit-actor" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All actors</SelectItem>
                    {(Object.keys(ACTOR_LABEL) as AuditEvent["actor"][]).map((value) => (
                      <SelectItem key={value} value={value}>
                        {ACTOR_LABEL[value]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
            </div>
            <p className="text-sm tabular-nums text-muted-foreground" aria-live="polite">
              {filtered.length} {filtered.length === 1 ? "step" : "steps"}
            </p>
            {events.length === 0 ? (
              <EmptyState title="No audit steps yet">Recorded events will appear here.</EmptyState>
            ) : filtered.length === 0 ? (
              <EmptyState title="No audit steps match these filters">
                <Button className="mt-3" variant="outline" onClick={clearFilters}>
                  Clear filters
                </Button>
              </EmptyState>
            ) : (
              <Card>
                <CardContent>
                  <AuditTimeline events={filtered} />
                </CardContent>
              </Card>
            )}
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
