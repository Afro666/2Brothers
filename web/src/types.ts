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
  warning?: boolean;
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
  /** The baskets the engine offers for this request; absent or empty when it offers one. */
  options?: ProposalOption[];
}

export interface ProposalOptionLine {
  productId: ProductCode;
  /** null when the API names only the product id. */
  productName: string | null;
  quantity: number;
  unit: string;
  /** Ex VAT, per `unit`. */
  unitPrice: number | null;
}

/**
 * One basket the engine offers for a request (contract `substitute_options`).
 * null means unknown: never zero, never none, and never the best value.
 */
export interface ProposalOption {
  /** The option's engine offer id. */
  id: string;
  /** Presentation order only; it does not say an option is better. */
  tier: OfferTier;
  /** PARTIAL covers part of the ask now and leaves the rest for later. */
  kind: "FULL" | "PARTIAL";
  lines: ProposalOptionLine[];
  /** With fees and tax: the exact figure a person approves. */
  totalInclVat: number;
  /** False unless every line's stock is measured. */
  stockConfirmed: boolean;
  /** true = the order cut-off is missed; null = the API did not say. */
  cutoffPassed: boolean | null;
  cutoffAt: string | null;
  /** Delivered vs ordered, 0..1, of the weakest line. */
  deliveryReliability: number | null;
  /** Product-group average (not this product's own figure): lowest and highest line. */
  co2KgPerKg: { min: number; max: number } | null;
  /** Labels every line carries. */
  labels: ProductLabel[] | null;
  /** The engine's sentence, shown verbatim. */
  tradeOff: string;
  /** Only what the API says: the UI never ranks options. */
  recommended: boolean;
  /** The basket the proposal holds now. */
  chosen: boolean;
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
  /** Ex VAT amount above which an approval carries a budget warning. */
  budgetWarningPerOrderExVat: number;
  weeklyLimitExVat: number;
  spentThisWeekExVat: number;
  /** A line with one of these (CONTAINS or MAY_CONTAIN) is refused. */
  excludedAllergens: Allergen[];
  acceptedLabels: ProductLabel[];
  substitutionRules: SubstitutionRule[];
}

export type AuditKind =
  | "request"
  | "search"
  | "offer"
  | "simulate"
  | "mandate_check"
  | "approval"
  | "order"
  | "stock"
  | "forecast_share"
  | "settings";

export interface AuditEvent {
  id: string;
  at: string;
  kind: AuditKind;
  actor: "chef" | "agent" | "gateway" | "human" | "valio" | "system";
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

export type SupplierAdapter = "valio_api" | "manual" | "csv";

/** A kitchen's supplier. Terms are set by the user; null means not set, never a default. */
export interface Supplier {
  id: string;
  name: string;
  adapter: SupplierAdapter;
  freeDeliveryThresholdEur: number | null;
  deliveryFeeEur: number | null;
  /** ISO weekdays the supplier takes orders: 1 Monday .. 7 Sunday. */
  orderDays: number[] | null;
  /** Order cut-off on an order day, "HH:MM" Helsinki time. */
  cutoffTime: string | null;
  leadTimeDays: number | null;
}

/** A product the kitchen added itself (not in a supplier catalog). */
export interface OwnProduct {
  id: string;
  name: string;
  unit: string;
  packSize: number | null;
  priceEur: number | null;
  supplierId: string;
  /** null = unknown, NOT allergen-free. */
  allergens: Allergen[] | null;
}

export interface RecipeItem {
  productId: ProductCode;
  productName: string;
  unit: string;
  qtyPerPortion: number;
}

export interface Recipe {
  id: string;
  name: string;
  items: RecipeItem[];
}

/** One recipe on one day's menu, with the covers expected for it. */
export interface MenuPlanEntry {
  id: string;
  date: string;
  meal: string;
  recipeId: string;
  covers: number;
}

export interface StockItem {
  productId: ProductCode;
  productName: string;
  unit: string;
  /** null = not counted (unknown), never zero. */
  onHand: number | null;
  onOrder: number;
  countedAt: string | null;
  lastDelivery: string | null;
}

/** What the kitchen needs of one product on one day, from the menu plan. */
export interface DemandLine {
  productId: ProductCode;
  productName: string;
  unit: string;
  date: string;
  need: number;
  why: string;
}

export type ShortageRisk = "SHORT" | "AT_RISK" | "COVERED" | "UNKNOWN";

/** Supplier view: forecast demand across consenting kitchens against availability. */
export interface SupplierDemandRow {
  productId: ProductCode;
  productName: string;
  unit: string;
  date: string;
  forecastDemand: number;
  kitchens: number;
  byKitchen: { kitchenId: string; kitchenName: string; demand: number }[];
  /** null = the supplier's availability is not measured. */
  available: number | null;
  risk: ShortageRisk;
  /** What the supplier should buy to close the gap; null when availability is unknown. */
  suggestedBuy: number | null;
}

/** Whether this kitchen shares its forecast with a supplier. */
export interface SharingConsent {
  supplierId: string;
  shared: boolean;
}

export type DemandClass = "A" | "B" | "C";

export interface CoverRule {
  category: string;
  maxDays: number;
}

/** How the engine sizes orders for this kitchen. Defaults come from the engine. */
export interface KitchenSettings {
  /** Target service level per demand class, in percent (A = menu-critical). */
  serviceLevelPercent: Record<DemandClass, number>;
  /** Never order more than this many days of cover for a category. */
  maxDaysOfCover: CoverRule[];
  /** Demand seen during a stock-out is undercounted; it is scaled up by at most this factor. */
  stockOutDemandCap: number;
  /** Above these the approval shows a warning. null = no warning set. */
  budgetWarningPerOrderExVat: number | null;
  budgetWarningPerWeekExVat: number | null;
  /** A product that contains or may contain one of these is refused. GS1 codes. */
  excludedAllergens: string[];
}

/** A product the Buyer could add to this order, most useful first. */
export interface AddableProduct {
  product: Product;
  offer: Offer;
  /** null = not counted (unknown), never zero. */
  onHand: number | null;
  onOrder: number | null;
  /** In the product's sales unit; from the engine, never typed by the model. */
  suggestedQuantity: number;
  why: string;
}

export type ProposalChange =
  | { type: "SET_QUANTITY"; productId: ProductCode; quantity: number }
  | { type: "REMOVE_LINE"; productId: ProductCode }
  | { type: "ADD_LINE"; productId: ProductCode; quantity: number };

/** One human correction, kept as learning data for the engine. */
export interface FeedbackRow {
  id: string;
  at: string;
  actor: AuditEvent["actor"];
  orderId: string;
  productId: ProductCode | null;
  /** Maps to contract change kinds: QUANTITY_CHANGED = qty_changed (from_qty, to_qty), LINE_REMOVED = line_removed, LINE_ADDED = line_added (to_qty), REJECTED = rejected (reason), APPROVED = approved. */
  kind: "QUANTITY_CHANGED" | "LINE_REMOVED" | "LINE_ADDED" | "REJECTED" | "APPROVED";
  /** For QUANTITY_CHANGED: the Buyer's number and the person's number. */
  from: number | null;
  to: number | null;
  reason: string | null;
}
