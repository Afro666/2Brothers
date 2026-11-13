import { describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { approval } from "@/mocks/milk-case";

const DECISION = {
  approvalId: approval.id,
  expectedTotalExVat: approval.totalExVat,
  expectedTotalInclVat: approval.totalInclVat,
};

describe("mock API approvals", () => {
  it("approves, and records who approved in the audit log", async () => {
    const api = createMockApi();
    const before = (await api.listAudit({ orderId: approval.orderId })).length;

    const decided = await api.approve(DECISION, "human");

    expect(decided.status).toBe("APPROVED");
    expect((await api.listApprovals())[0].status).toBe("APPROVED");
    const after = await api.listAudit({ orderId: approval.orderId });
    expect(after).toHaveLength(before + 1);
    expect(after.at(-1)).toMatchObject({ kind: "approval", actor: "human", orderId: approval.orderId });
  });

  it("keeps the approval pending when the gateway refuses it", async () => {
    const api = createMockApi();
    const before = (await api.listAudit()).length;
    api.failNextApprove("TOTAL_MISMATCH");

    await expect(api.approve(DECISION, "human")).rejects.toMatchObject({ code: "TOTAL_MISMATCH" });

    expect((await api.getApproval(approval.id)).status).toBe("PENDING");
    expect(await api.listAudit()).toHaveLength(before);
    await expect(api.approve(DECISION, "human")).resolves.toMatchObject({ status: "APPROVED" });
  });

  it("refuses a total the human did not read", async () => {
    const api = createMockApi();
    const stale = { ...DECISION, expectedTotalInclVat: DECISION.expectedTotalInclVat + 1 };
    await expect(api.approve(stale, "human")).rejects.toMatchObject({ code: "TOTAL_MISMATCH" });
  });

  it("refuses a second decision", async () => {
    const api = createMockApi();
    await api.reject(approval.id, "Wrong fat percentage", "chef");
    await expect(api.approve(DECISION, "human")).rejects.toMatchObject({ code: "ALREADY_DECIDED" });
    expect((await api.listAudit()).at(-1)).toMatchObject({ actor: "chef", reason: "Wrong fat percentage" });
  });

  it("gives each instance its own state", async () => {
    const first = createMockApi();
    await first.approve(DECISION, "human");
    expect((await createMockApi().getApproval(approval.id)).status).toBe("PENDING");
  });
});

describe("mock API product search", () => {
  it("removes products with an excluded allergen and keeps products with no allergen data", async () => {
    const api = createMockApi();
    const all = await api.searchProducts("milk");
    const withoutMilk = await api.searchProducts("milk", { excludedAllergens: ["AM"] });

    expect(all.length).toBeGreaterThan(withoutMilk.length);
    expect(withoutMilk.map((product) => product.id)).toEqual(["464179"]);
    expect(withoutMilk[0].allergens).toBeNull();
  });
});
