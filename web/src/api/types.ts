import type { ApprovalDecision } from "@/components/purchasing/approval-card";
import type {
  AllergenPresence,
  ApprovalRequest,
  AuditEvent,
  AddableProduct,
  ChefRequest,
  DemandLine,
  Mandate,
  MenuPlanEntry,
  Order,
  OrderResolution,
  OrderResolutionInput,
  OrderResolutionResult,
  OwnProduct,
  PlanProposal,
  Product,
  ProductCode,
  ProposalChange,
  FeedbackRow,
  Recipe,
  SharingConsent,
  StockItem,
  Supplier,
  ProductLabel,
  SupplierDemandRow,
  SubstituteOption,
  KitchenSettings,
  ForecastAccuracy,
  DriftReport,
  BuyerPermissions,
  BuyingNote,
  AutoApproveLearning,
  RecallList,
  KitchenBrandLookup,
  SupplierOffer,
  SupplierOfferAccepted,
} from "@/types";

/** Who a decision is recorded as in the audit log. */
export type AuditActor = AuditEvent["actor"];

export interface LiveEvent {
  kind: "proposal" | "approval" | "audit";
  operation: string;
}

export interface Session {
  kind: "human" | "agent" | "token" | null;
  name: string;
  email: string | null;
  role: "approver" | "chef" | "viewer" | null;
  canApprove: boolean;
}

export type KitchenProfileType = "restaurant" | "school" | "hospital" | "hotel" | "cafe";

export interface KitchenProfile {
  name: string;
  type: KitchenProfileType;
  address: string;
  timezone: string;
  deliveryAddress: string;
}

export interface TeamMember {
  id: string;
  name: string;
  email: string;
  role: "approver" | "chef" | "viewer";
}

export interface NotificationPreferences {
  approvalWaiting: boolean;
  cutoffTwoHours: boolean;
  recallAlert: boolean;
  orderConfirmed: boolean;
}

export interface Webhook {
  id: string;
  url: string;
  events: string[];
  createdAt: string | null;
  createdBy: string | null;
}

export interface CreatedWebhook extends Webhook {
  secret: string;
}

export interface WebhookDelivery {
  id: string;
  event: string;
  at: string | null;
  attempts: number | null;
  status: number | null;
  ok: boolean;
  error: string | null;
}

export interface GatewayHealth {
  status: string;
  valioMode: "live" | "mock" | "unknown";
}

export interface RecentApiCall {
  id: string;
  method: string;
  path: string;
  status: number | null;
  at: string | null;
}

export interface KitchenDeletionRequest {
  id: string;
  requestedAt: string;
  status: "requested";
}

export type Draft<T extends { id: string }> = Omit<T, "id"> & { id?: string };

export type ApiTokenScope = "kitchen:read" | "kitchen:propose" | "kitchen:write";

/** The secret-free token row returned by every token route. */
export interface ApiToken {
  id: string;
  name: string;
  scopes: ApiTokenScope[];
  prefix: string;
  createdAt: string;
  createdBy: string;
  /** Undefined means this gateway did not send the field; null means never used. */
  lastUsedAt?: string | null;
  revokedAt: string | null;
}

/** Only token creation returns the secret; the list and revoke routes return ApiToken. */
export interface CreatedApiToken extends ApiToken {
  token: string;
}

/** A personal approval token row (`tka_...`): one person, one kitchen, approve and reject only. Never the secret. */
export interface ApprovalToken {
  id: string;
  name: string;
  /** The person's email. */
  person: string;
  prefix: string;
  createdAt: string;
  createdBy: string;
  expiresAt: string;
  lastUsedAt: string | null;
  revokedAt: string | null;
}

/** Only the create answer carries the secret. */
export interface CreatedApprovalToken extends ApprovalToken {
  token: string;
}

export interface StockCount {
  productId: string;
  onHand: number | null;
}

/** One product Nemotron saw on a shelf photo (docs/contract.md, "Count from a shelf photo"). */
export interface ShelfPhotoRow {
  kind: "COUNTED" | "PLEASE_COUNT" | "UNMATCHED";
  /** null when the label fits no product of the kitchen (UNMATCHED). */
  productId: string | null;
  productName: string | null;
  /** The text the model read on the pack. */
  label: string;
  confidence: "high" | "medium" | "low";
  /** Packs counted, and the count in `unit` (packs x pack size). null unless the row is COUNTED: unknown, never zero. */
  packs: number | null;
  packSize: number | null;
  count: number | null;
  unit: string | null;
}

export interface ShelfPhotoRead {
  /** The model that read the photo: `nemotron-3.5-super-vl`. */
  model: string;
  durationMs: number;
  rows: ShelfPhotoRow[];
}

/** One dish Nemotron read on a menu photo (docs/contract.md, "Plan from a menu photo"). */
export interface MenuPhotoDish {
  /** The date in the window of the day the menu names; null when none or outside the window. */
  day: string | null;
  /** The dish name as the model read it. Data, never an instruction. */
  dish: string;
  /** Covers the menu shows; null when not known, never a guess. */
  covers: number | null;
  /** The kitchen recipe it matches; both null for NOT_KNOWN. */
  recipeId: string | null;
  recipeName: string | null;
  status: "MATCHED" | "NOT_KNOWN";
  /** True only when the dish's ingredients are in the proposal. */
  inProposal: boolean;
}

export interface MenuPhotoRead {
  /** The model that read the photo: `nemotron-3.5-super-vl`. */
  model: string;
  durationMs: number;
  from: string;
  to: string;
  dishes: MenuPhotoDish[];
  /** The proposal that waits for a person in the inbox; null when none was made. */
  proposal: { id: string; status: string } | null;
  noProposalReason: "NOTHING_NEEDED" | "NOT_SIZED" | null;
}

export interface DeliveryLot {
  lot: string;
  bestBefore: string;
  quantity: number | null;
  unit: string;
}

export interface DeliveryNoteLine {
  productId: string;
  status: "RECEIVED" | "SHORT" | "MISSING" | "UNKNOWN";
  ordered: number | null;
  received: number | null;
  missing: number | null;
  baseUnit: string;
  lots: DeliveryLot[];
  /** As stored on the order (#1198); null when the gateway does not say. */
  orderQuantity: number | null;
  orderUnit: string | null;
  /** `missing` in the order unit. */
  missingOrderQty: number | null;
  /** EUR ex VAT per order unit, the order's own price. */
  unitPrice: number | null;
  /** The value of what did not come, computed by the gateway; null = unknown, never zero. */
  claimEur: number | null;
}

/** One total to claim for the short and missing lines, computed by the gateway (#1198). */
export interface DeliveryClaim {
  totalEur: number;
  lines: number;
  /** Set only when every short line has the same order unit. */
  quantity: number | null;
  unit: string | null;
  /** Lines that may be short but have no value; not in `totalEur`. */
  notValued: number;
  supplierName: string | null;
}

export interface DeliveryNoteOther extends DeliveryLot {
  productId: string;
  status: "SUBSTITUTE" | "EXTRA" | "UNREADABLE";
  replaces: string;
  received: number | null;
  baseUnit: string;
  needsApproval: boolean;
}

export interface DeliveryNoteRead {
  orderId: string;
  model: string;
  durationMs: number;
  orderRef: string;
  deliveryDate: string;
  complete: boolean;
  lines: DeliveryNoteLine[];
  notOrdered: DeliveryNoteOther[];
  /** null when the gateway sent no claim (an older gateway). */
  claim: DeliveryClaim | null;
}

/** docs/contract.md "Check a package's allergen label from a photo" (#1175). The first that applies. */
export type LabelPhotoOutcome = "EXCLUDED_ALLERGEN" | "PLEASE_CHECK" | "DIFFERS" | "CATALOG_UNKNOWN" | "AGREES";
export type LabelProductCheck = "CONFIRMED_BY_EAN" | "CONFIRMED_BY_NAME" | "MISMATCH" | "NOT_CONFIRMED";
export type LabelPleaseCheck = "NO_STATEMENT_READ" | "WORD_UNKNOWN" | "PRODUCT_MISMATCH" | "PRODUCT_NOT_CONFIRMED";

/** A word as printed on the label, with its GS1 allergen code. */
export interface LabelWord {
  word: string;
  code: string;
}

/** One label read. Shown to a person and stored nowhere: it never changes the catalog. */
export interface LabelPhotoRead {
  model: string;
  /** null when the gateway sent no duration. */
  durationMs: number | null;
  orderId: string;
  productId: string;
  /** false: a substitute that is not on the order. */
  inOrder: boolean;
  outcome: LabelPhotoOutcome;
  /** The gateway's one sentence (English). */
  message: string;
  productCheck: LabelProductCheck;
  label: { productName: string | null; ean: string | null; contains: LabelWord[]; mayContain: LabelWord[]; unknownWords: string[] };
  excludedHits: { code: string; level: AllergenPresence }[];
  differences: { code: string; kind: "LABEL_ADDS" | "CATALOG_ADDS"; text: string }[];
  /** UNKNOWN is never "free from". */
  catalogAllergenData: "KNOWN" | "UNKNOWN";
  pleaseCheck: LabelPleaseCheck[];
}

export type ProductTemperature = "ambient" | "chilled" | "frozen";

export interface ProductSearchFilters {
  /** GS1 allergen codes, e.g. `AM` milk. CONTAINS and MAY_CONTAIN both exclude. */
  excludedAllergens?: string[];
  /** When true, a product with no allergen data is removed too (unknown, not safe). */
  strictAllergens?: boolean;
  /** Products must carry every one of these labels. */
  requiredLabels?: ProductLabel[];
  /** A product with no temperature data never matches a temperature filter. */
  temperature?: ProductTemperature;
  /**
   * The Catalog page's "Search by meaning" switch: Atlas Vector Search with the words for
   * this one search (`mode: "hybrid"`, docs/contract.md, #1382). Not a filter.
   */
  byMeaning?: boolean;
}

/** How a search row was found (`matched_by`). */
export type MatchedBy = "words" | "meaning" | "both";

/** A product found by a search: it may say how it was found. */
export type SearchedProduct = Product & { matchedBy?: MatchedBy };

/**
 * Search rows, best first. `meaningUnavailable`: a search by meaning could not make the
 * query vector, so the gateway answered with words.
 */
export type SearchedProducts = SearchedProduct[] & { meaningUnavailable?: true };

/** What the agent proposes for one chef request. */
export interface ChefProposal {
  order: Order;
  substitutes: SubstituteOption[];
  approval: ApprovalRequest | null;
}

/** One audit line with its place in the hash chain (the entry shape of `store/audit.py`). */
export interface AuditChainRow {
  /** Position in the chain, from 1. */
  seq: number;
  event: AuditEvent;
  prevHash: string;
  hash: string;
}

/** `GET /audit/verify`. The chain is one for all kitchens. */
export interface AuditChainCheck {
  ok: boolean;
  /** Lines checked up to the first broken one. */
  length: number;
  /** `seq` of the first changed or removed line. */
  brokenAt: number | null;
  /** The kitchen that line belongs to; null when the chain is whole or the gateway cannot tell. */
  brokenKitchenId: string | null;
  /** How many of the lines belong to this kitchen. */
  kitchenEntries: number;
  /** When the web app got the answer; the gateway does not send it. */
  checkedAt: string;
}

/** `GET /model-usage`: what the Buyer agent used on its model, summed over this kitchen's runs. */
export interface ModelUsage {
  model: string;
  /** Every Buyer run of the kitchen. */
  runs: number;
  /** Runs that carry no count (from before the meter, or without a proposal). The sums leave them out. */
  runsWithoutUsage: number;
  modelCalls: number;
  promptTokens: number;
  completionTokens: number;
  modelSeconds: number;
}

/** The label nutrients of one portion. null means the labels do not say: unknown, never zero. */
export interface NutrientValues {
  kcal: number | null;
  proteinG: number | null;
  fatG: number | null;
  saturatedFatG: number | null;
  carbsG: number | null;
  sugarG: number | null;
  fibreG: number | null;
  saltG: number | null;
}

/** `GET /recipes/{id}/nutrition`: one portion as eaten, from the products' own nutrition tables. */
export interface RecipeNutrition {
  recipeId: string;
  name: string;
  perPortion: NutrientValues;
  /** Ingredients the numbers count. */
  knownIngredients: number;
  /** Ingredients with no nutrition table or no amount that converts: they are not in the numbers. */
  unknown: { productId: string; productName: string }[];
  complete: boolean;
  /** false when the gateway says the numbers cannot be right (a unit mistake in the recipe). */
  plausible: boolean;
  source: string;
}

export interface NutritionDay {
  date: string;
  covers: number;
  kcal: number | null;
  proteinG: number | null;
  kcalPerCover: number | null;
  complete: boolean;
}

/** `GET /nutrition?from=&to=`: planned energy per menu day, and what the approved orders contain. */
export interface KitchenNutrition {
  from: string;
  to: string;
  days: NutritionDay[];
  planned: { kcal: number | null; complete: boolean };
  /** `lines` 0 means nothing is ordered for the window; `kcal` null means no line could be counted. */
  ordered: { kcal: number | null; lines: number; knownLines: number; unknown: string[] };
  /** Ordered energy as a fraction of the planned energy; null when either is unknown. */
  orderedVsPlanned: number | null;
  note: string;
}

/** A phrase a person linked to one product. */
export interface KitchenAlias {
  phrase: string;
  productId: string;
  productName: string;
  setBy: string | null;
  uses: number;
}

/** A phrase from a request that matched no product. */
export interface UnknownWord {
  phrase: string;
  times: number;
  firstAsked: string | null;
  lastAsked: string | null;
  /** The nearest catalog products the gateway found; null = not looked up yet. */
  suggestions?: { productId: string; productName: string }[] | null;
  /** "meaning" (vector search) or "words" (text search). */
  suggestedBy?: "meaning" | "words" | null;
}

/** `GET /aliases`. */
export interface KitchenWords {
  aliases: KitchenAlias[];
  unknownItems: UnknownWord[];
}

/** Everything the screens ask the gateway for. Mock and HTTP both implement it. */
/** A brand's logo from Context.dev, kept by the gateway; only `found` has a logo. */
export interface BrandLogo {
  brand: string;
  status: "found" | "none" | "not_checked";
  logoUrl: string | null;
  /** What the logo needs behind it; `own` means the image has its own background. */
  background: "light" | "dark" | "own" | null;
  domain: string | null;
  checkedAt: string | null;
}

export interface Api {
  /**
   * Gateway mode only: the methods the real gateway answers. Every other method still
   * returns sample data from the mock. Absent on the mock itself.
   */
  readonly live?: ReadonlySet<keyof Api>;
  /** Optional for simpler test adapters; the mock returns a no-op subscription. */
  subscribeEvents?(onEvent: (event: LiveEvent) => void, onStatus?: (connected: boolean) => void): () => void;
  listApiTokens(): Promise<ApiToken[]>;
  createApiToken(input: { name: string; scopes: ApiTokenScope[] }): Promise<CreatedApiToken>;
  revokeApiToken(id: string): Promise<ApiToken>;
  listApprovalTokens(): Promise<ApprovalToken[]>;
  createApprovalToken(input: { hours: number; name?: string }): Promise<CreatedApprovalToken>;
  revokeApprovalToken(id: string): Promise<ApprovalToken>;
  getSession(): Promise<Session | null>;
  signIn(email: string, password: string): Promise<Session>;
  signOut(): Promise<void>;
  changePassword(current: string, next: string): Promise<void>;
  getKitchenProfile(): Promise<KitchenProfile>;
  saveKitchenProfile(profile: KitchenProfile, actor: AuditActor): Promise<KitchenProfile>;
  listTeamMembers(): Promise<TeamMember[]>;
  getNotificationPreferences(): Promise<NotificationPreferences>;
  saveNotificationPreferences(preferences: NotificationPreferences, actor: AuditActor): Promise<NotificationPreferences>;
  listWebhooks(): Promise<{ webhooks: Webhook[]; events: string[] }>;
  createWebhook(input: { url: string; events: string[] }, actor: AuditActor): Promise<CreatedWebhook>;
  testWebhook(id: string, actor: AuditActor): Promise<WebhookDelivery>;
  /** Remove the webhook and its delivery log (approver only). */
  deleteWebhook(id: string, actor: AuditActor): Promise<void>;
  getGatewayHealth(): Promise<GatewayHealth>;
  listRecentApiCalls(): Promise<RecentApiCall[]>;
  requestKitchenDeletion(confirmation: string, actor: AuditActor): Promise<KitchenDeletionRequest>;
  listApprovals(): Promise<ApprovalRequest[]>;
  /** How many approvals wait for a person, without loading the audit log. */
  countPendingApprovals?(): Promise<number>;
  getApproval(id: string): Promise<ApprovalRequest>;
  approve(decision: ApprovalDecision, actor: AuditActor): Promise<ApprovalRequest>;
  reject(approvalId: string, reason: string, actor: AuditActor): Promise<ApprovalRequest>;
  /** Products that could be added to this order, ranked; `query` filters by name. */
  listAddableProducts(orderId: string, query?: string): Promise<AddableProduct[]>;
  /** Applies one change, re-simulates the order and returns the new order and approval totals. */
  changeProposal(
    orderId: string,
    change: ProposalChange,
    actor: AuditActor,
  ): Promise<{ order: Order; approval: ApprovalRequest }>;
  /**
   * Re-simulates the proposal with one of its options and returns the approval with the new
   * totals. It approves nothing: a person still approves the exact new total. Optional for
   * adapters that cannot switch baskets.
   */
  chooseOption?(approvalId: string, optionId: string, actor: AuditActor): Promise<ApprovalRequest>;
  listFeedback(filter?: { orderId?: string }): Promise<FeedbackRow[]>;
  /** What is known about each brand's logo (contract: "Product pictures"). Never calls Context.dev. */
  listBrandLogos?(brands: string[]): Promise<BrandLogo[]>;
  listOrders(): Promise<Order[]>;
  getOrder(id: string): Promise<Order>;
  getOrderResolution(orderId: string): Promise<OrderResolution>;
  resolveOrder(orderId: string, resolution: OrderResolutionInput, actor: string): Promise<OrderResolutionResult>;
  listAudit(filter?: { orderId?: string }): Promise<AuditEvent[]>;
  /** The newest `limit` audit lines with their chain hashes, oldest first. */
  listAuditChain(limit: number): Promise<AuditChainRow[]>;
  verifyAuditChain(): Promise<AuditChainCheck>;
  getModelUsage(): Promise<ModelUsage>;
  /**
   * Demo only: changes the newest stored line and leaves its hash alone, so the next verify
   * reports the break. Fails with `DEMO_ONLY`, `ALREADY_TAMPERED` or `NOTHING_TO_TAMPER`.
   */
  tamperAuditRow(): Promise<{ seq: number }>;
  /** Demo only: puts the tampered line back. `seq` is null when nothing was tampered. */
  restoreAuditRow(): Promise<{ seq: number | null; restored: boolean }>;
  submitChefRequest(request: ChefRequest): Promise<ChefProposal>;
  searchProducts(query: string, filters?: ProductSearchFilters): Promise<SearchedProducts>;
  /** Catalog products by id; ids the catalog does not know are absent from the result. */
  getProducts(ids: ProductCode[]): Promise<Product[]>;
  getMandate(): Promise<Mandate>;
  listSuppliers(): Promise<Supplier[]>;
  /** Creates when `id` is missing, otherwise replaces. */
  saveSupplier(supplier: Draft<Supplier>): Promise<Supplier>;
  deleteSupplier(id: string): Promise<void>;
  listOwnProducts(): Promise<OwnProduct[]>;
  saveOwnProduct(product: Draft<OwnProduct>): Promise<OwnProduct>;
  deleteOwnProduct(id: string): Promise<void>;
  listRecipes(): Promise<Recipe[]>;
  saveRecipe(recipe: Draft<Recipe>): Promise<Recipe>;
  deleteRecipe(id: string): Promise<void>;
  /** `week` is ISO `YYYY-Www`. */
  getMenuPlan(week: string): Promise<MenuPlanEntry[]>;
  /** One portion of a recipe from the label data. Fails with `NOT_FOUND` for an unknown recipe. */
  getRecipeNutrition(recipeId: string): Promise<RecipeNutrition>;
  /** Planned and ordered energy, `from` and `to` inclusive (`YYYY-MM-DD`). */
  getNutrition(from: string, to: string): Promise<KitchenNutrition>;
  /** The kitchen's own names for products, and the words of requests that matched nothing. */
  getKitchenWords(): Promise<KitchenWords>;
  /** Links a phrase to one product; a request that uses the phrase then goes to that product. */
  linkWord(phrase: string, productId: string): Promise<void>;
  /** Removes an own name, or forgets a word that matched nothing. */
  forgetWord(phrase: string): Promise<void>;
  /** Replaces the whole week. */
  saveMenuPlan(week: string, entries: Draft<MenuPlanEntry>[]): Promise<MenuPlanEntry[]>;
  getStock(): Promise<StockItem[]>;
  submitStockCount(counts: StockCount[], actor: AuditActor): Promise<StockItem[]>;
  /**
   * Nemotron 3.5 Super VL reads a shelf photo (JPEG or PNG) into counts to confirm. It saves
   * nothing: the person checks the numbers and `submitStockCount` stores them.
   */
  readShelfPhoto(photo: Blob, actor: AuditActor): Promise<ShelfPhotoRead>;
  /**
   * Nemotron 3.5 Super VL reads a photo of the week's menu into dishes matched to recipes,
   * and the gateway makes a menu-plan proposal that waits for a person. Orders nothing.
   */
  readMenuPhoto(
    photo: Blob,
    window: { from: string; to: string; requestedDate?: string },
    actor: AuditActor,
  ): Promise<MenuPhotoRead>;
  /** Reads and compares a note. No receipt, substitute approval or stock count is saved. */
  readDeliveryNote(orderId: string, photo: Blob, actor: AuditActor): Promise<DeliveryNoteRead>;
  /**
   * Nemotron 3.5 Super VL reads the allergen label of one delivered package (#1175). Plain
   * code compares it with the catalog and the kitchen's rule. Read-only: nothing is stored.
   */
  readLabelPhoto(orderId: string, productId: string, photo: Blob, actor: AuditActor): Promise<LabelPhotoRead>;
  /** The kitchen's need per product and day, `from` and `to` inclusive (`YYYY-MM-DD`). */
  getDemand(from: string, to: string): Promise<DemandLine[]>;
  /**
   * Asks for one order proposal for what the menu plan needs from `from` to `to` (inclusive,
   * `YYYY-MM-DD`), delivered on `requestedDate`. It approves nothing. Fails with
   * `NOTHING_NEEDED` when the stock covers the plan.
   */
  proposeOrderForPlan(from: string, to: string, requestedDate: string): Promise<PlanProposal>;
  getSharing(): Promise<SharingConsent[]>;
  setSharing(supplierId: string, shared: boolean, actor: AuditActor): Promise<SharingConsent[]>;
  getSupplierDemand(from: string, to: string): Promise<SupplierDemandRow[]>;
  /**
   * Nemotron 3.5 Super VL's short buying note over the same window as the demand table.
   * Null when there is nothing to say, the note was dropped, or the gateway failed.
   */
  getBuyingNote(from: string, to: string, language: "en" | "fi"): Promise<BuyingNote | null>;
  getKitchenSettings(): Promise<KitchenSettings>;
  saveKitchenSettings(settings: KitchenSettings, actor: AuditActor): Promise<KitchenSettings>;
  /** Predicted against actual for the last 12 full weeks, and the forecast for this week and the 3 after. */
  getForecastAccuracy(): Promise<ForecastAccuracy>;
  /** Standing-order drift for the last full week (`GET /drift`). */
  getDrift(): Promise<DriftReport>;
  /** Drift warnings of the kitchens that share with this supplier (`GET /demand/drift`). */
  getSupplierDrift(): Promise<DriftReport>;
  getPermissions(): Promise<BuyerPermissions>;
  /** Suggestions a supplier sent to this kitchen, open ones first (`GET /supplier-offers`). */
  listSupplierOffers(): Promise<SupplierOffer[]>;
  /** Turns an open offer into a normal proposal. It approves and orders nothing. */
  acceptSupplierOffer(offerId: string, actor: AuditActor): Promise<SupplierOfferAccepted>;
  declineSupplierOffer(offerId: string, actor: AuditActor, reason?: string): Promise<SupplierOffer>;
  /** Progress only. There is no method to switch auto-approve on: a person approves every order. */
  getAutoApproveLearning(): Promise<AutoApproveLearning>;
  /**
   * Recall alerts for this kitchen and its last check. Optional, like `checkRecalls`: the contract
   * routes are proposed (#358); a gateway that does not serve them answers `NOT_SERVED`, and the
   * screens then say the check is not available instead of showing "no recalls".
   */
  listRecalls?(): Promise<RecallList>;
  /** Runs the recall monitor now (Context.dev scrape, or its recording when Context.dev is slow). */
  checkRecalls?(actor: AuditActor): Promise<RecallList>;
  /**
   * Onboarding: the gateway looks the kitchen up with Context.dev (`POST /v1/brand/retrieve`)
   * from a work email or a website. It saves nothing; a person confirms the fields first.
   */
  lookupKitchenBrand(query: { email: string } | { website: string }): Promise<KitchenBrandLookup>;
}

/** A gateway error: `code` is the contract's error code, e.g. `TOTAL_MISMATCH`. */
export class ApiError extends Error {
  readonly code: string;
  /** The other fields of the gateway's error object, e.g. `expected_total` on `TOTAL_MISMATCH`. */
  readonly details: Record<string, unknown>;
  readonly status?: number;

  constructor(code: string, message: string, details: Record<string, unknown> = {}, status?: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.details = details;
    this.status = status;
  }
}
