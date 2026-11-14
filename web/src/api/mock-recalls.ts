import type { Api, AuditActor } from "@/api/types";
import {
  coffeeRecallAlert,
  coffeeRecording,
  coffeeReplacementApproval,
  coffeeReplacementLine,
  coffeeReplacementOrder,
} from "@/mocks/coffee-recall";
import type { ApprovalRequest, AuditEvent, Order, RecallAlert, RecallCheck } from "@/types";

interface RecallMockDeps {
  /** The open order the recall hits, or undefined when it is gone. */
  getOrder(id: string): Order | undefined;
  /** Adds the replacement as its own proposal with its own pending approval. */
  addReplacement(order: Order, approval: ApprovalRequest): void;
  /** Marks the original proposal blocked by recall, so it is never approvable. */
  hold(orderId: string): void;
  /** True while the order's approval is still pending. */
  isPending(orderId: string): boolean;
  recordAudit(event: Pick<AuditEvent, "kind" | "actor" | "summary" | "reason" | "orderId">): void;
}

/**
 * The recall monitor (#358) in memory. Nothing is known before the first check, so the
 * screens say "not checked yet", never "no recalls". A check answers from the recorded
 * Context.dev scrape; it holds the original and adds a separate replacement proposal.
 * A person rejects the original and approves the replacement's own total. A repeat check
 * is a replay: same alert, no second replacement.
 */
export function createRecallMock(deps: RecallMockDeps): Required<Pick<Api, "listRecalls" | "checkRecalls">> {
  const alerts = new Map<string, RecallAlert>();
  let lastCheck: RecallCheck | null = null;

  return {
    async listRecalls() {
      return { lastCheck, alerts: [...alerts.values()] };
    },
    async checkRecalls(actor: AuditActor) {
      const checkedAt = new Date().toISOString();
      deps.recordAudit({
        kind: "search",
        actor,
        summary: `Checked Ruokavirasto recalls: ${coffeeRecording.noticesScanned} notices`,
        reason: `Context.dev ${coffeeRecording.via}, recording from ${coffeeRecording.fetchedAt} (the live scrape is the monitor's, #358).`,
      });
      let alert = coffeeRecallAlert(checkedAt);
      const order = alert.orderId ? deps.getOrder(alert.orderId) : undefined;
      const onOpenOrder =
        order != null && deps.isPending(order.id) && order.lines.some((line) => line.product.id === alert.productId);
      if (!onOpenOrder) {
        // Still in stock and recipes, but no open order holds it: nothing to block or re-plan.
        alert = {
          ...alert,
          orderId: null,
          proposalStatus: "UNKNOWN",
          replacement: null,
          where: alert.where.filter((place) => !place.includes("proposal")),
        };
      }
      if (!alerts.has(alert.eventId) && order && onOpenOrder) {
        deps.hold(order.id);
        deps.addReplacement(structuredClone(coffeeReplacementOrder), structuredClone(coffeeReplacementApproval));
        deps.recordAudit({
          kind: "approval",
          actor: "gateway",
          orderId: order.id,
          summary: `Blocked ${alert.productId} by recall; replaced with ${coffeeReplacementLine.product.id}`,
          reason: `${alert.recall.title} (${alert.recall.date}): ${alert.match} match, ${alert.why}. ${alert.nextStep} Nothing is approved or sent yet.`,
        });
      }
      if (!alerts.has(alert.eventId)) alerts.set(alert.eventId, alert);
      lastCheck = {
        checkedAt,
        source: "recording",
        fetchedAt: coffeeRecording.fetchedAt,
        via: coffeeRecording.via,
        noticesScanned: coffeeRecording.noticesScanned,
        liveError: "NO_KEY",
        noticesListed: null,
        noticesUnread: null,
        scannedSince: "2026-03-02",
        detailsFetchedAt: coffeeRecording.fetchedAt,
        checkedBy: actor,
      };
      return { lastCheck, alerts: [...alerts.values()] };
    },
  };
}
