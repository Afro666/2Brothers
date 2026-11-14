import type { Api, AuditActor, AuditChainRow, ProductTemperature } from "@/api/types";
import { ApiError } from "@/api/types";
import { GENESIS, KITCHEN_ID, mapChainCheck, rowHash, verifyRows } from "@/api/audit-chain";
import { nameProducts } from "@/api/map";
import { permissionsMock } from "@/api/mock-permissions";
import { createNutritionMock } from "@/api/mock-nutrition";
import { createPlanningMock } from "@/api/mock-planning";
import { createSettingsMock } from "@/api/mock-settings";
import { driftMock, supplierDriftMock } from "@/api/mock-drift";
import { createOffersMock } from "@/api/mock-offers";
import { forecastAccuracyMock } from "@/api/mock-forecast";
import { createRecallMock } from "@/api/mock-recalls";
import { coffeeApproval, coffeeOrder } from "@/mocks/coffee-recall";
import { sampleReceipt } from "@/mocks/receipt";
import { lookupKitchenBrandMock } from "@/api/mock-onboarding";
import { readShelfPhotoMock } from "@/api/mock-shelf";
import { createMockAuth } from "@/api/mock-auth";
import { createKitchenMock } from "@/api/mock-kitchen";
import { createNotificationsMock } from "@/api/mock-notifications";
import { createDeveloperMock } from "@/api/mock-developer";
import { createPrivacyMock } from "@/api/mock-privacy";
import { createTokensMock } from "@/api/mock-tokens";
import { modelUsageMock } from "@/api/mock-usage";
import { createWordsMock } from "@/api/mock-words";
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
  OrderResolution,
  OrderResolutionResult,
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

export interface MockApiOptions {
  signedOut?: boolean;
}

/** The milk case held in memory. Each call makes its own state, so tests do not share it. */
export function createMockApi(options: MockApiOptions = {}): MockApi {
  const unknownOrder: Order = {
    ...structuredClone(seedOrders.placed),
    id: "ORD-1046",
    status: "UNCONFIRMED",
    urgency: "UNKNOWN",
    supplierOrderRef: null,
    // Placed before receipts existed: the detail page says it has none.
    receipt: null,
  };
  const placedOrder: Order = {
    ...structuredClone(seedOrders.placed),
    receipt: sampleReceipt(seedOrders.placed, "aron", "2026-11-14T08:15:00Z"),
  };
  const supplierConfirmationOrder: Order = {
    ...structuredClone(seedOrders.placed),
    id: "ORD-1047",
    supplierMustConfirm: ["SUP-BAKERY"],
  };
  const unknownApproval: ApprovalRequest = {
    ...structuredClone(seedApproval),
    id: "APR-UNKNOWN-1046",
    approvalRef: "APR-UNKNOWN-1046",
    orderId: unknownOrder.id,
    status: "APPROVED",
  };
  const supplierConfirmationApproval: ApprovalRequest = {
    ...structuredClone(confirmedDemoApproval),
    id: "APR-314",
    approvalRef: "APR-314",
    orderId: supplierConfirmationOrder.id,
    summary: "Demo: bakery stock waiting for supplier confirmation",
    totalExVat: 80,
    totalInclVat: 91.2,
    suppliersToConfirm: [{ supplierId: "SUP-BAKERY", name: "Leipomo Demo" }],
  };
  const approvals = new Map(
    [
      { ...confirmedDemoApproval, options: milkOptions },
      seedApproval,
      coffeeApproval,
      unknownApproval,
      supplierConfirmationApproval,
    ].map((row) => [row.id, structuredClone(row)]),
  );
  const demoOrders = new Map(
    [placedOrder, seedOrders.needsApproval, confirmedDemoOrder, coffeeOrder, unknownOrder, supplierConfirmationOrder].map(
      (row) => [row.id, structuredClone(row)],
    ),
  );
  const resolutions = new Map<string, OrderResolution>([
    [
      unknownOrder.id,
      {
        orderId: unknownOrder.id,
        proposalId: unknownApproval.id,
        proposalStatus: "COMMITTING",
        idempotencyKey: "approve-unknown-1046",
        payloadHash: "3a08f1a95f244b7f9d8f6f7e8e7e51e2",
        offerId: "OFR-MILK-UNKNOWN",
        supplierId: "sup-valio",
        approvedBy: "aron",
        outcome: "UNCONFIRMED",
        status: null,
        expectedTotal: unknownOrder.totalInclVat,
        lines: structuredClone(unknownOrder.lines),
        createdAt: "2026-11-14T02:10:00+00:00",
        updatedAt: "2026-11-14T02:10:01+00:00",
        resolvable: true,
        resolution: null,
      },
    ],
  ]);
  const audit: AuditEvent[] = [...auditEvents];
  const feedback: FeedbackRow[] = [];
  let nextFailure: ApiError | null = null;

  // The stored hash of each audit line, in order. A line is hashed once, when the chain is
  // first read after the line was written; changing the line later no longer matches it.
  const hashes: Pick<AuditChainRow, "prevHash" | "hash">[] = [];
  let tampered: { index: number; original: AuditEvent } | null = null;
  function chainRows(): AuditChainRow[] {
    for (let index = hashes.length; index < audit.length; index++) {
      const prevHash = index === 0 ? GENESIS : hashes[index - 1].hash;
      hashes.push({ prevHash, hash: rowHash(index + 1, prevHash, audit[index]) });
    }
    return hashes.map((stored, index) => ({ seq: index + 1, event: audit[index], ...stored }));
  }
  const productNames = new Map((Object.values(products) as Product[]).map((product) => [product.id, product.names.en]));
  const named = (event: AuditEvent): AuditEvent => ({
    ...event,
    summary: nameProducts(event.summary, productNames),
    reason: nameProducts(event.reason, productNames),
  });

  const recordAudit = (
    event: Pick<AuditEvent, "kind" | "actor" | "summary" | "reason"> & Partial<Pick<AuditEvent, "orderId">>,
  ) => {
    audit.push({
      ...event,
      id: `EV-${audit.length + 1}`,
      at: new Date().toISOString(),
    });
  };

  function pendingApproval(id: string, allowRecallHold = false): ApprovalRequest {
    const approval = approvals.get(id);
    if (!approval) throw new ApiError("NOT_FOUND", `Approval ${id} was not found.`);
    if (approval.status !== "PENDING" && !(allowRecallHold && approval.status === "BLOCKED_BY_RECALL")) {
      throw new ApiError("ALREADY_DECIDED", `Approval ${id} is already decided.`);
    }
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

  function resimulate(lines: OrderLine[], proposalOrder: Order): Order & { totalExVat: number } {
    let exVat = 0;
    let inclVat = 0;
    for (const line of lines) {
      if (line.offer.priceExVat == null || line.offer.taxRatePercent == null) {
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
      mov: proposalOrder.mov && { ...proposalOrder.mov, current: totalExVat },
    };
  }

  const planning = createPlanningMock(recordAudit);
  const getProducts: Api["getProducts"] = async (ids) => {
    const wanted = new Set(ids);
    return (Object.values(products) as Product[]).filter((product) => wanted.has(product.id));
  };

  return {
    ...createMockAuth(options.signedOut),
    ...createKitchenMock(recordAudit),
    ...createNotificationsMock(recordAudit),
    ...createDeveloperMock(recordAudit),
    ...createPrivacyMock(recordAudit),
    ...planning,
    ...createNutritionMock(planning),
    ...createWordsMock(getProducts),
    ...createSettingsMock(recordAudit),
    getForecastAccuracy: async () => forecastAccuracyMock(),
    getDrift: async () => driftMock(),
    getSupplierDrift: async () => supplierDriftMock(),
    ...createOffersMock(),
    ...permissionsMock,
    ...createRecallMock({
      getOrder: (id) => demoOrders.get(id),
      isPending: (orderId) => [...approvals.values()].some((row) => row.orderId === orderId && row.status === "PENDING"),
      addReplacement(order, approval) {
        demoOrders.set(order.id, order);
        approvals.set(approval.id, approval);
      },
      hold: (orderId) => {
        const approval = [...approvals.values()].find((row) => row.orderId === orderId);
        if (approval) approvals.set(approval.id, { ...approval, status: "BLOCKED_BY_RECALL" });
        const order = demoOrders.get(orderId);
        if (order) demoOrders.set(orderId, { ...order, status: "BLOCKED_BY_RECALL" });
      },
      recordAudit: (event) => audit.push({ ...event, id: `EV-${audit.length + 1}`, at: new Date().toISOString() }),
    }),
    lookupKitchenBrand: lookupKitchenBrandMock,
    ...createTokensMock(),
    getModelUsage: async () => modelUsageMock(),
    readShelfPhoto: readShelfPhotoMock,
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
      const current = pendingApproval(decision.approvalId, true);
      if (current.status === "BLOCKED_BY_RECALL") {
        throw new ApiError(
          "BLOCKED_BY_RECALL",
          "This order is blocked by a recall and cannot be approved. Reject it and approve the replacement order instead.",
        );
      }
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
      const short = order.lines.find(
        (line) => line.offer.availableAmount != null && line.quantity > line.offer.availableAmount,
      );
      if (short) {
        throw new ApiError(
          "PARTIAL_STOCK",
          `Only ${short.offer.availableAmount} of ${short.product.id} in supplier stock; ${short.quantity} requested.`,
        );
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
      const current = pendingApproval(approvalId, true);
      const rejected = decide(current, "REJECTED", actor, `Rejected ${current.orderId}`, reason.trim() || null);
      return rejected;
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
      const approval = [...approvals.values()].find((row) => row.orderId === orderId);
      if (!approval) throw new ApiError("NOT_FOUND", `Order ${orderId} has no approval to change.`);
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
      const next = resimulate(lines, order);
      Object.assign(order, next);
      const approval = {
        ...current,
        totalExVat: next.totalExVat,
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
    async getOrderResolution(orderId) {
      const found = resolutions.get(orderId);
      if (!found) throw new ApiError("ORDER_NOT_FOUND", `Order ${orderId} was not found.`);
      return structuredClone(found);
    },
    async resolveOrder(orderId, input, actor) {
      const current = resolutions.get(orderId);
      if (!current) throw new ApiError("ORDER_NOT_FOUND", `Order ${orderId} was not found.`);
      const supplierOrderRef = input.resolution === "placed" ? input.supplierOrderRef.trim() : null;
      const note = input.resolution === "not_sent" ? (input.note?.trim() ?? "") : "";
      if (input.resolution === "placed" && (!supplierOrderRef || supplierOrderRef.length > 200)) {
        throw new ApiError("INVALID_REQUEST", "The supplier order reference must be 1 to 200 characters.");
      }
      if (note.length > 500) throw new ApiError("INVALID_REQUEST", "The note must be at most 500 characters.");
      if (current.resolution) {
        if (
          current.resolution.resolution !== input.resolution ||
          current.resolution.supplierOrderRef !== supplierOrderRef
        ) {
          throw new ApiError("ALREADY_RESOLVED", "Someone else already resolved this order another way.");
        }
      } else if (!current.resolvable) {
        throw new ApiError("ORDER_NOT_RESOLVABLE", "This order is no longer waiting for resolution.");
      } else {
        const resolvedAt = new Date().toISOString();
        current.resolution = {
          resolution: input.resolution,
          supplierOrderRef,
          note,
          resolvedBy: actor,
          resolvedAt,
          fromOutcome: current.outcome,
        };
        current.resolvable = false;
        current.updatedAt = resolvedAt;
        recordAudit({
          kind: "order",
          actor: "human",
          orderId,
          summary: `${input.resolution === "placed" ? "Marked placed" : "Marked not sent"}: ${orderId}`,
          reason: note || supplierOrderRef || `Checked with the supplier; recorded by ${actor}.`,
        });
      }
      const placed = current.resolution.resolution === "placed";
      current.outcome = placed ? "CONFIRMED" : "NOT_SENT";
      current.status = placed ? "SENT" : null;
      current.proposalStatus = placed ? "APPROVED" : "READY";
      demoOrders.set(orderId, {
        ...demoOrders.get(orderId)!,
        status: placed ? "PLACED" : "NOT_SENT",
        supplierOrderRef: current.resolution.supplierOrderRef,
      });
      approvals.set(unknownApproval.id, { ...approvals.get(unknownApproval.id)!, status: placed ? "APPROVED" : "PENDING" });
      const result: OrderResolutionResult = {
        orderId,
        proposalId: current.proposalId,
        proposalStatus: current.proposalStatus,
        outcome: current.outcome,
        status: current.status,
        resolution: structuredClone(current.resolution),
      };
      return structuredClone(result);
    },
    async listAudit(filter) {
      return (filter?.orderId ? audit.filter((event) => event.orderId === filter.orderId) : audit).map(named);
    },
    async listAuditChain(limit) {
      return chainRows()
        .slice(-limit)
        .map((row) => ({ ...row, event: named(row.event) }));
    },
    async verifyAuditChain() {
      const rows = chainRows();
      const check = verifyRows(rows);
      // Every sample line is this kitchen's own.
      return mapChainCheck({ ...check, broken_kitchen_id: check.ok ? null : KITCHEN_ID, kitchen_entries: rows.length });
    },
    async tamperAuditRow() {
      const rows = chainRows();
      if (rows.length === 0) throw new ApiError("NOTHING_TO_TAMPER", "The audit log is empty.");
      if (tampered) throw new ApiError("ALREADY_TAMPERED", "A line is already tampered.");
      const index = rows.length - 1;
      tampered = { index, original: audit[index] };
      audit[index] = { ...audit[index], summary: `${audit[index].summary} (edited after the fact)` };
      return { seq: index + 1 };
    },
    async restoreAuditRow() {
      if (!tampered) return { seq: null, restored: false };
      const { index, original } = tampered;
      audit[index] = original;
      tampered = null;
      return { seq: index + 1, restored: true };
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
    getProducts,
    async getMandate() {
      return mandate;
    },
  };
}
