import type { Api, AuditActor, ProductTemperature } from "@/api/types";
import { ApiError } from "@/api/types";
import { createPlanningMock } from "@/api/mock-planning";
import { approval as seedApproval, auditEvents, mandate, orders, products, substitutes } from "@/mocks/milk-case";
import { formatEur } from "@/lib/format";
import type { ApprovalRequest, AuditEvent, Product } from "@/types";

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

/** The milk case held in memory. Each call makes its own state, so tests do not share it. */
export function createMockApi(): MockApi {
  let approval: ApprovalRequest = { ...seedApproval };
  const audit: AuditEvent[] = [...auditEvents];
  let nextFailure: ApiError | null = null;

  function pendingApproval(id: string): ApprovalRequest {
    if (id !== approval.id) throw new ApiError("NOT_FOUND", `Approval ${id} was not found.`);
    if (approval.status !== "PENDING") throw new ApiError("ALREADY_DECIDED", `Approval ${id} is already decided.`);
    return approval;
  }

  function decide(status: "APPROVED" | "REJECTED", actor: AuditActor, summary: string, reason: string) {
    approval = { ...approval, status };
    audit.push({
      id: `EV-${audit.length + 1}`,
      at: new Date().toISOString(),
      kind: "approval",
      actor,
      summary,
      reason,
      orderId: approval.orderId,
    });
    return approval;
  }

  return {
    ...createPlanningMock((event) => {
      audit.push({
        ...event,
        id: `EV-${audit.length + 1}`,
        at: new Date().toISOString(),
      });
    }),
    failNextApprove(code, message = "The gateway refused the approval.") {
      nextFailure = new ApiError(code, message);
    },

    async listApprovals() {
      return [approval];
    },
    async getApproval(id) {
      if (id !== approval.id) throw new ApiError("NOT_FOUND", `Approval ${id} was not found.`);
      return approval;
    },
    async approve(decision, actor) {
      const current = pendingApproval(decision.approvalId);
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
      return decide(
        "APPROVED",
        actor,
        `Approved ${current.orderId}`,
        `Approved exactly ${formatEur(current.totalExVat)} ex VAT (${formatEur(current.totalInclVat)} incl VAT).`,
      );
    },
    async reject(approvalId, reason, actor) {
      const current = pendingApproval(approvalId);
      return decide("REJECTED", actor, `Rejected ${current.orderId}`, reason || "No reason given.");
    },

    async listOrders() {
      return Object.values(orders);
    },
    async getOrder(id) {
      const found = Object.values(orders).find((order) => order.id === id);
      if (!found) throw new ApiError("NOT_FOUND", `Order ${id} was not found.`);
      return found;
    },
    async listAudit(filter) {
      return filter?.orderId ? audit.filter((event) => event.orderId === filter.orderId) : [...audit];
    },
    async submitChefRequest() {
      return { order: orders.needsApproval, substitutes, approval };
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
    async getMandate() {
      return mandate;
    },
  };
}
