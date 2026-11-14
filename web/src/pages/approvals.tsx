import { ApprovalCard, type ApprovalDecision } from "@/components/purchasing/approval-card";
import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { RecallPanel, type RecallStatus } from "@/components/purchasing/recall-panel";
import { useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/api";
import { ApiError, type Api } from "@/api/types";
import { auditActorForRole, useRole } from "@/lib/role";
import { formatEur } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
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

function ApiApprovalsPage() {
  const api = useApi();
  const { role } = useRole();
  const actor = auditActorForRole(role);
  const approvals = useAsync(() => loadApprovals(api), [api]);
  const [editCounts, setEditCounts] = useState<Record<string, number>>({});
  const recalls = useAsync(() => loadRecalls(api), [api]);

  // The gateway has no route to change a proposal yet, so its proposals are read-only.
  const canEdit = !api.live || api.live.has("changeProposal");

  async function approve(decision: ApprovalDecision): Promise<void> {
    try {
      await api.approve(decision, actor);
      toast.success(`Approved: ${formatEur(decision.expectedTotalInclVat)} incl VAT`, { testId: "approval-toast" });
    } finally {
      // Also after a refusal: when the total moved, the card must show the new one before asking again.
      approvals.reload();
    }
  }

  async function reject(approvalId: string, reason: string): Promise<void> {
    await api.reject(approvalId, reason, actor);
    toast.success("Rejected. The reason goes back to the Buyer.", { testId: "approval-toast" });
    approvals.reload();
  }

  async function change(orderId: string, proposalChange: ProposalChange): Promise<void> {
    await api.changeProposal(orderId, proposalChange, actor);
    setEditCounts((counts) => ({ ...counts, [orderId]: (counts[orderId] ?? 0) + 1 }));
    toast.success("Proposal updated. Check the new total before you approve.");
    approvals.reload();
  }

  const pending =
    approvals.status === "ready" ? approvals.data.filter(({ approval }) => approval.status === "PENDING") : [];
  const decided =
    approvals.status === "ready" ? approvals.data.filter(({ approval }) => approval.status !== "PENDING") : [];

  const pendingOrders = new Set(pending.map(({ approval }) => approval.orderId));
  const recallsFor = (orderId: string) =>
    recalls.status === "ready" ? (recalls.data?.alerts ?? []).filter((alert) => alert.orderId === orderId) : [];
  // An order a recall hits comes first, so nobody scrolls past it.
  const hit = (row: ApprovalWithOrder) => Number(recallsFor(row.approval.orderId).length > 0);
  const recallFirst = [...pending].sort((a, b) => hit(b) - hit(a));
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
              affecting: recalls.data.alerts.filter((alert) => alert.orderId != null && pendingOrders.has(alert.orderId))
                .length,
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
          <h1 className="text-2xl font-semibold">Approvals</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            Every order the Buyer proposes waits here. Nothing is sent until a person approves it.
          </p>
        </header>
        <RecallPanel status={recallStatus} onCheck={checkRecalls} />
        {approvals.status === "loading" ? <LoadingState label="Loading approvals" /> : null}
        {approvals.status === "error" ? (
          <ErrorState message={approvals.error.message} onRetry={approvals.reload} />
        ) : null}
        {approvals.status === "ready" && approvals.data.length === 0 ? (
          <EmptyState title="No approvals yet">Orders that need a human decision will appear here.</EmptyState>
        ) : null}
        {approvals.status === "ready" && approvals.data.length > 0 ? (
          <div className="space-y-8">
            <section className="space-y-4" aria-labelledby="waiting-heading">
              <h2 id="waiting-heading" className="text-lg font-semibold">
                Waiting for you ({pending.length})
              </h2>
              {pending.length > 0 ? (
                <div className="space-y-4">
                  {recallFirst.map(({ approval, order }) => (
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
                          await api.chooseOption?.(approval.id, optionId, actor);
                          toast.success("Option chosen. Check the new total before you approve.");
                          approvals.reload();
                        })
                      }
                      listAddableProducts={
                        canEdit ? (query) => api.listAddableProducts(approval.orderId, query) : undefined
                      }
                      editCount={editCounts[approval.orderId] ?? 0}
                      recalls={recallsFor(approval.orderId)}
                    />
                  ))}
                </div>
              ) : (
                <EmptyState title="Nothing waiting for you">All approvals have been decided.</EmptyState>
              )}
            </section>
            {decided.length > 0 ? (
              <section className="space-y-4" aria-labelledby="decided-heading">
                <h2 id="decided-heading" className="text-lg font-semibold">
                  Decided
                </h2>
                <div className="space-y-4">
                  {decided.map(({ approval, order }) => (
                    <ApprovalCard key={approval.id} request={approval} order={order ?? undefined} />
                  ))}
                </div>
              </section>
            ) : null}
          </div>
        ) : null}
      </div>
    </AppShell>
  );
}
