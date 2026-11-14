import type { ApprovalDecision } from "@/components/purchasing/approval-card";
import type {
  ApprovalRequest,
  AuditEvent,
  AddableProduct,
  ChefRequest,
  DemandLine,
  Mandate,
  MenuPlanEntry,
  Order,
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
  AutoApproveLearning,
  RecallList,
  KitchenBrandLookup,
} from "@/types";

/** Who a decision is recorded as in the audit log. */
export type AuditActor = AuditEvent["actor"];

export interface Session {
  name: string;
  email: string | null;
  role: "approver" | "chef" | "viewer" | null;
  canApprove: boolean;
}

export type Draft<T extends { id: string }> = Omit<T, "id"> & { id?: string };

export interface StockCount {
  productId: string;
  onHand: number | null;
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
}

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

/** Everything the screens ask the gateway for. Mock and HTTP both implement it. */
export interface Api {
  /**
   * Gateway mode only: the methods the real gateway answers. Every other method still
   * returns sample data from the mock. Absent on the mock itself.
   */
  readonly live?: ReadonlySet<keyof Api>;
  getSession(): Promise<Session | null>;
  signIn(email: string, password: string): Promise<Session>;
  signOut(): Promise<void>;
  changePassword(current: string, next: string): Promise<void>;
  listApprovals(): Promise<ApprovalRequest[]>;
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
   * totals. It approves nothing: a person still approves the exact new total. Optional because
   * the contract has no route for it yet; without it the screens cannot switch baskets.
   */
  chooseOption?(approvalId: string, optionId: string, actor: AuditActor): Promise<ApprovalRequest>;
  listFeedback(filter?: { orderId?: string }): Promise<FeedbackRow[]>;
  listOrders(): Promise<Order[]>;
  getOrder(id: string): Promise<Order>;
  listAudit(filter?: { orderId?: string }): Promise<AuditEvent[]>;
  /** The newest `limit` audit lines with their chain hashes, oldest first. */
  listAuditChain(limit: number): Promise<AuditChainRow[]>;
  verifyAuditChain(): Promise<AuditChainCheck>;
  /**
   * Demo only: changes the newest stored line and leaves its hash alone, so the next verify
   * reports the break. Fails with `DEMO_ONLY`, `ALREADY_TAMPERED` or `NOTHING_TO_TAMPER`.
   */
  tamperAuditRow(): Promise<{ seq: number }>;
  /** Demo only: puts the tampered line back. `seq` is null when nothing was tampered. */
  restoreAuditRow(): Promise<{ seq: number | null; restored: boolean }>;
  submitChefRequest(request: ChefRequest): Promise<ChefProposal>;
  searchProducts(query: string, filters?: ProductSearchFilters): Promise<Product[]>;
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
  /** Replaces the whole week. */
  saveMenuPlan(week: string, entries: Draft<MenuPlanEntry>[]): Promise<MenuPlanEntry[]>;
  getStock(): Promise<StockItem[]>;
  submitStockCount(counts: StockCount[], actor: AuditActor): Promise<StockItem[]>;
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
  getKitchenSettings(): Promise<KitchenSettings>;
  saveKitchenSettings(settings: KitchenSettings, actor: AuditActor): Promise<KitchenSettings>;
  /** Predicted against actual for the last 12 full weeks, and the forecast for this week and the 3 after. */
  getForecastAccuracy(): Promise<ForecastAccuracy>;
  /** Standing-order drift for the last full week (`GET /drift`). */
  getDrift(): Promise<DriftReport>;
  /** Drift warnings of the kitchens that share with this supplier (`GET /demand/drift`). */
  getSupplierDrift(): Promise<DriftReport>;
  getPermissions(): Promise<BuyerPermissions>;
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
