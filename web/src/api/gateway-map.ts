import { mapMoney } from "@/api/map";
import { readDeliveryFacts } from "@/api/delivery-facts";
import { mapProposalOptions } from "@/api/map-options";
import { mapModelTrace } from "@/api/model-trace";
import { SUPPLIER_ID } from "@/api/supplier-id";
import { ApiError } from "@/api/types";
import { CODE_LABELS, codeLabel, plainReason } from "@/lib/codes";
import { formatDate } from "@/lib/format";
import type {
  AddableProduct,
  ApprovalRequest,
  AuditEvent,
  AuditKind,
  BuyerPermissions,
  MandateReason,
  MovState,
  Offer,
  Order,
  OrderLine,
  OrderReceipt,
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
  // Cut-off, lead time and reliability to show (#1453); an older proposal has none of them.
  const facts = readDeliveryFacts(row);
  return {
    product: productOf(id, nullableText(row.product_name, "product_name"), unit),
    offer: {
      // Only `unknown_stock: false` is a confirmation. The amount in stock is not sent.
      ...offerOf(id, unit, requestedDate, decimal(row.unit_price, "unit_price"), row.unknown_stock === false),
      closingTime: facts.cutoffAt,
      cutoffSource: facts.cutoffSource,
      leadTimeDays: facts.leadTimeDays,
      leadTimeSource: facts.leadTimeSource,
      deliveryReliability: facts.deliveryReliability,
      reliabilitySource: facts.reliabilitySource,
    },
    quantity: mapMoney(row.quantity, "quantity"),
    lineTotal: decimal(row.total, "line total"),
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

/**
 * `total_incl_vat` and the names of the `vat_unknown` lines (docs/contract.md "VAT per product").
 * Nothing when the answer does not send `total_incl_vat` (an older gateway).
 */
function vatTotals(answer: Json | null, lines: unknown[]): { inclVat?: number | null; vatUnknown?: string[] } {
  if (!answer || !("total_incl_vat" in answer)) return {};
  const names = new Map<string, string>();
  for (const line of lines) {
    const row = line && typeof line === "object" ? (line as Json) : {};
    if (typeof row.product_id === "string" && typeof row.product_name === "string" && row.product_name) {
      names.set(row.product_id, row.product_name);
    }
  }
  const unknown = strings(answer.vat_unknown).map((id) => names.get(id) ?? id);
  const inclVat = decimal(answer.total_incl_vat, "total_incl_vat");
  // Unknown is never a figure: a null total, or any unknown line, shows "incl VAT: unknown".
  return { inclVat: unknown.length ? null : inclVat, vatUnknown: unknown };
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
 * proposal is not at hand takes its totals from the order row and keeps its delivery date and
 * delivery terms unknown.
 */
export function mapOrder(proposal: Json | null, placed: Json | null): Order {
  const source = proposal ?? placed ?? invalid("an order");
  const request = proposal ? object(proposal.request, "a proposal's request") : null;
  const deliveryDate = request ? text(request.requested_date, "requested_date") : null;
  if (!Array.isArray(source.lines)) invalid("order lines");
  const shortfall = decimal(source.shortfall, "shortfall");
  // #1630: the order answer carries its own totals; the proposal only fills what it does not send.
  const own = (key: string): unknown => (placed && key in placed ? placed[key] : proposal?.[key]);
  return {
    id: text(placed ? placed.order_id : source.proposal_id, "an order id"),
    status: placed ? placedStatus(placed.outcome) : proposalStatus(source.status),
    urgency: "UNKNOWN",
    deliveryDate,
    lines: source.lines.map((line) => mapLine(object(line, "an order line"), deliveryDate ?? "")),
    supplierMustConfirm: placed ? strings(placed.supplier_must_confirm) : [],
    totalExVat: decimal(own("total_ex_vat"), "total_ex_vat"),
    vat: decimal(own("vat"), "vat"),
    deliveryFee: decimal(own("delivery_fee"), "delivery_fee"),
    // The approve figure; the screen shows `inclVat` (or "unknown") as incl VAT (#1630).
    totalInclVat: mapMoney((placed ?? source).expected_total, "expected_total"),
    ...vatTotals(placed && "total_incl_vat" in placed ? placed : proposal, source.lines),
    shortfall:
      shortfall !== null && shortfall > 0 && typeof source.measure === "string" && source.measure
        ? { amount: shortfall, unit: source.measure }
        : null,
    mov: proposal ? mapMov(proposal) : null,
    supplierOrderRef: placed ? resolutionRecord(placed.resolution)?.supplierOrderRef ?? null : null,
    ...(placed ? { receipt: mapReceipt(placed.receipt) } : {}),
    ...(placed?.placed_by === "demo-seed" ? { placedBy: "demo-seed" as const } : {}),
    // Aron, 14 Nov: repeated demo orders of one product show what was asked, and when.
    requestText: typeof request?.text === "string" && request.text.trim() ? request.text.trim() : null,
    createdAt: placed ? nullableText(placed.created_at, "created_at") : null,
    ...(proposal ? {} : { withoutProposal: true as const }),
  };
}

/** The JWS payload as JSON, or null when it cannot be read. Display only: no signature check. */
function receiptClaims(jws: string): Json | null {
  const parts = jws.split(".");
  if (parts.length !== 3 || !parts[1]) return null;
  try {
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "="));
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    const claims: unknown = JSON.parse(new TextDecoder().decode(bytes));
    return claims && typeof claims === "object" && !Array.isArray(claims) ? (claims as Json) : null;
  } catch {
    return null;
  }
}

/** `receipt` of an order answer: a compact JWS, or null for old orders and failed signing. */
export function mapReceipt(value: unknown): OrderReceipt | null {
  if (value == null || value === "") return null;
  const jws = text(value, "an order receipt");
  const claims = receiptClaims(jws) ?? {};
  const iat = claims.iat;
  let total: number | null = null;
  try {
    total = decimal(claims.expected_total, "receipt expected_total");
  } catch {
    total = null;
  }
  return {
    jws,
    approvedBy: typeof claims.approved_by === "string" && claims.approved_by ? claims.approved_by : null,
    signedAt: typeof iat === "number" && Number.isFinite(iat) ? new Date(iat * 1000).toISOString() : null,
    total,
    supplierOutcome:
      typeof claims.supplier_outcome === "string" && claims.supplier_outcome ? claims.supplier_outcome : null,
    supplierNote: typeof claims.supplier_note === "string" && claims.supplier_note ? claims.supplier_note : null,
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
 * Reason codes a person must check before approving, in plain words for "What to check".
 * Unknown is never "safe": a code here is shown even when `mandate.reasons` says nothing.
 */
const CHECK_CODES: Record<string, { rule: string; detail: string }> = {
  ALLERGEN_DATA_MISSING: {
    rule: "Allergen data missing",
    detail: "The catalog has no allergen data for one or more products. Check the label.",
  },
};

const WARNING_CODES: Record<string, { rule: string; detail: string }> = {
  OVER_BUDGET_WARNING: {
    rule: "The total is above your kitchen's budget warning.",
    detail: "A warning only. It does not block the order.",
  },
  CERTAINTY_PREMIUM_HIGH: {
    rule: "Confirmed stock costs more than your kitchen's allowed premium over the cheapest option, but it is needed to fill the order.",
    detail: "A warning only. It does not block the order.",
  },
};

/** Audit actors that are not a person's name, in words for "asked by". */
const ACTOR_NAMES: Record<string, string> = {
  "buyer-agent": "the Buyer agent",
  "demo-visitor": "a demo visitor",
  "demo-seed": "the demo setup",
  human: "a person",
  chef: "the chef",
};

/**
 * Who asked for a proposal, in words, or null when nothing says so. The audit actor wins;
 * without it, a supplier offer proposal (its text is written by the gateway,
 * gateway/supplier_offers.py) came from Valio's selling agent.
 */
export function askedBy(actor: unknown, request: Json): string | null {
  if (typeof actor === "string" && actor.trim()) {
    if (actor.startsWith("supplier:")) return "Valio's selling agent";
    if (actor.startsWith("token:")) return "an API client";
    return ACTOR_NAMES[actor] ?? actor;
  }
  if (typeof request.text === "string" && request.text.startsWith("Offer from ")) return "Valio's selling agent";
  return null;
}

export function mapSuppliersToConfirm(proposal: { blocks?: unknown }): ApprovalRequest["suppliersToConfirm"] {
  if (!Array.isArray(proposal.blocks)) return [];
  return proposal.blocks.flatMap((block) => {
    if (
      !block ||
      typeof block.supplier_id !== "string" ||
      !block.supplier_id ||
      block.supplier_id === SUPPLIER_ID ||
      !Array.isArray(block.lines) ||
      !block.lines.some((line: Json | null) => line?.unknown_stock === true)
    ) {
      return [];
    }
    return [{
      supplierId: block.supplier_id,
      name: typeof block.name === "string" && block.name ? block.name : block.supplier_id,
      count: block.lines.filter((line: Json | null) => line?.unknown_stock === true).length,
    }];
  });
}

/** #1899: how many lines of Valio's own block have unknown stock; undefined when no blocks were sent. */
export function mapValioToConfirm(proposal: { blocks?: unknown }): number | undefined {
  if (!Array.isArray(proposal.blocks) || proposal.blocks.length === 0) return undefined;
  return proposal.blocks.reduce((sum: number, block: Json | null) => {
    if (!block || block.supplier_id !== SUPPLIER_ID || !Array.isArray(block.lines)) return sum;
    return sum + block.lines.filter((line: Json | null) => line?.unknown_stock === true).length;
  }, 0);
}

/** #1858: each supplier block's own delivery fee above zero, as the gateway sent it (never a sum). */
export function mapBlockDeliveryFees(proposal: { blocks?: unknown }): NonNullable<ApprovalRequest["blockDeliveryFees"]> {
  if (!Array.isArray(proposal.blocks)) return [];
  return proposal.blocks.flatMap((block) => {
    const amount = block ? decimal(block.delivery_fee, "delivery_fee") : null;
    const supplierName = typeof block?.name === "string" && block.name ? block.name : block?.supplier_id;
    return amount !== null && amount > 0 && typeof supplierName === "string" && supplierName
      ? [{ supplierName, amount }]
      : [];
  });
}

/** #1227: a known product's name in place of its code, and any code after it in words. */
function approvalReason(rule: string, productNames: ReadonlyMap<string, string>): MandateReason {
  // A bare known code gets its title and detail, as CHECK_CODES does, so both go through t().
  if (Object.hasOwn(CODE_LABELS, rule)) return { rule: CODE_LABELS[rule].title, detail: CODE_LABELS[rule].detail };
  return { rule: productReason(rule, productNames), detail: "" };
}

function productReason(rule: string, productNames: ReadonlyMap<string, string>): string {
  const plain = plainReason(rule, productNames);
  if (plain !== rule) return plain;
  const [, productId, rest] = /^([^:]+): (.*)$/s.exec(rule) ?? [];
  const name = productId == null ? undefined : productNames.get(productId);
  return name ? `${name}: ${rest}` : rule;
}

/** #1970: the request's own quantity and unit; null when it has no single quantity (a list of items). */
function mapAsked(request: Json): ApprovalRequest["asked"] {
  if (request.quantity == null || typeof request.unit !== "string" || !request.unit) return null;
  const quantity = Number(request.quantity);
  if (!Number.isFinite(quantity) || quantity <= 0) return null;
  return { quantity, unit: request.unit, confirmedPartOnly: request.made_by === "confirmed_only" };
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
  const rejected = events.find((event) => event.proposal_id === id && event.kind === "proposal_rejected");
  const rejectReason = [proposal.reason, rejected?.reason].find(
    (value): value is string => typeof value === "string" && value.trim() !== "",
  );
  const codes = new Set(strings(mandate.reason_codes));
  if (Array.isArray(proposal.lines)) {
    for (const line of proposal.lines) for (const code of strings(line?.reason_codes)) codes.add(code);
  }
  const productNames = new Map<string, string>();
  if (Array.isArray(proposal.lines)) {
    for (const line of proposal.lines) {
      if (typeof line?.product_id === "string" && typeof line.product_name === "string" && line.product_name) {
        productNames.set(line.product_id, line.product_name);
      }
    }
  }
  if (Array.isArray(proposal.excluded)) {
    for (const line of proposal.excluded) {
      if (typeof line?.product_id !== "string" || productNames.has(line.product_id)) continue;
      const name = typeof line.product_name === "string" && line.product_name ? line.product_name : line.name;
      if (typeof name === "string" && name) productNames.set(line.product_id, name);
    }
  }
  const supplierNames = new Map<string, string>();
  if (Array.isArray(proposal.blocks)) {
    for (const block of proposal.blocks) {
      if (!block || typeof block.supplier_id !== "string" || !Array.isArray(block.lines)) continue;
      const name =
        block.supplier_id === SUPPLIER_ID
          ? "Valio"
          : typeof block.name === "string" && block.name
            ? block.name
            : block.supplier_id || null;
      if (name == null) continue;
      for (const line of block.lines) {
        if (typeof line?.product_id === "string") supplierNames.set(line.product_id, name);
      }
    }
  }
  // #1142: no raw code reaches the screen, in a gateway reason or as an unknown warning.
  const reasons = [
    ...strings(mandate.reasons).map((rule) => approvalReason(rule, productNames)),
    ...Object.entries(CHECK_CODES)
      .filter(([code]) => codes.has(code))
      .map(([, reason]) => reason),
    ...strings(mandate.warnings).map((code) => ({
      ...(WARNING_CODES[code] ?? { rule: codeLabel(code).title, detail: "A warning. It does not block the order." }),
      warning: true,
    })),
  ];
  return {
    id,
    approvalRef: typeof proposal.approval_id === "string" && proposal.approval_id ? proposal.approval_id : null,
    // The approval's order is the proposal's basket; a placed order gets its own id in `listOrders`.
    orderId: id,
    requestedBy: askedBy(created?.actor, request),
    createdAt: typeof created?.at === "string" && created.at ? created.at : null,
    summary:
      typeof request.text === "string" && request.text.trim()
        ? request.text.trim()
        : `${String(request.quantity)} ${String(request.unit)}`,
    lineCount: Array.isArray(proposal.lines) ? proposal.lines.length : invalid("proposal lines"),
    deliveryDate: text(request.requested_date, "requested_date"),
    totalExVat: mapMoney(proposal.total_ex_vat, "total_ex_vat"),
    // The approve figure, sent back on approve; `inclVat` is what the screen calls incl VAT (#1630).
    totalInclVat: mapMoney(proposal.expected_total, "expected_total"),
    ...vatTotals(proposal, Array.isArray(proposal.lines) ? proposal.lines : []),
    asked: mapAsked(request),
    reasons: reasons.length
      ? reasons
      : [{ rule: "A person approves every order", detail: "Nothing is sent until you approve the exact total." }],
    suppliersToConfirm: mapSuppliersToConfirm(proposal),
    valioToConfirm: mapValioToConfirm(proposal),
    blockDeliveryFees: mapBlockDeliveryFees(proposal),
    rejectReason: proposal.status === "REJECTED" ? (rejectReason?.trim() ?? null) : null,
    cutoffs: Array.isArray(proposal.lines)
      ? proposal.lines.map((line) => ({
          closingTime: nullableText(line?.closing_time, "closing_time"),
          supplierName: typeof line?.product_id === "string" ? supplierNames.get(line.product_id) ?? null : null,
          productId: typeof line?.product_id === "string" ? line.product_id : null,
        }))
      : undefined,
    status: approvalStatus(proposal.status),
    options: mapProposalOptions(
      proposal.substitute_options,
      typeof proposal.offer_id === "string" ? proposal.offer_id : undefined,
      productNames,
    ),
    modelTrace: mapModelTrace((proposal as { model_trace?: unknown }).model_trace),
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

/** #899: what the Buyer did with each tool, in plain words. An unknown tool keeps its raw name. */
const TOOL_VERBS: Record<string, { started: string; done: string }> = {
  search_products: { started: "Buyer is searching the catalog", done: "Buyer searched the catalog" },
  get_offer: { started: "Buyer is asking for an offer", done: "Buyer got the offer" },
  simulate_order: { started: "Buyer is simulating the order", done: "Buyer simulated the order" },
  request_approval: { started: "Buyer is asking for approval", done: "Buyer asked for approval" },
  place_order: { started: "Buyer is placing the order", done: "Buyer placed the order" },
  get_order_status: { started: "Buyer is checking the order status", done: "Buyer checked the order status" },
};

/**
 * The plain label of each event kind the Python code writes to the audit log. A kind that
 * `lib/codes.ts` names (`kitchen_brief_read`, ...) is not here: `plainCode` gives its title.
 * `event-labels.test.ts` reads the kinds from the sources (#1776): a new kind needs a line
 * here and a Finnish text in `i18n/fi/audit-events.ts`.
 */
export const EVENT_KINDS: Record<string, { kind: AuditKind; summary: string; internal?: true }> = {
  // #899: kinds added on 14 Nov, with a plain-English label each.
  stock_photo_read: { kind: "stock", summary: "Shelf photo read by Nemotron VL" },
  audit_demo_tamper: { kind: "other", summary: "Tamper demo: a line was changed" },
  audit_demo_restore: { kind: "other", summary: "Tamper demo: the line was restored" },
  option_chosen: { kind: "approval", summary: "A person chose an option" },
  order_lookup: { kind: "order", summary: "Order status checked" },
  order_resolved: { kind: "order", summary: "A person resolved an unknown send" },
  recall_check: { kind: "other", summary: "Recall check" },
  // #1978: `internal` steps stay in the full activity log and are left out of Home's Latest steps.
  demo_inbox_cleared: { kind: "other", summary: "Demo inbox reset before a rehearsal", internal: true },
  signed_in: { kind: "other", summary: "Signed in" },
  password_changed: { kind: "settings", summary: "Password changed" },
  kitchen_brief_read: { kind: "request", summary: "Kitchen brief read" },
  delivery_note_read: { kind: "order", summary: "Delivery note read" },
  proposal_created: { kind: "request", summary: "Proposal created" },
  proposal_explanation_failed: { kind: "request", summary: "No model sentence for a proposal", internal: true },
  approval_requested: { kind: "approval", summary: "Approval requested" },
  decision_summary: { kind: "mandate_check", summary: "Decision summary" },
  total_mismatch: { kind: "simulate", summary: "The total moved before placing: nothing was sent" },
  order_placed: { kind: "order", summary: "Order placed" },
  proposal_rejected: { kind: "approval", summary: "Proposal rejected" },
  // #548: a 403 to the agent or a kitchen API token; the details (code, method, path) are the reason.
  // The gateway writes this kind only for a 403 (gateway/app.py), so "status: 403" below is its own fact.
  refused: { kind: "refused", summary: "Request refused by the gateway" },
  // #374: a supplier's selling agent suggests a substitute; only a person turns it into a proposal.
  supplier_offer_received: { kind: "offer", summary: "Offer received from the supplier's selling agent" },
  supplier_offer_accepted: { kind: "offer", summary: "Supplier offer accepted: a proposal was made from it" },
  supplier_offer_declined: { kind: "offer", summary: "Supplier offer declined" },
  proposal_withdrawn: { kind: "approval", summary: "Proposal withdrawn: the supplier offer was declined meanwhile" },
  // Mock jury, 14 Nov: Home showed raw kinds such as `approval_token_created`.
  approval_token_created: { kind: "settings", summary: "Personal approval token created" },
  approval_token_revoked: { kind: "settings", summary: "Personal approval token revoked" },
  token_created: { kind: "settings", summary: "Kitchen API token created" },
  token_revoked: { kind: "settings", summary: "Kitchen API token revoked" },
  webhook_created: { kind: "settings", summary: "Webhook added" },
  webhook_deleted: { kind: "settings", summary: "Webhook removed" },
  settings_changed: { kind: "settings", summary: "Settings changed" },
  auto_approve_changed: { kind: "settings", summary: "Auto-approve setting changed" },
  auto_approved: { kind: "approval", summary: "Approved automatically within the limit" },
  auto_approve_skipped: { kind: "approval", summary: "Not approved automatically: a person decides" },
  alias_set: { kind: "settings", summary: "Product name for the kitchen saved" },
  alias_removed: { kind: "settings", summary: "Product name for the kitchen removed" },
  proposal_changed: { kind: "request", summary: "Proposal changed" },
  proposal_explanation_ready: { kind: "request", summary: "Proposal explained" },
  menu_photo_read: { kind: "request", summary: "Menu photo read by Nemotron VL" },
  menu_photo_failed: { kind: "request", summary: "Menu photo could not be read" },
  menu_plan_changed: { kind: "request", summary: "Menu plan changed" },
  stock_counted: { kind: "stock", summary: "Stock counted" },
  stock_photo_failed: { kind: "stock", summary: "Shelf photo could not be read" },
  label_photo_read: { kind: "stock", summary: "Label photo read by Nemotron VL" },
  label_photo_failed: { kind: "stock", summary: "Label photo could not be read" },
  price_list_photo_read: { kind: "offer", summary: "Price list photo read by Nemotron VL" },
  price_list_photo_failed: { kind: "offer", summary: "Price list photo could not be read" },
  delivery_note_failed: { kind: "order", summary: "Delivery note could not be read" },
  delivery_result_saved: { kind: "order", summary: "Delivery check saved" },
  approve_rollback_failed: { kind: "order", summary: "An approval could not be undone after a failed send" },
  stuck_commit_released: { kind: "order", summary: "A stuck order send was released" },
  superseded_commit_discarded: { kind: "order", summary: "A late duplicate approval was discarded; no second order" },
  demo_delivery_order_placed: { kind: "order", summary: "Demo delivery order placed by the demo seed" },
  demo_offers_reset: { kind: "other", summary: "Demo supplier offers reset" },
  learned_fact_applied: { kind: "other", summary: "A learned fact changed a proposal" },
  learned_fact_switched_off: { kind: "settings", summary: "A learned fact was switched off" },
  recall_dismissed: { kind: "other", summary: "Recall alert dismissed" },
  recall_proposal_blocked: { kind: "approval", summary: "Proposal blocked by a recall" },
  recall_replacement_proposed: { kind: "request", summary: "Replacement proposed for a recalled product" },
  recall_replacement_rejected: { kind: "approval", summary: "Replacement for a recalled product rejected" },
  replacement_enriched: { kind: "other", summary: "Replacement product details added" },
  replacement_enrichment_unknown: { kind: "other", summary: "Replacement product details not found" },
  // #1776: the kinds the source scan found without a label.
  suppliers_created: { kind: "settings", summary: "Supplier added" },
  suppliers_changed: { kind: "settings", summary: "Supplier changed" },
  suppliers_deleted: { kind: "settings", summary: "Supplier removed" },
  recipes_created: { kind: "settings", summary: "Recipe added" },
  recipes_changed: { kind: "settings", summary: "Recipe changed" },
  recipes_deleted: { kind: "settings", summary: "Recipe removed" },
  products_created: { kind: "settings", summary: "Own product added" },
  products_changed: { kind: "settings", summary: "Own product changed" },
  products_deleted: { kind: "settings", summary: "Own product removed" },
  // These two rows and the recall alert carry a `type`, not a `kind`.
  share_granted: { kind: "forecast_share", summary: "Forecast sharing with the supplier switched on" },
  share_revoked: { kind: "forecast_share", summary: "Forecast sharing with the supplier switched off" },
  "recall.alert": { kind: "other", summary: "Recall alert" },
};

const SNAKE_CASE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/;

/** A kind with no label of its own: a code `plainCode` knows stays as it is, other snake_case reads as words. */
function kindWords(kind: string): string {
  if (Object.hasOwn(CODE_LABELS, kind) || !SNAKE_CASE.test(kind)) return kind;
  const text = kind.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** `expected_total: 148.76; verdict: NEEDS_APPROVAL`: the gateway's own values, as sent. */
function describe(fields: unknown): string {
  let values = fields;
  if (typeof fields === "string") {
    try {
      values = JSON.parse(fields);
    } catch {
      values = fields;
    }
  }
  const parts = Object.entries(values && typeof values === "object" ? values : {}).map(
    ([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`,
  );
  return parts.join("; ") || "No details recorded.";
}

function record(value: unknown): Json | null {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Json;
  if (typeof value !== "string") return null;
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Json) : null;
  } catch {
    return null;
  }
}

function auditId(value: unknown): string | null {
  if (typeof value !== "string" || !value) return null;
  const parsed = record(value);
  if (parsed) return null;
  try {
    const unquoted: unknown = JSON.parse(value);
    return typeof unquoted === "string" && unquoted ? unquoted : value;
  } catch {
    return value;
  }
}

function groupIds(value: unknown, key?: string, ids: string[] = []): string[] {
  if (key === "run_id" || key === "offer_id" || key === "proposal_id" || key === "order_id") {
    const id = auditId(value);
    if (id && !ids.includes(id)) ids.push(id);
    return ids;
  }
  const row = record(value);
  if (row) for (const [childKey, child] of Object.entries(row)) groupIds(child, childKey, ids);
  else if (Array.isArray(value)) for (const child of value) groupIds(child, key, ids);
  return ids;
}

function toolReason(tool: string, value: unknown): string {
  const args = record(value);
  if (!args) return "";
  if (tool === "search_products") {
    return typeof args.query === "string" && args.query ? `Looking for “${args.query}”` : "";
  }
  if (tool !== "get_offer") return "";
  const count = Array.isArray(args.product_ids) ? args.product_ids.length : null;
  const requestedDate = typeof args.requested_date === "string" ? args.requested_date : null;
  const date =
    requestedDate && /^\d{4}-\d{2}-\d{2}$/.test(requestedDate) && Number.isFinite(Date.parse(`${requestedDate}T12:00:00+02:00`))
      ? formatDate(requestedDate)
      : null;
  const products = count == null ? null : count === 1 ? "1 product" : `${count} products`;
  if (products && date) return `${products} for ${date}`;
  if (products) return products;
  return date ? `For ${date}` : "";
}

function mapAuditEvent(event: Json): AuditEvent {
  const base = {
    id: text(event.event_id, "an audit event_id"),
    // Agent tool events carry no `at` today: the time is unknown, not "now".
    at: typeof event.at === "string" ? event.at : null,
    orderId: [event.order_id, event.proposal_id].find((id): id is string => typeof id === "string"),
    groupIds: groupIds(event),
  };
  if (typeof event.tool === "string") {
    const finished = event.type === "tool_call_finished";
    const result = record(event.result ?? {});
    if (!result) invalid("an audit result");
    const error = result.error;
    const verb = Object.hasOwn(TOOL_VERBS, event.tool) ? TOOL_VERBS[event.tool] : undefined;
    return {
      ...base,
      kind: TOOL_KINDS[event.tool] ?? "other",
      actor: "agent",
      reason: toolReason(event.tool, event.arguments),
      details: describe(finished ? event.result : event.arguments),
      summary: !finished
        ? (verb?.started ?? `Buyer called ${event.tool}`)
        : error == null
          ? (verb?.done ?? `${event.tool} finished`)
          : verb
            ? `${verb.done}: it failed`
            : `${event.tool} failed`,
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
  // An older row has a `type` and no `kind` (`share_granted`, `recall.alert`): it names the step too.
  const name = typeof kind === "string" ? kind : typeof rest.type === "string" ? rest.type : undefined;
  const known = name !== undefined && Object.hasOwn(EVENT_KINDS, name) ? EVENT_KINDS[name] : undefined;
  const humanReason =
    typeof rest.summary === "string"
      ? rest.summary
      : typeof rest.reason === "string" && rest.reason
        ? rest.reason
        : "";
  const details = humanReason
    ? Object.fromEntries(
        Object.entries(rest).filter(([key]) => key !== (typeof rest.summary === "string" ? "summary" : "reason")),
      )
    : rest;
  return {
    ...base,
    // With sign-in on, the gateway's actor is the account's email: the log says who, not only "a person".
    ...(typeof actor === "string" && actor.includes("@") && !actor.includes(":") ? { actorName: actor } : {}),
    ...(known?.internal ? { internal: true as const } : {}),
    kind: known?.kind ?? "other",
    actor:
      actor === "buyer-agent"
        ? "agent"
        : actor === "chef"
          ? "chef"
          : typeof actor === "string" && actor.startsWith("supplier:")
            ? "valio"
            : typeof actor === "string" && !actor.startsWith("token:")
              ? "human"
            : "system",
    summary: known?.summary ?? (name !== undefined ? kindWords(name) : "Unknown step"),
    reason: humanReason || (typeof kind === "string" && kind.startsWith("supplier_offer_") ? describe(rest) : ""),
    details: describe(kind === "refused" ? { status: 403, ...details } : details),
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
