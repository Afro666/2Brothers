import { useSearch } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { useApi } from "@/api";
import { ACTOR_LABEL, AuditTimeline, KIND_META } from "@/components/purchasing/audit-timeline";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAsync } from "@/lib/use-async";
import { useT } from "@/lib/i18n";
import type { AuditEvent, AuditKind } from "@/types";
import { AppShell } from "@/components/purchasing/app-shell";

export function AuditPage() {
  const t = useT();
  const api = useApi();
  const state = useAsync(() => api.listAudit());
  const [order, setOrder] = useState("all");
  // `/audit?kind=search` chooses that kind (the Permissions page links here). Follows later
  // `?kind=` changes too (another link, back/forward) without remounting; unknown kinds mean "all".
  const linkedKind = (useSearch({ strict: false }) as { kind?: unknown }).kind;
  const validKind = typeof linkedKind === "string" && Object.hasOwn(KIND_META, linkedKind) ? linkedKind : "all";
  const [kind, setKind] = useState(validKind);
  useEffect(() => setKind(validKind), [validKind]);
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
          <h1 className="page-title">{t("Activity log")}</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t("Every step the Buyer, the gateway and people took, with who did it and why.")}
          </p>
        </header>
        {state.status === "loading" ? <LoadingState /> : null}
        {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
        {state.status === "ready" ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="label-caps grid gap-1" htmlFor="audit-order">
                {t("Order")}
                <Select value={order} onValueChange={setOrder}>
                  <SelectTrigger id="audit-order" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t("All orders")}</SelectItem>
                    {orders.map((id) => (
                      <SelectItem key={id} value={id}>
                        {id}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <label className="label-caps grid gap-1" htmlFor="audit-kind">
                {t("Kind")}
                <Select value={kind} onValueChange={setKind}>
                  <SelectTrigger id="audit-kind" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t("All kinds")}</SelectItem>
                    {(Object.keys(KIND_META) as AuditKind[]).map((value) => (
                      <SelectItem key={value} value={value}>
                        {t(KIND_META[value].label)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <label className="label-caps grid gap-1" htmlFor="audit-actor">
                {t("Actor")}
                <Select value={actor} onValueChange={setActor}>
                  <SelectTrigger id="audit-actor" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t("All actors")}</SelectItem>
                    {(Object.keys(ACTOR_LABEL) as AuditEvent["actor"][]).map((value) => (
                      <SelectItem key={value} value={value}>
                        {t(ACTOR_LABEL[value])}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
            </div>
            <p className="font-mono text-xs text-muted-foreground" aria-live="polite">
              {filtered.length === 1
                ? t("{count} step", { count: filtered.length })
                : t("{count} steps", { count: filtered.length })}
            </p>
            {events.length === 0 ? (
              <EmptyState title={t("No audit steps yet")}>{t("Recorded events will appear here.")}</EmptyState>
            ) : filtered.length === 0 ? (
              <EmptyState title={t("No audit steps match these filters")}>
                <Button className="mt-3" variant="outline" onClick={clearFilters}>
                  {t("Clear filters")}
                </Button>
              </EmptyState>
            ) : (
              <AuditTimeline events={filtered} />
            )}
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
