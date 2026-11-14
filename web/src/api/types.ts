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
} from "@/types";

/** Who a decision is recorded as in the audit log. */
export type AuditActor = AuditEvent["actor"];

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

/** Everything the screens ask the gateway for. Mock and HTTP both implement it. */
export interface Api {
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
  getSharing(): Promise<SharingConsent[]>;
  setSharing(supplierId: string, shared: boolean, actor: AuditActor): Promise<SharingConsent[]>;
  getSupplierDemand(from: string, to: string): Promise<SupplierDemandRow[]>;
  getKitchenSettings(): Promise<KitchenSettings>;
  saveKitchenSettings(settings: KitchenSettings, actor: AuditActor): Promise<KitchenSettings>;
  /** Predicted against actual for the last 12 full weeks, and the forecast for this week and the 3 after. */
  getForecastAccuracy(): Promise<ForecastAccuracy>;
}

/** A gateway error: `code` is the contract's error code, e.g. `TOTAL_MISMATCH`. */
export class ApiError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
  }
}
