import { ApprovalCard, type ApprovalDecision } from "@/components/purchasing/approval-card";
import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { RecallPanel, type RecallStatus } from "@/components/purchasing/recall-panel";
import { useSearch } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { toast } from "sonner";

import { useApi } from "@/api";
import { ApiError, type Api } from "@/api/types";
import { usePendingApprovals } from "@/lib/pending-approvals";
import { auditActorForRole, useRole } from "@/lib/role";
import { formatEur } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useAsync } from "@/lib/use-async";
import { supplierName } from "@/lib/supplier-name";
import { LiveConnectionLabel, useLiveEvents } from "@/lib/live-events";
import { useSession } from "@/lib/session";
import { closeTelegram, inTelegram } from "@/lib/telegram";
import { inclVatText } from "@/lib/vat";
import { OpenDemoNote } from "@/components/purchasing/open-demo-note";
import type { ApprovalRequest, Order, ProposalChange, RecallList } from "@/types";
import { LiveApprovalsPage } from "@/pages/live-approvals";

interface ApprovalWithOrder {
  approval: ApprovalRequest;
  order: Order | null;
}

async function loadApprovals(api: Api): Promise<ApprovalWithOrder[]> {
  const approvals = await api.listApprovals();
  return Promise.all(
    approvals.map(async (approval) => {
      try {
        return { approval, order: await api.getOrder(approval.orderId) };
      } catch {
        return { approval, order: null };
      }
    }),
  );
}

/** null when this gateway does not serve recalls yet (hidden, never shown as "no recalls"). */
async function loadRecalls(api: Api): Promise<RecallList | null> {
  // In gateway mode an unserved method answers from the mock: sample recalls must never
  // stand in for the real orders' recalls.
  if (!api.listRecalls || (api.live && !api.live.has("listRecalls"))) return null;
  try {
    return await api.listRecalls();
  } catch (error) {
    if (error instanceof ApiError && error.code === "NOT_SERVED") return null;
    throw error;
  }
}

export function ApprovalsPage() {
  const api = useApi();
  // In gateway mode the Api itself reads and decides the real proposals, so the inbox below is the live one.
  // The standalone live page is for a build whose Api is still the mock.
  return import.meta.env.VITE_LIVE_BUYER === "true" && !api.live?.has("listApprovals") ? (
    <LiveApprovalsPage />
  ) : (
    <ApiApprovalsPage />
  );
}

/** Decided cards shown before "Show all decided". */
const DECIDED_SHOWN = 5;

function ApiApprovalsPage() {
  const t = useT();
  const api = useApi();
  const { proposal } = useSearch({ from: "/approvals" });
  const { role } = useRole();
  const { session } = useSession();
  const actor = auditActorForRole(role);
  const approvals = useAsync(() => loadApprovals(api), [api]);
  useLiveEvents(["proposal", "approval"], approvals.reload);
  const { refresh: refreshWaiting } = usePendingApprovals();
  const [editCounts, setEditCounts] = useState<Record<string, number>>({});
  const [allDecided, setAllDecided] = useState(false);
  const recalls = useAsync(() => loadRecalls(api), [api]);
  const closeTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(closeTimer.current), []);
  // Decided here: the toast says so, the "already decided" line is only for a link that was stale.
  const decidedHere = useRef(new Set<string>());

  // An Api that cannot change a proposal shows it read-only (the gateway serves the change, #303).
  const canEdit = !api.live || api.live.has("changeProposal");

  async function approve(decision: ApprovalDecision): Promise<void> {
    try {
      const decided = await api.approve(decision, actor);
      decidedHere.current.add(decision.approvalId);
      const answeredOrder = await api.getOrder(decided.orderId).catch(() => null);
      const waitingFor = answeredOrder?.supplierMustConfirm ?? [];
      if (waitingFor.length > 0) {
        const suppliers = await api.listSuppliers().catch(() => []);
        const supplierNames = new Map(suppliers.map((supplier) => [supplier.id, supplier.name]));
        const supplier = waitingFor.map((supplierId) => supplierName(supplierId, supplierNames)).join(", ");
        toast.success(t("Order placed. Call {supplier} to confirm.", { supplier }), { testId: "approval-toast" });
      } else {
        toast.success(t("Approved: {exVat} ex VAT, {total}. The order may now be sent.", {
          exVat: formatEur(decided.totalExVat),
          total: inclVatText(decided, t, formatEur),
        }), {
          testId: "approval-toast",
        });
      }
      // Inside Telegram the Mini App closes after the person has seen the result.
      if (inTelegram()) {
        window.clearTimeout(closeTimer.current);
        closeTimer.current = window.setTimeout(closeTelegram, 2000);
      }
    } finally {
      // Also after a refusal: when the total moved, the card must show the new one before asking again.
      approvals.reload();
      refreshWaiting();
    }
  }

  async function reject(approvalId: string, reason: string): Promise<void> {
    await api.reject(approvalId, reason, actor);
    decidedHere.current.add(approvalId);
    toast.success(t("Rejected. The reason goes back to the Buyer."), { testId: "approval-toast" });
    approvals.reload();
    refreshWaiting();
  }

  async function change(orderId: string, proposalChange: ProposalChange): Promise<void> {
    try {
      await api.changeProposal(orderId, proposalChange, actor);
      setEditCounts((counts) => ({ ...counts, [orderId]: (counts[orderId] ?? 0) + 1 }));
      toast.success(t("Proposal updated. Check the new total before you approve."));
    } finally {
      // Also after a failure: the gateway may have saved a change whose answer was lost, and the
      // card must show the gateway's basket and total before anyone approves.
      await approvals.reload();
    }
  }

  const pending =
    approvals.status === "ready" ? approvals.data.filter(({ approval }) => approval.status === "PENDING") : [];
  const held =
    approvals.status === "ready"
      ? approvals.data.filter(({ approval }) => approval.status === "BLOCKED_BY_RECALL")
      : [];
  const decided =
    approvals.status === "ready"
      ? approvals.data.filter(
          ({ approval }) => approval.status !== "PENDING" && approval.status !== "BLOCKED_BY_RECALL",
        )
      : [];

  const openOrders = new Set(
    approvals.status === "ready"
      ? approvals.data
          .filter(({ approval }) => approval.status === "PENDING" || approval.status === "BLOCKED_BY_RECALL")
          .map(({ approval }) => approval.orderId)
      : [],
  );
  const recallsFor = (orderId: string) =>
    recalls.status === "ready" ? (recalls.data?.alerts ?? []).filter((alert) => alert.orderId === orderId) : [];
  // An order a recall hits comes first, so nobody scrolls past it.
  const hit = (row: ApprovalWithOrder) => Number(recallsFor(row.approval.orderId).length > 0);
  const recallFirst = [...pending].sort((a, b) => hit(b) - hit(a));
  const linked =
    proposal && approvals.status === "ready"
      ? approvals.data.find(({ approval }) => approval.id === proposal)
      : undefined;
  const linkedPending = linked?.approval.status === "PENDING" ? linked : undefined;
  const linkedFirst = linkedPending
    ? [linkedPending, ...recallFirst.filter(({ approval }) => approval.id !== linkedPending.approval.id)]
    : recallFirst;
  const linkedOrderId = linkedPending?.approval.orderId;
  useEffect(() => {
    if (!linkedOrderId) return;
    const card = document.getElementById(`proposal-${linkedOrderId}`);
    card?.scrollIntoView({ block: "start" });
    card?.focus({ preventScroll: true });
  }, [linkedOrderId]);
  const linkedMessage =
    !proposal || approvals.status !== "ready" || linkedPending
      ? undefined
      : !linked
        ? t("Proposal {id} was not found.", { id: proposal })
        : linked.approval.status === "BLOCKED_BY_RECALL"
          ? t("Proposal {id} is held by a recall and cannot be approved.", { id: proposal })
          : decidedHere.current.has(linked.approval.id)
            ? undefined
            : t("Proposal {id} has already been decided.", { id: proposal });
  const recallStatus: RecallStatus =
    recalls.status === "loading"
      ? { kind: "loading" }
      : recalls.status === "error"
        ? { kind: "unknown", message: recalls.error.message }
        : recalls.data === null
          ? { kind: "unavailable" }
          : {
              kind: "ready",
              lastCheck: recalls.data.lastCheck,
              // No proposal carries it (`proposals: []`): the product is in stock or in a recipe.
              unheld: recalls.data.alerts.filter(
                (alert, index, all) =>
                  alert.status === "active" &&
                  alert.orderId == null &&
                  all.findIndex((other) => other.eventId === alert.eventId) === index,
              ),
              affecting: recalls.data.alerts.filter(
                (alert) =>
                  alert.proposalStatus === "BLOCKED_BY_RECALL" &&
                  alert.orderId != null &&
                  openOrders.has(alert.orderId),
              ).length,
            };
  const checkRecalls =
    api.checkRecalls && recallStatus.kind !== "unavailable"
      ? async () => {
          await api.checkRecalls!(actor);
          recalls.reload();
          approvals.reload();
        }
      : undefined;

  return (
    <AppShell activeId="approvals">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <OpenDemoNote />
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold">{t("To approve")}</h1>
            <LiveConnectionLabel />
          </div>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t("Every order the Buyer proposes waits here. Nothing is sent until a person approves it.")}
          </p>
        </header>
        <RecallPanel status={recallStatus} onCheck={checkRecalls} />
        {linkedMessage ? (
          <p role="status" className="hatch px-3 py-2 text-sm break-words">
            {linkedMessage}
          </p>
        ) : null}
        {approvals.status === "loading" ? <LoadingState label={t("Loading approvals")} /> : null}
        {approvals.status === "error" ? (
          <ErrorState message={approvals.error.message} onRetry={approvals.reload} />
        ) : null}
        {approvals.status === "ready" && approvals.data.length === 0 ? (
          <EmptyState title={t("No approvals yet")}>
            {t("Orders that need a human decision will appear here.")}
          </EmptyState>
        ) : null}
        {approvals.status === "ready" && approvals.data.length > 0 ? (
          <div className="space-y-8">
            <section className="space-y-4" aria-labelledby="waiting-heading">
              <h2 id="waiting-heading" className="text-lg font-semibold">
                {t("Waiting for you ({count})", { count: pending.length })}
              </h2>
              {pending.length > 0 ? (
                <div className="space-y-4">
                  {linkedFirst.map(({ approval, order }) => (
                    <ApprovalCard
                      key={approval.id}
                      request={approval}
                      order={order ?? undefined}
                      onApprove={approve}
                      onReject={reject}
                      onChangeProposal={
                        canEdit ? (proposalChange) => change(approval.orderId, proposalChange) : undefined
                      }
                      onChooseOption={
                        api.chooseOption &&
                        (async (optionId) => {
                          try {
                            await api.chooseOption?.(approval.id, optionId, actor);
                            toast.success(t("Option chosen. Check the new total before you approve."));
                          } finally {
                            // A refused choice keeps its basket; reload that same proposal after either answer.
                            await approvals.reload();
                          }
                        })
                      }
                      listAddableProducts={
                        canEdit ? (query) => api.listAddableProducts(approval.orderId, query) : undefined
                      }
                      editCount={editCounts[approval.orderId] ?? 0}
                      approvalBlockedReason={
                        session && !session.canApprove ? t("Your account cannot approve or reject orders.") : undefined
                      }
                      recalls={recallsFor(approval.orderId)}
                    />
                  ))}
                </div>
              ) : (
                <EmptyState title={t("Nothing waiting for you")}>
                  {t("No proposals are waiting for your approval.")}
                </EmptyState>
              )}
            </section>
            {held.length > 0 ? (
              <section className="space-y-4" aria-labelledby="held-heading">
                <h2 id="held-heading" className="text-lg font-semibold">
                  {t("Held by a recall ({count})", { count: held.length })}
                </h2>
                <div className="space-y-4">
                  {held.map(({ approval, order }) => (
                    <ApprovalCard
                      key={approval.id}
                      request={approval}
                      order={order ?? undefined}
                      onReject={reject}
                      approvalBlockedReason={
                        session && !session.canApprove ? t("Your account cannot approve or reject orders.") : undefined
                      }
                      recalls={recallsFor(approval.orderId)}
                    />
                  ))}
                </div>
              </section>
            ) : null}
            {decided.length > 0 ? (
              <section className="space-y-4" aria-labelledby="decided-heading">
                <h2 id="decided-heading" className="text-lg font-semibold">
                  {t("Decided")}
                </h2>
                <div className="space-y-4">
                  {/* Every card starts compact, and only the first few decided ones show: a phone stays short (#1142). */}
                  {(allDecided ? decided : decided.slice(0, DECIDED_SHOWN)).map(({ approval, order }) => (
                    <ApprovalCard
                      key={approval.id}
                      request={approval}
                      order={order ?? undefined}
                      recalls={recallsFor(approval.orderId)}
                    />
                  ))}
                </div>
                {!allDecided && decided.length > DECIDED_SHOWN ? (
                  <Button type="button" variant="outline" onClick={() => setAllDecided(true)}>
                    {t("Show all decided ({count})", { count: decided.length })}
                  </Button>
                ) : null}
              </section>
            ) : null}
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
