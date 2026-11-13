/**
 * `/kit`: every purchasing component with the milk-case mocks, one screen.
 * Each section says where the component lives in the real app.
 */
import type { ReactNode } from "react";

import { AppShell, NAV_ITEMS } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { ApprovalCard } from "@/components/purchasing/approval-card";
import { AuditTimeline } from "@/components/purchasing/audit-timeline";
import { ChefRequestBox } from "@/components/purchasing/chef-request-box";
import { MandateSummary } from "@/components/purchasing/mandate-summary";
import { MovProgress } from "@/components/purchasing/mov-progress";
import { OfferCompare } from "@/components/purchasing/offer-compare";
import { OrderLinesTable } from "@/components/purchasing/order-lines-table";
import { ProductCard } from "@/components/purchasing/product-card";
import { STATUS_META, StatusBadge } from "@/components/purchasing/status-badge";
import { URGENCY_META, UrgencyBadge } from "@/components/purchasing/urgency-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate, formatEur } from "@/lib/format";
import {
  MOCK_NOW,
  approval,
  auditEvents,
  chefRequest,
  consideredLines,
  mandate,
  orders,
  products,
  substitutes,
} from "@/mocks/milk-case";
import type { Order, OrderStatus, Urgency } from "@/types";

const KIT_NAV = NAV_ITEMS.map((item) => ({
  ...item,
  href: `#${item.id}`,
  count: item.id === "approvals" ? 1 : undefined,
}));

function Section({ id, title, usedIn, children }: { id: string; title: string; usedIn: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="space-y-4 border-t pt-8">
      <div className="space-y-1">
        <h2 id={`${id}-title`} className="text-lg font-semibold">
          {title}
        </h2>
        <p className="text-sm text-muted-foreground">Used in: {usedIn}</p>
      </div>
      {children}
    </section>
  );
}

function OrderHeader({ order }: { order: Order }) {
  return (
    <CardHeader>
      <div className="flex flex-wrap items-center gap-2">
        <CardTitle>{order.id}</CardTitle>
        <StatusBadge status={order.status} />
        <UrgencyBadge urgency={order.urgency} />
      </div>
      <CardDescription>
        Delivery {formatDate(order.deliveryDate)} · {formatEur(order.totalExVat)} ex VAT ·{" "}
        {formatEur(order.totalInclVat)} incl VAT
      </CardDescription>
    </CardHeader>
  );
}

export function KitPage() {
  const now = MOCK_NOW;
  return (
    <AppShell items={KIT_NAV} activeId="requests">
      <div className="mx-auto max-w-6xl space-y-8">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">Component kit</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            The purchasing components with mock data from the milk case: "{chefRequest.text}", asked on Fri 13 Nov
            for delivery on {formatDate(chefRequest.deliveryDate)}. Three of five products missed the order
            cut-off, so the Buyer proposes a split: one part is approved and placed, one part waits for approval.
          </p>
        </header>

        <Section id="requests" title="ChefRequestBox" usedIn="Requests: the chef's free-text ask">
          <Card>
            <CardContent>
              <ChefRequestBox initial={chefRequest} />
            </CardContent>
          </Card>
        </Section>

        <Section id="status" title="StatusBadge" usedIn="Orders, Approvals and the audit log (hover or focus for the meaning)">
          <div className="flex flex-wrap gap-2">
            {(Object.keys(STATUS_META) as OrderStatus[]).map((s) => (
              <StatusBadge key={s} status={s} />
            ))}
          </div>
        </Section>

        <Section id="urgency" title="UrgencyBadge" usedIn="Requests and Orders: sort order, most urgent first">
          <div className="flex flex-wrap gap-2">
            {(Object.keys(URGENCY_META) as Urgency[]).map((u) => (
              <UrgencyBadge key={u} urgency={u} />
            ))}
          </div>
        </Section>

        <Section id="orders" title="OrderLinesTable" usedIn="Orders: order detail, and the approval detail">
          <Card>
            <OrderHeader order={orders.placed} />
            <CardContent>
              <OrderLinesTable lines={orders.placed.lines} now={now} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Every product checked for Monday</CardTitle>
              <CardDescription>Stock sentinels show as unknown; passed cut-offs are red.</CardDescription>
            </CardHeader>
            <CardContent>
              <OrderLinesTable lines={consideredLines} now={now} />
            </CardContent>
          </Card>
        </Section>

        <Section id="mov" title="MovProgress" usedIn="Orders and Approvals: order value against free delivery">
          <Card>
            <CardHeader>
              <CardTitle>{orders.placed.id} alone</CardTitle>
            </CardHeader>
            <CardContent>
              <MovProgress mov={orders.placed.mov} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>
                {orders.placed.id} and {orders.needsApproval.id} on the same delivery
              </CardTitle>
            </CardHeader>
            <CardContent>
              <MovProgress mov={orders.needsApproval.mov} />
            </CardContent>
          </Card>
        </Section>

        <Section id="offers" title="OfferCompare" usedIn="Requests: when the first choice cannot cover the ask">
          <OfferCompare options={substitutes} now={now} onChoose={() => {}} />
        </Section>

        <Section id="catalog" title="ProductCard" usedIn="Catalog, and the product drawer from an order line">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <ProductCard product={products.arlaUht1l} />
            <ProductCard product={products.eilaOrganic1l} />
            <ProductCard product={products.arlaEsl10l} />
          </div>
        </Section>

        <Section id="approvals" title="ApprovalCard" usedIn="Approvals: the human's inbox">
          <div className="max-w-2xl">
            <ApprovalCard request={approval} order={orders.needsApproval} />
          </div>
        </Section>

        <Section id="audit" title="AuditTimeline" usedIn="Audit log, and the history tab of an order">
          <Card>
            <CardContent>
              <AuditTimeline events={auditEvents} />
            </CardContent>
          </Card>
        </Section>

        <Section id="mandate" title="MandateSummary" usedIn="Approvals (why something needs you) and settings">
          <Card>
            <CardContent>
              <MandateSummary mandate={mandate} />
            </CardContent>
          </Card>
        </Section>

        <Section id="states" title="Shared states" usedIn="Every screen while data loads, is empty, or fails">
          <EmptyState title="No requests yet">New requests will appear here.</EmptyState>
          <LoadingState />
          <ErrorState message="Could not load this screen." onRetry={() => {}} />
        </Section>
      </div>
    </AppShell>
  );
}
