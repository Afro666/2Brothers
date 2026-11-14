import { Link } from "@tanstack/react-router";
import { useState } from "react";

import type { ChefProposal } from "@/api";
import { useApi } from "@/api";
import { AppShell } from "@/components/purchasing/app-shell";
import { ChefRequestBox } from "@/components/purchasing/chef-request-box";
import { EmptyState } from "@/components/purchasing/empty-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { MovProgress } from "@/components/purchasing/mov-progress";
import { OfferCompare } from "@/components/purchasing/offer-compare";
import { OrderLinesTable } from "@/components/purchasing/order-lines-table";
import { StatusBadge } from "@/components/purchasing/status-badge";
import { UrgencyBadge } from "@/components/purchasing/urgency-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate, formatEur } from "@/lib/format";
import type { ChefRequest } from "@/types";
import { LiveBuyerRequests } from "@/pages/live-buyer";

type ProposalState =
  { status: "idle" } | { status: "loading" } | { status: "ready"; request: ChefRequest; proposal: ChefProposal };

export function RequestsPage() {
  return import.meta.env.VITE_LIVE_BUYER === "true" ? <LiveBuyerRequests /> : <DemoRequestsPage />;
}

function DemoRequestsPage() {
  const api = useApi();
  const [state, setState] = useState<ProposalState>({ status: "idle" });
  const [preferred, setPreferred] = useState<string | null>(null);

  // A failure is rethrown so ChefRequestBox shows it inline and keeps the form filled.
  async function submit(request: ChefRequest) {
    setState({ status: "loading" });
    try {
      const proposal = await api.submitChefRequest(request);
      setPreferred(null);
      setState({ status: "ready", request, proposal });
    } catch (error) {
      setState({ status: "idle" });
      throw error;
    }
  }

  return (
    <AppShell activeId="requests">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-[28px] leading-8 font-bold tracking-[-0.015em]">Request an order</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            Say what the kitchen needs. The Buyer agent proposes an order, and a person approves it before it is sent.
          </p>
        </header>

        <Card>
          <CardContent>
            <ChefRequestBox onSubmit={submit} />
          </CardContent>
        </Card>

        {state.status === "idle" ? (
          <EmptyState title="No request yet">
            Tell the agent what the kitchen needs to start the first request.
          </EmptyState>
        ) : null}

        {state.status === "loading" ? (
          <div className="space-y-3">
            <div className="print-bar" aria-hidden="true" />
            <LoadingState label="Preparing the proposal" />
          </div>
        ) : null}

        {state.status === "ready" ? (
          <Proposal request={state.request} proposal={state.proposal} preferred={preferred} onChoose={setPreferred} />
        ) : null}
      </div>
    </AppShell>
  );
}

function Proposal({
  request,
  proposal,
  preferred,
  onChoose,
}: {
  request: ChefRequest;
  proposal: ChefProposal;
  preferred: string | null;
  onChoose: (productName: string) => void;
}) {
  const { order, substitutes, approval } = proposal;
  return (
    <section aria-label="Proposal" className="space-y-6">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Proposal for "{request.text}"</h2>
        <p className="text-sm tabular-nums text-muted-foreground">
          Needed by {formatDate(request.deliveryDate)}
          {request.covers == null ? null : ` · ${request.covers} covers`}
        </p>
      </div>

      <Card className="docket gap-4 p-4 sm:p-5">
        <CardHeader className="px-0">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{order.id}</CardTitle>
            <StatusBadge status={order.status} />
            <UrgencyBadge urgency={order.urgency} />
          </div>
          <p className="text-sm tabular-nums text-muted-foreground">
            Delivery {formatDate(order.deliveryDate)} · {formatEur(order.totalExVat)} ex VAT ·{" "}
            {formatEur(order.totalInclVat)} incl VAT
          </p>
        </CardHeader>
        <CardContent className="space-y-6 px-0">
          <OrderLinesTable lines={order.lines} now={new Date()} />
          <MovProgress mov={order.mov} />
        </CardContent>
      </Card>

      {substitutes.length > 0 ? (
        <div className="space-y-3">
          <h3 className="text-base font-semibold">Other options</h3>
          <OfferCompare
            options={substitutes}
            now={new Date()}
            onChoose={(option) => onChoose(option.product.names.en)}
          />
          {preferred ? (
            <p role="status" className="text-sm">
              Noted: you prefer {preferred}. This is not applied to the order yet; tell the approver, or ask the Buyer
              again.
            </p>
          ) : null}
        </div>
      ) : null}

      {approval ? (
        <Alert>
          <AlertTitle>Waiting for a person to approve</AlertTitle>
          <AlertDescription>
            <p>
              This order is not placed yet: a human must approve it first.{" "}
              <Link to="/approvals" className="font-medium text-primary underline underline-offset-4">
                Review it under To approve
              </Link>
              .
            </p>
          </AlertDescription>
        </Alert>
      ) : null}
    </section>
  );
}
