import type { Api, AuditActor, ProductTemperature } from "@/api/types";
import { ApiError } from "@/api/types";
import { nameProducts } from "@/api/map";
import { createPlanningMock } from "@/api/mock-planning";
import { createSettingsMock } from "@/api/mock-settings";
import { driftMock, supplierDriftMock } from "@/api/mock-drift";
import { forecastAccuracyMock } from "@/api/mock-forecast";
import {
  approval as seedApproval,
  confirmedDemoApproval,
  confirmedDemoOrder,
  auditEvents,
  mandate,
  milkOptionLines,
  milkOptions,
  offers,
  orders as seedOrders,
  products,
  substitutes,
} from "@/mocks/milk-case";
import { formatEur } from "@/lib/format";
import { isPassed, isUnknownStock } from "@/lib/format";
import type {
  AddableProduct,
  ApprovalRequest,
  AuditEvent,
  FeedbackRow,
  Order,
  OrderLine,
  Product,
  ProposalChange,
} from "@/types";

/** The mock products label temperature in prose, e.g. "Chilled, +2 to +6 °C". */
function temperatureOf(product: Product): ProductTemperature | null {
  const label = product.temperature?.label.toLocaleLowerCase();
  if (!label) return null;
  if (label.includes("ambient")) return "ambient";
  if (label.includes("chilled")) return "chilled";
  if (label.includes("frozen")) return "frozen";
  return null;
}

export interface MockApi extends Api {
  /** Test and demo hook: the next `approve` is refused with this gateway error code. */
  failNextApprove(code: string, message?: string): void;
}

/** The milk case held in memory. Each call makes its own state, so tests do not share it. */
export function createMockApi(): MockApi {
  const approvals = new Map(
    [{ ...confirmedDemoApproval, options: milkOptions }, seedApproval].map((row) => [row.id, structuredClone(row)]),
  );
  const demoOrders = new Map([...Object.values(seedOrders), confirmedDemoOrder].map((row) => [row.id, structuredClone(row)]));
  const audit: AuditEvent[] = [...auditEvents];
  const feedback: FeedbackRow[] = [];
  let nextFailure: ApiError | null = null;

  const recordAudit = (event: Pick<AuditEvent, "kind" | "actor" | "summary" | "reason">) => {
    audit.push({
      ...event,
      id: `EV-${audit.length + 1}`,
      at: new Date().toISOString(),
    });
  };

  function pendingApproval(id: string): ApprovalRequest {
    const approval = approvals.get(id);
    if (!approval) throw new ApiError("NOT_FOUND", `Approval ${id} was not found.`);
    if (approval.status !== "PENDING") throw new ApiError("ALREADY_DECIDED", `Approval ${id} is already decided.`);
    return approval;
  }

  function decide(current: ApprovalRequest, status: "APPROVED" | "REJECTED", actor: AuditActor, summary: string, reason: string | null) {
    const approval = { ...current, status };
    approvals.set(approval.id, approval);
    audit.push({
      id: `EV-${audit.length + 1}`,
      at: new Date().toISOString(),
      kind: "approval",
      actor,
      summary,
      reason: reason ?? (status === "REJECTED" ? "No reason given." : summary),
      orderId: approval.orderId,
    });
    feedback.push({
      id: `FB-${feedback.length + 1}`,
      at: new Date().toISOString(),
      actor,
      orderId: approval.orderId,
      productId: null,
      kind: status === "APPROVED" ? "APPROVED" : "REJECTED",
      from: null,
      to: null,
      reason: status === "REJECTED" ? reason : null,
    });
    return approval;
  }

  function appendChange(
    orderId: string,
    kind: FeedbackRow["kind"],
    productId: string,
    from: number | null,
    to: number | null,
    actor: AuditActor,
    summary: string,
  ) {
    feedback.push({
      id: `FB-${feedback.length + 1}`,
      at: new Date().toISOString(),
      actor,
      orderId,
      productId,
      kind,
      from,
      to,
      reason: null,
    });
    audit.push({
      id: `EV-${audit.length + 1}`,
      at: new Date().toISOString(),
      kind: "approval",
      actor,
      summary,
      reason: summary,
      orderId,
    });
  }

  function resimulate(lines: OrderLine[], proposalOrder: Order): Order {
    let exVat = 0;
    let inclVat = 0;
    for (const line of lines) {
      if (line.offer.priceExVat == null) {
        throw new ApiError("PRICE_UNKNOWN", `Price for ${line.product.id} is unknown.`);
      }
      const lineEx = line.offer.priceExVat * line.quantity;
      exVat += lineEx;
      inclVat += lineEx * (1 + line.offer.taxRatePercent / 100);
    }
    const totalExVat = Math.round((exVat + Number.EPSILON) * 100) / 100;
    const totalInclVat = Math.round((inclVat + 1e-10) * 100) / 100;
    return {
      ...proposalOrder,
      lines,
      totalExVat,
      totalInclVat,
      mov: { ...proposalOrder.mov, current: totalExVat },
    };
  }

  return {
    ...createPlanningMock(recordAudit),
    ...createSettingsMock(recordAudit),
    getForecastAccuracy: async () => forecastAccuracyMock(),
    getDrift: async () => driftMock(),
    getSupplierDrift: async () => supplierDriftMock(),
    failNextApprove(code, message = "The gateway refused the approval.") {
      nextFailure = new ApiError(code, message);
    },

    async listApprovals() {
      return [...approvals.values()];
    },
    async getApproval(id) {
      const approval = approvals.get(id);
      if (!approval) throw new ApiError("NOT_FOUND", `Approval ${id} was not found.`);
      return approval;
    },
    async approve(decision, actor) {
      const current = pendingApproval(decision.approvalId);
      if (nextFailure) {
        const failure = nextFailure;
        nextFailure = null;
        throw failure;
      }
      if (
        decision.expectedTotalExVat !== current.totalExVat ||
        decision.expectedTotalInclVat !== current.totalInclVat
      ) {
        throw new ApiError("TOTAL_MISMATCH", "The order total changed since you read it.");
      }
      const order = demoOrders.get(current.orderId)!;
      if (order.lines.some((line) => isUnknownStock(line.offer.availableAmount))) {
        throw new ApiError("STOCK_UNKNOWN", "Waiting for supplier stock confirmation.");
      }
      demoOrders.set(order.id, { ...order, status: "PLACED" });
      const decided = decide(
        current, "APPROVED", actor, `Approved ${current.orderId}`,
        `Approved exactly ${formatEur(current.totalExVat)} ex VAT (${formatEur(current.totalInclVat)} incl VAT).`,
      );
      audit.push({ id: `EV-${audit.length + 1}`, at: new Date().toISOString(), kind: "order", actor: "gateway",
        orderId: order.id, summary: `Placed ${order.id}`, reason: "Human approved the exact simulated demo total; stock was measured." });
      return decided;
    },
    async reject(approvalId, reason, actor) {
      const current = pendingApproval(approvalId);
      return decide(current, "REJECTED", actor, `Rejected ${current.orderId}`, reason.trim() || null);
    },

    async listAddableProducts(orderId, query = "") {
      const proposalOrder = demoOrders.get(orderId);
      if (!proposalOrder) throw new ApiError("NOT_FOUND", `Order ${orderId} was not found.`);
      const words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
      const existing = new Set(proposalOrder.lines.map((line) => line.product.id));
      const ranked: AddableProduct[] = (Object.entries(products) as [keyof typeof products, Product][])
        .filter(([, product]) => !existing.has(product.id))
        .map(([key, product]) => {
          const offer = offers[key];
          return {
            product,
            offer,
            onHand: isUnknownStock(offer.availableAmount) ? null : offer.availableAmount,
            onOrder: null,
            suggestedQuantity: 1,
            why: isPassed(offer.closingTime, new Date())
              ? "The order cut-off has passed, so this product may arrive late."
              : "The order cut-off is still open for the requested delivery.",
          };
        })
        .filter(({ offer }) => offer.priceExVat != null)
        .filter(({ product }) => {
          const names = [product.names.en, product.names.fi, product.names.sv].join(" ").toLocaleLowerCase();
          return words.every((word) => names.includes(word));
        })
        .sort(
          (a, b) =>
            Number(isPassed(a.offer.closingTime, new Date())) - Number(isPassed(b.offer.closingTime, new Date())),
        );
      return ranked;
    },
    async changeProposal(orderId, change: ProposalChange, actor) {
      const proposalOrder = demoOrders.get(orderId);
      if (!proposalOrder) throw new ApiError("NOT_FOUND", `Order ${orderId} was not found.`);
      const approval = [...approvals.values()].find((row) => row.orderId === orderId)!;
      pendingApproval(approval.id);
      if (change.type !== "REMOVE_LINE" && (!Number.isInteger(change.quantity) || change.quantity < 1)) {
        throw new ApiError("INVALID", "Quantity must be a whole number of at least 1.");
      }
      let lines = [...proposalOrder.lines];
      let kind: FeedbackRow["kind"];
      let from: number | null = null;
      let to: number | null = null;
      let summary: string;
      if (change.type === "SET_QUANTITY") {
        const line = lines.find((item) => item.product.id === change.productId);
        if (!line) throw new ApiError("NOT_FOUND", `Product ${change.productId} is not on the order.`);
        from = line.quantity;
        to = change.quantity;
        lines = lines.map((item) => (item === line ? { ...item, quantity: change.quantity } : item));
        kind = "QUANTITY_CHANGED";
        summary = `Changed ${change.productId} from ${from} to ${to}`;
      } else if (change.type === "REMOVE_LINE") {
        if (!lines.some((line) => line.product.id === change.productId)) {
          throw new ApiError("NOT_FOUND", `Product ${change.productId} is not on the order.`);
        }
        lines = lines.filter((line) => line.product.id !== change.productId);
        if (lines.length === 0) throw new ApiError("INVALID", "An order needs at least one line; reject it instead.");
        kind = "LINE_REMOVED";
        summary = `Removed ${change.productId}`;
      } else {
        if (lines.some((line) => line.product.id === change.productId)) {
          throw new ApiError("INVALID", `${change.productId} is already on the order.`);
        }
        const productKey = Object.keys(products).find(
          (key) => products[key as keyof typeof products].id === change.productId,
        ) as keyof typeof offers | undefined;
        if (!productKey) throw new ApiError("NOT_FOUND", `Product ${change.productId} was not found.`);
        const product = products[productKey];
        const offer = offers[productKey];
        if (offer.priceExVat == null) throw new ApiError("PRICE_UNKNOWN", `Price for ${change.productId} is unknown.`);
        lines.push({
          product,
          offer,
          quantity: change.quantity,
          why: "Added by a person reviewing the Buyer's proposal.",
        });
        to = change.quantity;
        kind = "LINE_ADDED";
        summary = `Added ${change.productId} with quantity ${change.quantity}`;
      }
      const next = resimulate(lines, proposalOrder);
      Object.assign(proposalOrder, next);
      // An edited basket is no longer one of the engine's options.
      const options = approval.options?.map((option) => ({ ...option, chosen: false }));
      const nextApproval = { ...approval, totalExVat: next.totalExVat, totalInclVat: next.totalInclVat, lineCount: lines.length, options };
      approvals.set(approval.id, nextApproval);
      appendChange(proposalOrder.id, kind, change.productId, from, to, actor, summary);
      return { order: proposalOrder, approval: nextApproval };
    },
    async chooseOption(approvalId, optionId, actor) {
      const current = pendingApproval(approvalId);
      const option = current.options?.find((row) => row.id === optionId);
      if (!option) throw new ApiError("NOT_FOUND", `Option ${optionId} was not found.`);
      if (option.cutoffPassed) throw new ApiError("CLOSING_PASSED", "The order cut-off for this option has passed.");
      const lines = structuredClone(milkOptionLines[optionId]);
      if (!lines) throw new ApiError("NOT_FOUND", `Option ${optionId} has no basket.`);
      const order = demoOrders.get(current.orderId)!;
      Object.assign(order, resimulate(lines, order));
      const approval = {
        ...current,
        totalExVat: order.totalExVat,
        totalInclVat: order.totalInclVat,
        lineCount: lines.length,
        options: current.options?.map((row) => ({ ...row, chosen: row.id === optionId })),
      };
      approvals.set(approval.id, approval);
      audit.push({
        id: `EV-${audit.length + 1}`,
        at: new Date().toISOString(),
        kind: "approval",
        actor,
        orderId: order.id,
        summary: `Chose option ${optionId} for ${order.id}`,
        reason: `Re-simulated: ${formatEur(order.totalInclVat)} incl VAT. Nothing is approved or sent yet.`,
      });
      return approval;
    },
    async listFeedback(filter) {
      return filter?.orderId ? feedback.filter((row) => row.orderId === filter.orderId) : [...feedback];
    },

    async listOrders() {
      return [...demoOrders.values()];
    },
    async getOrder(id) {
      const found = demoOrders.get(id);
      if (!found) throw new ApiError("NOT_FOUND", `Order ${id} was not found.`);
      return found;
    },
    async listAudit(filter) {
      const names = new Map((Object.values(products) as Product[]).map((product) => [product.id, product.names.en]));
      return (filter?.orderId ? audit.filter((event) => event.orderId === filter.orderId) : audit).map((event) => ({
        ...event,
        summary: nameProducts(event.summary, names),
        reason: nameProducts(event.reason, names),
      }));
    },
    async submitChefRequest() {
      return { order: demoOrders.get(seedApproval.orderId)!, substitutes, approval: approvals.get(seedApproval.id)! };
    },
    async searchProducts(query, filters = {}) {
      const words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
      const excluded = filters.excludedAllergens ?? [];
      const requiredLabels = filters.requiredLabels ?? [];
      return (Object.values(products) as Product[]).filter((product) => {
        const names = [product.names.en, product.names.fi, product.names.sv].join(" ").toLocaleLowerCase();
        if (!words.every((word) => names.includes(word))) return false;
        if (!requiredLabels.every((label) => product.labels.includes(label))) return false;
        if (filters.temperature && temperatureOf(product) !== filters.temperature) return false;
        // No allergen data is unknown, not safe: the row stays unless the search is strict.
        if (product.allergens === null) return !filters.strictAllergens;
        return !product.allergens.some((allergen) => excluded.includes(allergen.code));
      });
    },
    async getProducts(ids) {
      const wanted = new Set(ids);
      return (Object.values(products) as Product[]).filter((product) => wanted.has(product.id));
    },
    async getMandate() {
      return mandate;
    },
  };
}
