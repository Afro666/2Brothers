import { mapMoney } from "@/api/map";
import { mapProposalOptions } from "@/api/map-options";
import { ApiError } from "@/api/types";
import type {
  AddableProduct,
  ApprovalRequest,
  AuditEvent,
  AuditKind,
  BuyerPermissions,
  MovState,
  Offer,
  Order,
  OrderLine,
  OrderResolution,
  OrderResolutionRecord,
  OrderResolutionResult,
  OrderSendOutcome,
  OrderStatus,
  PermissionRow,
  Product,
  RecallCheck,
  RecallList,
  RecallMatch,
  RecallReplacement,
} from "@/types";

/**
 * Gateway JSON (docs/contract.md "Product API", gateway/service.py) to the UI types.
 * The gateway does not send everything a screen shows. What it does not send stays
 * null ("unknown"); it is never filled with zero or a guess.
 */

export type Json = Record<string, unknown>;

function invalid(what: string): never {
  throw new ApiError("INVALID_RESPONSE", `The gateway sent ${what} in an unexpected shape.`);
}

export function object(value: unknown, what: string): Json {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid(what);
  return value as Json;
}

export function text(value: unknown, what: string): string {
  if (typeof value !== "string" || !value) invalid(what);
  return value;
}

/** `{"proposals": [...]}` -> the rows. */
export function rows(body: unknown, key: string): Json[] {
  const list = object(body, key)[key];
  if (!Array.isArray(list)) invalid(key);
  return list.map((row) => object(row, key));
}

/** A decimal string, or null when the gateway says unknown. */
export function decimal(value: unknown, label: string): number | null {
  return value == null ? null : mapMoney(value, label);
}

function nullableText(value: unknown, what: string): string | null {
  return value == null || value === "" ? null : text(value, what);
}

function sendOutcome(value: unknown): OrderSendOutcome | null {
  return value === "CONFIRMED" || value === "NOT_SENT" || value === "UNCONFIRMED" || value === "SENT_READ_FAILED"
    ? value
    : null;
}

function resolutionRecord(value: unknown): OrderResolutionRecord | null {
  if (value == null) return null;
  const row = object(value, "order resolution");
  const resolution = row.resolution;
  if (resolution !== "placed" && resolution !== "not_sent") invalid("order resolution");
  return {
    resolution,
    supplierOrderRef: nullableText(row.supplier_order_ref, "supplier_order_ref"),
    note: row.note == null ? null : typeof row.note === "string" ? row.note : invalid("resolution note"),
    resolvedBy: nullableText(row.resolved_by, "resolved_by"),
    resolvedAt: nullableText(row.resolved_at, "resolved_at"),
    fromOutcome: sendOutcome(row.from_outcome),
  };
}

export function mapOrderResolutionResult(value: unknown): OrderResolutionResult {
  const row = object(value, "order resolution");
  return {
    orderId: text(row.order_id, "order_id"),
    proposalId: nullableText(row.proposal_id, "proposal_id"),
    proposalStatus: nullableText(row.proposal_status, "proposal_status"),
    outcome: sendOutcome(row.outcome),
    status: nullableText(row.status, "order status"),
    resolution: resolutionRecord(row.resolution),
  };
}

export function mapOrderResolution(value: unknown): OrderResolution {
  const row = object(value, "order resolution");
  if (!Array.isArray(row.lines)) invalid("order lines");
  return {
    ...mapOrderResolutionResult(row),
    idempotencyKey: nullableText(row.idempotency_key, "idempotency_key"),
    payloadHash: nullableText(row.payload_hash, "payload_hash"),
    offerId: nullableText(row.offer_id, "offer_id"),
    supplierId: nullableText(row.supplier_id, "supplier_id"),
    approvedBy: nullableText(row.approved_by, "approved_by"),
    expectedTotal: decimal(row.expected_total, "expected_total"),
    lines: row.lines.map((line) => mapLine(object(line, "an order line"), "")),
    createdAt: nullableText(row.created_at, "created_at"),
    updatedAt: nullableText(row.updated_at, "updated_at"),
    resolvable: row.resolvable === true,
  };
}

/** The gateway names a product by its code only (#304 adds the row): the rest is unknown. */
function productOf(id: string, name: string | null, unit: string): Product {
  return {
    id,
    names: { en: name ?? id },
    brand: "",
    vendorName: "",
    category: "",
    salesUnit: unit,
    baseUnit: "",
    baseUnitsPerSalesUnit: null,
    units: [],
    fatPercent: null,
    temperature: null,
    allergens: null,
    labels: [],
    co2KgPerKg: null,
    deliveryReliability: null,
  };
}

function offerOf(
  productId: string,
  unit: string,
  requestedDate: string,
  priceExVat: number | null,
  stockConfirmed: boolean,
): Offer {
  return {
    productId,
    requestedDate,
    priceExVat,
    taxRatePercent: null,
    comparisonPrice: null,
    comparisonUnit: null,
    availableAmount: null,
    stockConfirmed,
    salesUnit: unit,
    availableDate: null,
    closingTime: null,
    salesBlock: false,
  };
}

function mapLine(row: Json, requestedDate: string): OrderLine {
  const id = text(row.product_id, "a line's product_id");
  const unit = text(row.unit, "a line's unit");
  return {
    product: productOf(id, null, unit),
    // Only `unknown_stock: false` is a confirmation. The amount in stock is not sent.
    offer: offerOf(id, unit, requestedDate, decimal(row.unit_price, "unit_price"), row.unknown_stock === false),
    quantity: mapMoney(row.quantity, "quantity"),
    why: typeof row.why === "string" && row.why ? row.why : "Not recorded with the order.",
  };
}

function mapMov(proposal: Json): MovState | null {
  const gap = decimal(proposal.mov_gap, "mov_gap");
  const deliveryFee = decimal(proposal.delivery_fee, "delivery_fee");
  if (gap == null || deliveryFee == null) return null; // supplier terms not set: unknown, not zero
  const current = mapMoney(proposal.total_ex_vat, "total_ex_vat");
  // The gateway sends the gap, not the threshold: at a gap of 0 the threshold equals `current` here.
  return { threshold: Math.round((current + gap) * 100) / 100, current, deliveryFee };
}

/** The gateway `outcome` of a placed order. Anything but a known outcome is "unconfirmed", never "placed". */
function placedStatus(outcome: unknown): OrderStatus {
  if (outcome === "CONFIRMED") return "PLACED";
  return outcome === "NOT_SENT" || outcome === "SENT_READ_FAILED" ? outcome : "UNCONFIRMED";
}

/** docs/contract.md: only READY can be approved. PENDING is still being built; APPROVING/COMMITTING last while an approve runs. */
function proposalStatus(status: unknown): OrderStatus {
  if (status === "READY") return "NEEDS_APPROVAL";
  if (status === "PENDING" || status === "APPROVING" || status === "COMMITTING") return "IN_PROGRESS";
  if (status === "BLOCKED_BY_RECALL") return "BLOCKED_BY_RECALL";
  // Approved, but the caller found no order row: nobody may assume it was placed.
  return status === "APPROVED" ? "UNCONFIRMED" : "REFUSED";
}

/**
 * One UI order. The proposal carries the basket (lines with `why`, delivery date, totals);
 * the placed order, when there is one, carries the id and the outcome. An order whose
 * proposal is not at hand keeps its delivery date, ex-VAT total and delivery terms unknown.
 */
export function mapOrder(proposal: Json | null, placed: Json | null): Order {
  const source = proposal ?? placed ?? invalid("an order");
  const request = proposal ? object(proposal.request, "a proposal's request") : null;
  const deliveryDate = request ? text(request.requested_date, "requested_date") : null;
  if (!Array.isArray(source.lines)) invalid("order lines");
  return {
    id: text(placed ? placed.order_id : source.proposal_id, "an order id"),
    status: placed ? placedStatus(placed.outcome) : proposalStatus(source.status),
    urgency: "UNKNOWN",
    deliveryDate,
    lines: source.lines.map((line) => mapLine(object(line, "an order line"), deliveryDate ?? "")),
    totalExVat: proposal ? mapMoney(proposal.total_ex_vat, "total_ex_vat") : null,
    totalInclVat: mapMoney((placed ?? source).expected_total, "expected_total"),
    mov: proposal ? mapMov(proposal) : null,
    supplierOrderRef: placed ? resolutionRecord(placed.resolution)?.supplierOrderRef ?? null : null,
  };
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item !== "") : [];
}

function sourceUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function nullableNumber(value: unknown, label: string): number | null {
  if (value == null) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) invalid(label);
  return value;
}

function mapRecallCheck(check: Json): RecallCheck {
  if (check.source !== "live" && check.source !== "recording") invalid("a recall check source");
  const liveErrors = ["NO_KEY", "TIMEOUT", "UPSTREAM_ERROR", "BAD_ANSWER"];
  if (check.live_error != null && !liveErrors.includes(String(check.live_error))) invalid("a recall live_error");
  return {
    checkedAt: text(check.checked_at, "a recall checked_at"),
    checkedBy: nullableText(check.checked_by, "checked_by"),
    source: check.source,
    liveError: (check.live_error ?? null) as RecallCheck["liveError"],
    fetchedAt: text(check.fetched_at, "a recall fetched_at"),
    detailsFetchedAt: nullableText(check.details_fetched_at, "details_fetched_at"),
    via: text(check.via, "a recall via"),
    noticesScanned: nullableNumber(check.notices_scanned, "notices_scanned"),
    scannedSince: nullableText(check.scanned_since, "scanned_since"),
    noticesListed: nullableNumber(check.notices_listed, "notices_listed"),
    noticesUnread: nullableNumber(check.notices_unread, "notices_unread"),
  };
}

function mapRecallReplacement(value: unknown): RecallReplacement | null {
  if (value == null) return null;
  const replacement = object(value, "a recall replacement");
  if (!Array.isArray(replacement.lines)) invalid("recall replacement lines");
  return {
    orderId: text(replacement.proposal_id, "a replacement proposal_id"),
    status: text(replacement.status, "a replacement status"),
    expectedTotal: mapMoney(replacement.expected_total, "replacement expected_total"),
    lines: replacement.lines.map((value) => {
      const line = object(value, "a recall replacement line");
      return {
        productId: text(line.product_id, "a replacement product_id"),
        productName: nullableText(line.product_name, "replacement product_name"),
        quantity: mapMoney(line.quantity, "replacement quantity"),
        unit: text(line.unit, "a replacement unit"),
      };
    }),
  };
}

/** The two recall routes share this shape. An alert is repeated for each proposal it holds. */
export function mapRecalls(body: unknown): RecallList {
  const view = object(body, "a recall list");
  if (!Array.isArray(view.alerts)) invalid("recall alerts");
  const lastCheck = view.last_check == null ? null : mapRecallCheck(object(view.last_check, "a recall last_check"));
  const alerts = view.alerts.flatMap((value) => {
    const alert = object(value, "a recall alert");
    if (!Array.isArray(alert.proposals)) invalid("recall alert proposals");
    if (!Array.isArray(alert.replacement_proposal)) invalid("replacement_proposal");
    const match = alert.match;
    if (match !== "exact" && match !== "possible" && match !== "review") invalid("a recall match");
    const recall = object(alert.recall, "a recall notice");
    const base = {
      eventId: text(alert.event_id, "a recall event_id"),
      productId: text(alert.product_id, "a recall product_id"),
      productName: nullableText(alert.product_name, "recall product_name"),
      match: match as RecallMatch,
      why: typeof alert.why === "string" ? alert.why : "",
      where: strings(alert.where),
      recall: {
        url: sourceUrl(recall.url),
        date: nullableText(recall.date, "recall date"),
        title: nullableText(recall.title, "recall title"),
        reason: nullableText(recall.reason, "recall reason"),
        action: nullableText(recall.action, "recall action"),
        recalledProduct: nullableText(recall.recalled_product, "recalled_product"),
        brand: nullableText(recall.brand, "recall brand"),
        gtin: nullableText(recall.gtin, "recall gtin"),
        packageSize: nullableText(recall.package_size, "package_size"),
        lot: nullableText(recall.lot, "recall lot"),
      },
      nextStep: typeof alert.next_step === "string" ? alert.next_step : "",
      replacementIdeas: alert.replacement_proposal.map((value) => {
        const idea = object(value, "a replacement_proposal row");
        return {
          productId: text(idea.product_id, "a replacement idea product_id"),
          name: nullableText(idea.name, "replacement idea name"),
          brand: nullableText(idea.brand, "replacement idea brand"),
        };
      }),
      detectedAt: text(alert.detected_at, "a recall detected_at"),
      status: alert.status === "dismissed" ? ("dismissed" as const) : ("active" as const),
      dismissedBy: nullableText(alert.dismissed_by, "dismissed_by"),
      dismissedAt: nullableText(alert.dismissed_at, "dismissed_at"),
      dismissReason: nullableText(alert.dismiss_reason, "dismiss_reason"),
      lineStatus: match === "review" ? ("WARNING" as const) : ("BLOCKED_BY_RECALL" as const),
    };
    const proposals = alert.proposals.length ? alert.proposals : [null];
    return proposals.map((value) => {
      const proposal = value == null ? null : object(value, "a recall proposal");
      return {
        ...base,
        orderId: proposal ? text(proposal.proposal_id, "a recall proposal_id") : null,
        proposalStatus: proposal ? text(proposal.status, "a recall proposal status") : "UNKNOWN",
        replacement: mapRecallReplacement(proposal?.replacement),
        replanError: nullableText(proposal?.recall_replan_error, "recall_replan_error"),
      };
    });
  });
  return { lastCheck, alerts };
}

function approvalStatus(status: unknown): ApprovalRequest["status"] {
  if (status === "APPROVED") return "APPROVED";
  const order = proposalStatus(status);
  if (order === "NEEDS_APPROVAL") return "PENDING";
  return order === "IN_PROGRESS" || order === "BLOCKED_BY_RECALL" ? order : "REJECTED";
}

/**
 * The approval card for one proposal. `events` is the kitchen's audit log: the proposal
 * itself does not say who asked or when, the event that created it does.
 */
export function mapApproval(proposal: Json, events: Json[] = []): ApprovalRequest {
  const id = text(proposal.proposal_id, "proposal_id");
  const request = object(proposal.request, "a proposal's request");
  const mandate = object(proposal.mandate, "a proposal's mandate");
  const created = events.find(
    (event) => event.proposal_id === id && (event.kind === "proposal_created" || event.kind === "approval_requested"),
  );
  const reasons = [
    ...strings(mandate.reasons).map((rule) => ({ rule, detail: "" })),
    ...strings(mandate.warnings).map((rule) => ({
      rule,
      detail: "A warning. It does not block the order.",
      warning: true,
    })),
  ];
  const productNames = new Map<string, string>();
  if (Array.isArray(proposal.lines)) {
    for (const line of proposal.lines) {
      if (typeof line?.product_id === "string" && typeof line.product_name === "string") {
        productNames.set(line.product_id, line.product_name);
      }
    }
  }
  return {
    id,
    // The approval's order is the proposal's basket; a placed order gets its own id in `listOrders`.
    orderId: id,
    requestedBy: typeof created?.actor === "string" ? created.actor : "unknown",
    createdAt: typeof created?.at === "string" ? created.at : null,
    summary:
      typeof request.text === "string" && request.text.trim()
        ? request.text.trim()
        : `${String(request.quantity)} ${String(request.unit)}`,
    lineCount: Array.isArray(proposal.lines) ? proposal.lines.length : invalid("proposal lines"),
    deliveryDate: text(request.requested_date, "requested_date"),
    totalExVat: mapMoney(proposal.total_ex_vat, "total_ex_vat"),
    totalInclVat: mapMoney(proposal.expected_total, "expected_total"),
    reasons: reasons.length
      ? reasons
      : [{ rule: "A person approves every order", detail: "Nothing is sent until you approve the exact total." }],
    status: approvalStatus(proposal.status),
    options: mapProposalOptions(
      proposal.substitute_options,
      typeof proposal.offer_id === "string" ? proposal.offer_id : undefined,
      productNames,
    ),
  };
}

const TOOL_KINDS: Record<string, AuditKind> = {
  search_products: "search",
  get_offer: "offer",
  simulate_order: "simulate",
  request_approval: "approval",
  place_order: "order",
  get_order_status: "order",
};

/** #899: what the Buyer did, in plain words; an unknown tool keeps its raw name. */
const TOOL_VERBS: Record<string, string> = {
  search_products: "searched the catalog",
  get_offer: "asked for an offer",
  simulate_order: "simulated the order",
  request_approval: "asked for approval",
  place_order: "placed the order",
  get_order_status: "checked the order status",
};

function toolSummary(tool: string, finished: boolean, failed: boolean): string {
  const verb = Object.hasOwn(TOOL_VERBS, tool) ? TOOL_VERBS[tool] : undefined;
  if (!verb) return !finished ? `Buyer called ${tool}` : failed ? `${tool} failed` : `${tool} finished`;
  return !finished ? `Buyer ${verb}` : failed ? `Buyer ${verb}: failed` : `Buyer ${verb}: done`;
}

const EVENT_KINDS: Record<string, { kind: AuditKind; summary: string }> = {
  proposal_created: { kind: "request", summary: "Proposal created" },
  approval_requested: { kind: "approval", summary: "Approval requested" },
  decision_summary: { kind: "mandate_check", summary: "Decision summary" },
  total_mismatch: { kind: "simulate", summary: "The total moved before placing: nothing was sent" },
  order_placed: { kind: "order", summary: "Order placed" },
  proposal_rejected: { kind: "approval", summary: "Proposal rejected" },
  // #548: a 403 to the agent or a kitchen API token; the details (code, method, path) are the reason.
  refused: { kind: "refused", summary: "Refused: the gateway said no (403)" },
  // #899: kinds added on 14 Nov; the stored events keep their raw names.
  stock_photo_read: { kind: "stock", summary: "Shelf photo read by Nemotron VL" },
  audit_demo_tamper: { kind: "other", summary: "Tamper demo: a line was changed" },
  audit_demo_restore: { kind: "other", summary: "Tamper demo: the line was restored" },
  option_chosen: { kind: "approval", summary: "A person chose an option" },
  order_lookup: { kind: "order", summary: "A person looked up an order with an unknown send result" },
  order_resolved: { kind: "order", summary: "A person resolved an unknown send" },
  recall_check: { kind: "other", summary: "Recall check" },
  demo_inbox_cleared: { kind: "other", summary: "Test proposals cleared before a demo" },
};

/** `expected_total: 148.76; verdict: NEEDS_APPROVAL`: the gateway's own values, as sent. */
function describe(fields: unknown): string {
  const parts = Object.entries(fields && typeof fields === "object" ? fields : {}).map(
    ([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`,
  );
  return parts.join("; ") || "No details recorded.";
}

function mapAuditEvent(event: Json): AuditEvent {
  const base = {
    id: text(event.event_id, "an audit event_id"),
    // Agent tool events carry no `at` today: the time is unknown, not "now".
    at: typeof event.at === "string" ? event.at : null,
    orderId: [event.order_id, event.proposal_id].find((id): id is string => typeof id === "string"),
  };
  if (typeof event.tool === "string") {
    const finished = event.type === "tool_call_finished";
    const error = object(event.result ?? {}, "an audit result").error;
    return {
      ...base,
      kind: TOOL_KINDS[event.tool] ?? "other",
      actor: "agent",
      summary: toolSummary(event.tool, finished, error != null),
      reason: describe(finished ? event.result : event.arguments),
    };
  }
  const {
    seq: _seq,
    event_id: _id,
    kind,
    actor,
    at: _at,
    order_id: _order,
    proposal_id: _proposal,
    offer_id: _offer,
    ...rest
  } = event;
  const known = typeof kind === "string" && Object.hasOwn(EVENT_KINDS, kind) ? EVENT_KINDS[kind] : undefined;
  return {
    ...base,
    kind: known?.kind ?? "other",
    actor:
      actor === "buyer-agent"
        ? "agent"
        : actor === "chef"
          ? "chef"
          : typeof actor === "string" && !actor.startsWith("token:")
            ? "human"
            : "system",
    summary: known?.summary ?? (typeof kind === "string" ? kind : "Unknown step"),
    reason:
      typeof rest.summary === "string"
        ? rest.summary
        : typeof rest.reason === "string" && rest.reason
          ? rest.reason
          : describe(rest),
  };
}

/** The kitchen's audit log, or one order's steps: its own and those of the proposal that placed it. */
export function mapAudit(events: Json[], orderId?: string): AuditEvent[] {
  if (orderId == null) return events.map(mapAuditEvent);
  const ids = new Set<unknown>([
    orderId,
    ...events.flatMap((event) =>
      event.order_id === orderId && typeof event.proposal_id === "string" ? [event.proposal_id] : [],
    ),
  ]);
  return events.filter((event) => ids.has(event.order_id) || ids.has(event.proposal_id)).map(mapAuditEvent);
}

const AUDIT_KINDS = new Set<string>([
  "request",
  "search",
  "offer",
  "simulate",
  "mandate_check",
  "approval",
  "order",
  "stock",
  "forecast_share",
  "settings",
  "refused",
  "other",
] satisfies AuditKind[]);

/** `GET /permissions` (gateway/permissions.py). A kind the UI does not know (e.g. `token_created`) shows as "other". */
export function mapPermissions(body: unknown): BuyerPermissions {
  const group = (key: keyof BuyerPermissions): PermissionRow[] =>
    rows(body, key).map((row) => ({
      action: text(row.action, "a permission action"),
      auditKind: (typeof row.audit_kind === "string" && AUDIT_KINDS.has(row.audit_kind)
        ? row.audit_kind
        : "other") as AuditKind,
      ...(typeof row.rule === "string" ? { rule: row.rule } : {}),
    }));
  return { alone: group("alone"), person: group("person"), never: group("never") };
}

/** `GET /proposals/{id}/addable`. A row the gateway marks not addable (no price) is left out. */
export function mapAddable(body: unknown, requestedDate: string): AddableProduct[] {
  return rows(body, "rows")
    .filter((row) => row.addable === true && row.suggested_qty != null)
    .map((row) => {
      const id = text(row.product_id, "an addable product_id");
      const unit = text(row.unit, "an addable unit");
      return {
        product: productOf(id, typeof row.name === "string" && row.name ? row.name : null, unit),
        offer: offerOf(id, unit, requestedDate, decimal(row.unit_price, "unit_price"), false),
        onHand: decimal(row.on_hand, "on_hand"),
        onOrder: decimal(row.on_order, "on_order"),
        suggestedQuantity: mapMoney(row.suggested_qty, "suggested_qty"),
        why: typeof row.why === "string" ? row.why : "",
      };
    });
}
