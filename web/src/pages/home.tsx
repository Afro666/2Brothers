import { useMemo } from "react";
import { Link, useRouterState } from "@tanstack/react-router";

import { useApi } from "@/api";
import { AppShell } from "@/components/purchasing/app-shell";
import { Button } from "@/components/ui/button";
import { useRole } from "@/lib/role";
import type { Api } from "@/api/types";

import { ApprovalTile, AuditTile, CutoffTile, StockTile } from "@/pages/home/kitchen";
import { KitchensTile, ShortageTile, useSupplierDemand } from "@/pages/home/valio";
import { DriftTile, SupplierDriftTile } from "@/pages/home/drift";

function dashboardNow(search: string): Date {
  const requested = new URLSearchParams(search).get("now");
  if (requested) {
    const parsed = new Date(requested);
    if (!Number.isNaN(parsed.getTime())) return parsed;
  }
  return new Date();
}

export function HomePage() {
  const api = useApi();
  const { side } = useRole();
  const search = useRouterState({ select: (state) => state.location.searchStr });
  const now = useMemo(() => dashboardNow(search), [search]);

  return (
    <AppShell activeId="home">
      <div className="mx-auto max-w-6xl space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="page-title">Kitchen Buyer</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {side === "kitchen" ? "What needs you today." : "Where demand may outrun supply."}
            </p>
          </div>
          {side === "kitchen" ? (
            <Button asChild>
              <Link to="/requests">Request an order</Link>
            </Button>
          ) : null}
        </header>
        <div className="grid gap-4 md:grid-cols-2">
          {side === "kitchen" ? <KitchenDashboard api={api} now={now} /> : <ValioDashboard api={api} now={now} />}
        </div>
      </div>
    </AppShell>
  );
}

function KitchenDashboard({ api, now }: { api: Api; now: Date }) {
  return (
    <>
      <ApprovalTile api={api} />
      <CutoffTile api={api} now={now} />
      <StockTile api={api} now={now} />
      <DriftTile api={api} />
      <AuditTile api={api} />
    </>
  );
}

function ValioDashboard({ api, now }: { api: Api; now: Date }) {
  const supplierDemand = useSupplierDemand(api, now);
  return (
    <>
      <ShortageTile state={supplierDemand} now={now} />
      <KitchensTile state={supplierDemand} />
      <SupplierDriftTile api={api} />
    </>
  );
}
