import { describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { confirmedDemoApproval as approval, approval as unknownApproval, milkOptions } from "@/mocks/milk-case";

const DECISION = {
  approvalId: approval.id,
  expectedTotalExVat: approval.totalExVat,
  expectedTotalInclVat: approval.totalInclVat,
};

describe("mock API approvals", () => {
  it("places the measured-stock demo once while leaving unknown stock pending", async () => {
    const api = createMockApi();
    await api.approve(DECISION, "human");
    expect((await api.getOrder(approval.orderId)).status).toBe("PLACED");
    await expect(api.approve(DECISION, "human")).rejects.toMatchObject({ code: "ALREADY_DECIDED" });
    const events = await api.listAudit({ orderId: approval.orderId });
    expect(events.filter((event) => event.kind === "order")).toHaveLength(1);
    await expect(api.approve({ approvalId: unknownApproval.id,
      expectedTotalExVat: unknownApproval.totalExVat,
      expectedTotalInclVat: unknownApproval.totalInclVat }, "human")).rejects.toMatchObject({ code: "STOCK_UNKNOWN" });
    expect((await api.getApproval(unknownApproval.id)).status).toBe("PENDING");
  });

  it("approves, and records who approved in the audit log", async () => {
    const api = createMockApi();
    const before = (await api.listAudit({ orderId: approval.orderId })).length;

    const decided = await api.approve(DECISION, "human");

    expect(decided.status).toBe("APPROVED");
    expect((await api.listApprovals())[0].status).toBe("APPROVED");
    const after = await api.listAudit({ orderId: approval.orderId });
    expect(after).toHaveLength(before + 2);
    expect(after.at(-2)).toMatchObject({ kind: "approval", actor: "human", orderId: approval.orderId });
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

describe("mock API products by id", () => {
  it("returns the catalog products in the requested order's place and leaves unknown ids out", async () => {
    const api = createMockApi();
    const found = await api.getProducts(["462775", "missing", "463335"]);

    expect(found.map((product) => product.id)).toEqual(["462775", "463335"]);
    expect(found[0].names.en).toBe("Arla 1 L lactose free fat free UHT milk drink");
  });

  it("returns nothing for an empty list", async () => {
    expect(await createMockApi().getProducts([])).toEqual([]);
  });
});

describe("mock API product search filters", () => {
  it("removes products with no allergen data only when the search is strict", async () => {
    const api = createMockApi();
    const lenient = await api.searchProducts("milk", { excludedAllergens: ["AM"] });
    const strict = await api.searchProducts("milk", { excludedAllergens: ["AM"], strictAllergens: true });
    const strictOnly = await api.searchProducts("milk", { strictAllergens: true });

    expect(lenient.map((product) => product.id)).toEqual(["464179"]);
    expect(strict).toEqual([]);
    expect(strictOnly.map((product) => product.id)).not.toContain("464179");
    expect(strictOnly).toHaveLength(4);
  });

  it("keeps only products that carry every required label", async () => {
    const api = createMockApi();
    const organic = await api.searchProducts("", { requiredLabels: ["EU_ORGANIC_FARMING"] });
    const swan = await api.searchProducts("milk", { requiredLabels: ["GOODS_FROM_FINLAND_BLUE_SWAN"] });
    const both = await api.searchProducts("", {
      requiredLabels: ["EU_ORGANIC_FARMING", "GOODS_FROM_FINLAND_BLUE_SWAN"],
    });

    expect(organic.map((product) => product.id)).toEqual(["462921"]);
    expect(swan.map((product) => product.id)).toEqual(["462921", "463038", "463335"]);
    expect(both.map((product) => product.id)).toEqual(["462921"]);
  });

  it("filters by temperature and never matches products without temperature data", async () => {
    const api = createMockApi();
    const ambient = await api.searchProducts("", { temperature: "ambient" });
    const chilled = await api.searchProducts("", { temperature: "chilled" });
    const frozen = await api.searchProducts("", { temperature: "frozen" });

    expect(ambient.map((product) => product.id)).toEqual(["462775"]);
    expect(chilled.map((product) => product.id)).toEqual(["462921", "463038", "463335"]);
    expect(frozen).toEqual([]);
    expect(chilled.map((product) => product.id)).not.toContain("464179");
  });

  it("lists every product for an empty query and combines filters", async () => {
    const api = createMockApi();
    const all = await api.searchProducts("");
    const combined = await api.searchProducts("", {
      excludedAllergens: ["AM"],
      strictAllergens: true,
      requiredLabels: ["GOODS_FROM_FINLAND_BLUE_SWAN"],
      temperature: "chilled",
    });

    expect(all).toHaveLength(5);
    expect(combined).toEqual([]);
  });
});

describe("mock API proposal changes", () => {
  it("resimulates totals and MOV from line prices and tax rates", async () => {
    const api = createMockApi();
    const result = await api.changeProposal(
      unknownApproval.orderId,
      {
        type: "SET_QUANTITY",
        productId: "463335",
        quantity: 900,
      },
      "human",
    );

    expect(result.order.totalExVat).toBe(1845);
    expect(result.order.totalInclVat).toBe(2094.08);
    expect(result.order.mov?.current).toBe(1845);
    expect(result.approval).toMatchObject({ totalExVat: 1845, totalInclVat: 2094.08, lineCount: 1 });
  });

  it("only allows proposal changes while its approval is pending", async () => {
    const api = createMockApi();
    await api.approve(DECISION, "human");
    await expect(
      api.changeProposal(
        approval.orderId,
        {
          type: "SET_QUANTITY",
          productId: "463335",
          quantity: 900,
        },
        "human",
      ),
    ).rejects.toMatchObject({ code: "ALREADY_DECIDED" });
  });
});

describe("mock API options", () => {
  const [optionA, optionB, optionC] = milkOptions;

  it("re-simulates the chosen option to its exact total and approves nothing", async () => {
    const api = createMockApi();
    const chosen = await api.chooseOption!(approval.id, optionA.id, "human");
    expect(chosen).toMatchObject({ status: "PENDING", totalExVat: 2050, totalInclVat: optionA.totalInclVat });
    expect(chosen.options?.filter((option) => option.chosen).map((option) => option.id)).toEqual([optionA.id]);
    expect((await api.getOrder(approval.orderId)).status).toBe("NEEDS_APPROVAL");
    // Option A's stock is not measured: the existing approval rule still refuses it.
    await expect(
      api.approve(
        { approvalId: approval.id, expectedTotalExVat: 2050, expectedTotalInclVat: optionA.totalInclVat },
        "human",
      ),
    ).rejects.toMatchObject({ code: "STOCK_UNKNOWN" });

    const back = await api.chooseOption!(approval.id, optionC.id, "human");
    expect(back).toMatchObject({ totalExVat: approval.totalExVat, totalInclVat: optionC.totalInclVat });
  });

  it("refuses an option whose cut-off has passed, and an option it does not know", async () => {
    const api = createMockApi();
    await expect(api.chooseOption!(approval.id, optionB.id, "human")).rejects.toMatchObject({ code: "CLOSING_PASSED" });
    await expect(api.chooseOption!(approval.id, "nope", "human")).rejects.toMatchObject({ code: "NOT_FOUND" });
    expect((await api.getApproval(approval.id)).totalInclVat).toBe(approval.totalInclVat);
  });

  it("marks no option as proposed once a person edits the basket", async () => {
    const api = createMockApi();
    const result = await api.changeProposal(
      approval.orderId,
      { type: "SET_QUANTITY", productId: "462775", quantity: 40 },
      "human",
    );
    expect(result.approval.options?.some((option) => option.chosen)).toBe(false);
  });
});
