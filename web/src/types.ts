/**
 * Data shapes the UI renders. They follow the Valio upstream fields
 * (docs/contract.md) and our own gateway concepts (order, approval, audit),
 * so the mocks in `src/mocks/` can later be swapped for gateway JSON.
 *
 * Money is a plain number in EUR, rounded to cents by the gateway.
 * Times are ISO 8601 strings with an offset (server time is Helsinki).
 * `null` always means "unknown", never zero or "none".
 */

/** Valio product code. Always a string: codes are never numbers. */
export type ProductCode = string;

/** Pack hierarchy entry, from catalog `units[]` (e.g. KI = 12 ST). */
export interface PackUnit {
  unitId: string;
  sizeInBaseUnits: number;
}

/** GS1 allergen classification: `CONTAINS` or may-contain. */
export type AllergenPresence = "CONTAINS" | "MAY_CONTAIN";

export interface Allergen {
  /** GS1 code, e.g. `AM` milk, `AW` gluten cereals. */
  code: string;
  name: string;
  presence: AllergenPresence;
}

/** Catalog `packagingMarkedLabel` values the UI knows how to show. */
export type ProductLabel =
  | "EU_ORGANIC_FARMING"
  | "GOODS_FROM_FINLAND_BLUE_SWAN"
  | "FINNISH_HEART_SYMBOL";

export interface Product {
  id: ProductCode;
  /** Names from `synkkaData.names[]`. */
  names: { en: string; fi?: string; sv?: string };
  brand: string;
  vendorName: string;
  category: string;
  /** The unit you order in (ST piece, KI case, KG …). */
  salesUnit: string;
  /** The unit prices compare in (L or KG). */
  baseUnit: string;
  /** Base units in one sales unit (1 for a 1 L carton sold per piece). */
  baseUnitsPerSalesUnit: number;
  units: PackUnit[];
  /** Fat % from nutrition data; null when not given. */
  fatPercent: number | null;
  /** `temperatureCondition` code with a readable label; null when missing. */
  temperature: { code: number; label: string } | null;
  /** null = allergen data missing (unknown), NOT allergen-free. */
  allergens: Allergen[] | null;
  labels: ProductLabel[];
  /** Product-group estimate in kg CO2-eq per kg; null when not in the dataset. */
  co2KgPerKg: number | null;
  /** Delivered vs ordered, 0..1; null when not in the dataset. */
  deliveryReliability: number | null;
}

/** Price + availability for one product and one requested date (an offer). */
export interface Offer {
  productId: ProductCode;
  requestedDate: string;
  /** Catalog price per sales unit before tax; null when `error: true`. */
  priceExVat: number | null;
  taxRatePercent: number;
  /** Price per comparison unit before tax, e.g. € per L. */
  comparisonPrice: number | null;
  comparisonUnit: "L" | "KG" | null;
  /** In `salesUnit`. 999999 and 9999999999 are "unknown" sentinels. */
  availableAmount: number;
  salesUnit: string;
  /** Earliest date it can arrive; can be later than `requestedDate`. */
  availableDate: string | null;
  /** Order cut-off for `availableDate`. Can already be in the past. */
  closingTime: string | null;
  salesBlock: boolean;
}

export type OrderStatus =
  | "AUTO_APPROVED"
  | "NEEDS_APPROVAL"
  | "REFUSED"
  | "PLACED"
  | "NOT_SENT"
  | "UNCONFIRMED"
  | "SENT_READ_FAILED";

export type Urgency =
  | "GUESTS_AFFECTED_TODAY"
  | "RUNS_OUT_BEFORE_NEXT_DELIVERY"
  | "DUE_NOW"
  | "CAN_WAIT"
  | "UNKNOWN";

export interface OrderLine {
  product: Product;
  offer: Offer;
  /** In the product's sales unit. Computed by the engine, never by the model. */
  quantity: number;
  /** Deterministic one-sentence reason from the engine. */
  why: string;
}

/** Free-delivery threshold (MOV), not a wall. */
export interface MovState {
  threshold: number;
  /** Order value ex VAT that counts toward the threshold. */
  current: number;
  /** Fee charged when the threshold is not met. */
  deliveryFee: number;
}

export interface Order {
  id: string;
  status: OrderStatus;
  urgency: Urgency;
  deliveryDate: string;
  lines: OrderLine[];
  totalExVat: number;
  totalInclVat: number;
  mov: MovState;
}

/** One rule of the mandate that this order breaks or touches. */
export interface MandateReason {
  rule: string;
  detail: string;
}

export interface ApprovalRequest {
  id: string;
  orderId: string;
  requestedBy: string;
  createdAt: string;
  /** One line: what the chef asked and what this order covers. */
  summary: string;
  lineCount: number;
  deliveryDate: string;
  totalExVat: number;
  totalInclVat: number;
  reasons: MandateReason[];
  status: "PENDING" | "APPROVED" | "REJECTED";
}

export interface SubstitutionRule {
  rule: string;
  needsApproval: boolean;
}

export interface Mandate {
  id: string;
  restaurant: string;
  signedBy: string;
  validUntil: string;
  /** Orders at or below this total (ex VAT) may be placed without a human. */
  autoApproveLimitExVat: number;
  weeklyLimitExVat: number;
  spentThisWeekExVat: number;
  /** A line with one of these (CONTAINS or MAY_CONTAIN) is refused. */
  excludedAllergens: Allergen[];
  acceptedLabels: ProductLabel[];
  substitutionRules: SubstitutionRule[];
}

export type AuditKind = "request" | "search" | "offer" | "simulate" | "mandate_check" | "approval" | "order";

export interface AuditEvent {
  id: string;
  at: string;
  kind: AuditKind;
  actor: "chef" | "agent" | "gateway" | "human";
  /** What happened, short. */
  summary: string;
  /** Why, in the words of the engine, the gateway or the human. */
  reason: string;
  orderId?: string;
}

export type OfferTier = "good" | "better" | "best";

export interface TradeOff {
  text: string;
  /** plus = better than the original ask, minus = worse. */
  direction: "plus" | "minus" | "neutral";
}

export interface SubstituteOption {
  tier: OfferTier;
  product: Product;
  offer: Offer;
  tradeOffs: TradeOff[];
  recommended?: boolean;
}

export interface ChefRequest {
  text: string;
  covers: number | null;
  deliveryDate: string;
}
