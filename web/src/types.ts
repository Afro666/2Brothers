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
  /** Base units in one sales unit (1 for a 1 L carton sold per piece); null when not known. */
  baseUnitsPerSalesUnit: number | null;
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
  /** null when the gateway sends only the order's VAT total. */
  taxRatePercent: number | null;
  /** Price per comparison unit before tax, e.g. € per L. */
  comparisonPrice: number | null;
  comparisonUnit: "L" | "KG" | null;
  /** In `salesUnit`. 999999, 9999999999 and null are "unknown". */
  availableAmount: number | null;
  /** The supplier confirmed stock for the ordered quantity, without saying how much there is. */
  stockConfirmed?: boolean;
  salesUnit: string;
  /** Earliest date it can arrive; can be later than `requestedDate`. */
  availableDate: string | null;
  /** Order cut-off for `availableDate`. Can already be in the past. */
  closingTime: string | null;
  salesBlock: boolean;
}

export type OrderStatus =
  | "NEEDS_APPROVAL"
  | "IN_PROGRESS"
  | "BLOCKED_BY_RECALL"
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
  deliveryDate: string | null;
  lines: OrderLine[];
  totalExVat: number | null;
  totalInclVat: number;
  /** null = the supplier's delivery terms are not known. */
  mov: MovState | null;
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
  createdAt: string | null;
  /** One line: what the chef asked and what this order covers. */
  summary: string;
  lineCount: number;
  deliveryDate: string;
  totalExVat: number;
  totalInclVat: number;
  reasons: MandateReason[];
  /** Only PENDING can be approved; IN_PROGRESS and BLOCKED_BY_RECALL wait, they are not decided. */
  status: "PENDING" | "IN_PROGRESS" | "BLOCKED_BY_RECALL" | "APPROVED" | "REJECTED";
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
  | "settings"
  | "other";

export interface AuditEvent {
  id: string;
  /** null = the gateway did not record when. */
  at: string | null;
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
  /** null = the gateway cannot say what is on order yet (unknown), never zero. */
  onOrder: number | null;
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

/**
 * One order proposal for everything a menu plan window needs, net of counted stock
 * (`POST /proposals` with `from` and `to`). It is a proposal only: a person approves it.
 */
export interface PlanProposal {
  id: string;
  /** REJECTED: the gateway could not put one line in the basket. */
  status: "READY" | "REJECTED";
  /** The total a person approves (the gateway's `expected_total`). */
  totalInclVat: number;
  lineCount: number;
  /** Products the plan needs something of. */
  needCount: number;
  /** Needed products whose stock was never counted: their full need is proposed. */
  uncountedCount: number;
  /** Needed products that cannot be fully covered. */
  shortfallCount: number;
  /** Why the proposal needs a person or was refused (the gateway's `mandate.reason_codes`). */
  reasonCodes: string[];
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

/**
 * How the engine sizes orders for this kitchen. Defaults come from the engine. From the gateway,
 * a service level or stock-out cap the kitchen never set is NaN (the form shows an empty field):
 * the engine's default applies and the gateway does not send it.
 */
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

/** One thing the Buyer does, asks for or is refused, with the audit kind that shows it happening. */
export interface PermissionRow {
  action: string;
  auditKind: AuditKind;
  /** The gateway rule that enforces it, when the gateway sends one. */
  rule?: string;
}

/** What the Buyer decides alone, what a person signs off, and what the Buyer can never do. */
export interface BuyerPermissions {
  alone: PermissionRow[];
  person: PermissionRow[];
  never: PermissionRow[];
}

/** How far this kitchen is into the learning period of the earned auto-approve. Read-only. */
export interface AutoApproveLearning {
  weeks: number;
  weeksNeeded: number;
  decisions: number;
  decisionsNeeded: number;
  /** Share of decisions a person edited, 0 to 1. null = not known yet, never shown as 0 %. */
  editRate: number | null;
  maxEditRate: number;
  /** Whether an approver switched auto-approve on. Absent = not known (shown as off). */
  enabled?: boolean;
  /** The kitchen's limit in EUR, as the gateway sends it. Only with `enabled`. */
  limitEur?: string | null;
  /** Who switched it on. Only with `enabled`. */
  setBy?: string | null;
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

/** How one forecast method did against what the kitchen really needed. Every null is "unknown", never zero. */
export interface ForecastScore {
  /** Weekly error: sum of |predicted - actual| over sum of actual, as a fraction. */
  wape: number | null;
  /** (predicted - actual) / actual; above zero means the forecast was too high. */
  bias: number | null;
  /** Quantity needed above the forecast (the kitchen would have run short). */
  short: number | null;
  /** Quantity forecast above the need (it would have been waste). */
  waste: number | null;
  /** Days a product would have run out when ordering to this forecast. */
  stockOutDays: number | null;
}

export interface ForecastWeek {
  /** ISO `YYYY-Www`. */
  week: string;
  /** null in a week that is not over, or a past week with no stock count. */
  actual: number | null;
  /** true for a week that is not over yet: it carries a forecast only. */
  ahead: boolean;
  engine: number | null;
  baseline: number | null;
  engineWape: number | null;
  baselineWape: number | null;
}

/** Predicted against actual per week, for the whole kitchen or one product. */
export interface ForecastSeries {
  /** null for the whole kitchen. */
  productId: ProductCode | null;
  name: string;
  /** null when the series adds products counted in different units. */
  unit: string | null;
  /** Our engine: menu x covers x recipe. */
  engine: ForecastScore;
  /** The plain weekday average. */
  baseline: ForecastScore;
  /** Oldest first: past weeks, then future weeks. */
  weeks: ForecastWeek[];
}

export interface ForecastAccuracy {
  kitchen: ForecastSeries;
  /** null when the gateway does not say per product (unknown, not "no products"). */
  products: ForecastSeries[] | null;
}

/** Standing-order drift (docs/contract.md, "Standing-order drift"). */
export type DriftKind = "portion_creep" | "cost_creep";

export interface DriftWarning {
  productId: ProductCode;
  /** null when the gateway sends only the code. */
  productName: string | null;
  kind: DriftKind;
  /** 0.4 = 40% above the baseline. */
  change: number;
  unit: string;
  qtyPer100: number;
  baselineQty: number;
  spendPer100: number;
  baselineSpend: number;
  baselineWeeks: number;
  why: string;
  /** Set on the supplier side only: the consenting kitchen it belongs to. */
  kitchenId?: string;
  kitchenName?: string | null;
}

export interface DriftReport {
  /** Monday of the last full week, `YYYY-MM-DD`. */
  week: string;
  warnings: DriftWarning[];
}

/** The kitchen-type guess onboarding offers. Anything else stays unknown. */
export type KitchenType = "hotel" | "school" | "hospital" | "restaurant";

/** Where a looked-up field came from: the provider and the endpoint the gateway called. */
export interface FieldSource {
  provider: "Context.dev";
  /** e.g. `POST /v1/brand/retrieve`. */
  endpoint: string;
}

/** One looked-up field. `value` null = unknown: the lookup did not find it, so nothing is guessed. */
export interface LookedUpField<T> {
  value: T | null;
  /** null when `value` is null. */
  source: FieldSource | null;
}

export interface KitchenAddress {
  street: string | null;
  postalCode: string | null;
  city: string | null;
  country: string | null;
}

/** What onboarding found for a kitchen's email or website. Nothing is saved until a person confirms. */
export interface KitchenBrandLookup {
  /** The domain the lookup used, e.g. `hotelkuusi.fi`. */
  domain: string;
  /** false when the provider knew nothing about the domain: every field is then unknown. */
  found: boolean;
  name: LookedUpField<string>;
  /** An https URL or a `data:image/svg+xml` URI. */
  logoUrl: LookedUpField<string>;
  /** Brand colours as `#rrggbb`, the main one first. */
  colors: LookedUpField<string[]>;
  address: LookedUpField<KitchenAddress>;
  kitchenType: LookedUpField<KitchenType>;
  /** Free text as the website says it, e.g. "Mon-Fri 06:30-22:00". */
  openingHours: LookedUpField<string>;
}

/** The profile a person confirmed on the onboarding page. */
export interface KitchenBrandProfile {
  domain: string;
  name: string;
  logoUrl: string | null;
  colors: string[];
  address: KitchenAddress;
  kitchenType: KitchenType | null;
  openingHours: string | null;
}

/**
 * How sure the recall monitor is that a notice is about this product (monitor/README.md):
 * `exact` the notice's EAN is the product's; `possible` same brand and a shared product
 * word; `review` no brand and no EAN, a person checks.
 */
export type RecallMatch = "exact" | "possible" | "review";

/** The Ruokavirasto notice as Context.dev scraped it. null means the notice does not say. */
export interface RecallNotice {
  url: string;
  /** `YYYY-MM-DD`. */
  date: string | null;
  /** The notice title, in Finnish as published. */
  title: string | null;
  reason: string | null;
  action: string | null;
  recalledProduct: string | null;
  brand: string | null;
  gtin: string | null;
  packageSize: string | null;
  /** Recalled lots or best-before dates; null means the notice names none, so every pack is in doubt. */
  lot: string | null;
}

/** The line the Buyer re-planned in place of the recalled one. The engine sized it. */
export interface RecallReplacementLine {
  productId: ProductCode;
  productName: string | null;
  quantity: number;
  unit: string;
}

/** One `recall.alert` (docs/contract.md, Webhooks), as the screens read it. */
export interface RecallAlert {
  /** Stable per notice, kitchen and product: a repeat check is the same alert. */
  eventId: string;
  productId: ProductCode;
  productName: string | null;
  match: RecallMatch;
  /** The monitor's reason for the match, shown verbatim. */
  why: string;
  /** Where the kitchen holds it: stock, recipes, the open proposal. */
  where: string[];
  recall: RecallNotice;
  nextStep: string;
  /** The open order it hits; null when it is not on an open order. */
  orderId: string | null;
  /**
   * `BLOCKED_BY_RECALL` for an exact or possible match on an order line; `WARNING` for a
   * review match, which never blocks on its own.
   */
  lineStatus: "BLOCKED_BY_RECALL" | "WARNING";
  /** null while the Buyer has not re-planned the line: then the order cannot be approved. */
  replacementLine: RecallReplacementLine | null;
  /** Ideas for the chef from other brands; nothing is ordered from an alert. */
  replacementIdeas: { productId: ProductCode; name: string | null; brand: string | null }[];
  detectedAt: string;
}

/** One run of the recall monitor. */
export interface RecallCheck {
  checkedAt: string;
  /** `live`: scraped now. `recording`: Context.dev was slow or the demo uses the saved scrape. */
  source: "live" | "recording";
  /** When the scraped pages were fetched; for `live` the same as `checkedAt`. */
  fetchedAt: string;
  /** The Context.dev endpoint, e.g. `/v1/web/scrape`. */
  via: string;
  /** null when the monitor does not say. */
  noticesScanned: number | null;
}

/** What the inbox knows about recalls: the open alerts and the last check. */
export interface RecallList {
  /** null when no check has run: the screens then say "not checked yet", never "no recalls". */
  lastCheck: RecallCheck | null;
  alerts: RecallAlert[];
}
