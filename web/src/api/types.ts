import type { ApprovalDecision } from "@/components/purchasing/approval-card";
import type { ApprovalRequest, AuditEvent, ChefRequest, Mandate, Order, Product, SubstituteOption } from "@/types";

/** Who a decision is recorded as in the audit log. */
export type AuditActor = AuditEvent["actor"];

export interface ProductSearchFilters {
  /** GS1 allergen codes, e.g. `AM` milk. CONTAINS and MAY_CONTAIN both exclude. */
  excludedAllergens?: string[];
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
  listOrders(): Promise<Order[]>;
  getOrder(id: string): Promise<Order>;
  listAudit(filter?: { orderId?: string }): Promise<AuditEvent[]>;
  submitChefRequest(request: ChefRequest): Promise<ChefProposal>;
  searchProducts(query: string, filters?: ProductSearchFilters): Promise<Product[]>;
  getMandate(): Promise<Mandate>;
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
