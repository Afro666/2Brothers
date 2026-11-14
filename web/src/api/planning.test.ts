import { describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { ApiError } from "@/api/types";

describe("mock API planning data", () => {
  it("creates, updates and deletes suppliers, and protects suppliers with products", async () => {
    const api = createMockApi();
    const created = await api.saveSupplier({
      name: "Test supplier",
      adapter: "manual",
      freeDeliveryThresholdEur: null,
      deliveryFeeEur: null,
      orderDays: null,
      cutoffTime: null,
      leadTimeDays: null,
    });
    const updated = await api.saveSupplier({ ...created, name: "Updated supplier" });

    expect(updated).toMatchObject({ id: created.id, name: "Updated supplier" });
    await api.deleteSupplier(created.id);
    await expect(api.deleteSupplier("SUP-BAKERY")).rejects.toMatchObject({ code: "IN_USE" });
  });

  it("keeps unknown stock counts null and records the count in the audit", async () => {
    const api = createMockApi();

    const stock = await api.submitStockCount(
      [
        { productId: "462775", onHand: 0 },
        { productId: "463335", onHand: null },
      ],
      "chef",
    );

    expect(stock.find((item) => item.productId === "463335")).toMatchObject({ onHand: null });
    expect((await api.listAudit()).at(-1)).toMatchObject({
      kind: "stock",
      actor: "chef",
      reason: "1 counted and 1 unknown.",
    });
  });

  it("rejects a stock count with an unknown product and leaves stock unchanged", async () => {
    const api = createMockApi();
    const before = (await api.getStock()).find((item) => item.productId === "462775");
    const auditBefore = (await api.listAudit()).length;

    await expect(
      api.submitStockCount(
        [
          { productId: "462775", onHand: 999 },
          { productId: "NOPE", onHand: 1 },
        ],
        "chef",
      ),
    ).rejects.toMatchObject({ code: "NOT_FOUND" });

    expect((await api.getStock()).find((item) => item.productId === "462775")).toEqual(before);
    expect(await api.listAudit()).toHaveLength(auditBefore);
  });

  it("rejects negative or non-finite stock counts", async () => {
    const api = createMockApi();
    for (const onHand of [-1, Number.NaN, Number.POSITIVE_INFINITY]) {
      await expect(api.submitStockCount([{ productId: "462775", onHand }], "chef")).rejects.toMatchObject({
        code: "INVALID",
      });
    }
  });

  it("calculates daily product demand from menu covers", async () => {
    const api = createMockApi();
    const demand = await api.getDemand("2026-11-16", "2026-11-16");
    const milk = demand.find((line) => line.productId === "463335");

    expect(milk).toMatchObject({
      productName: "Valio Eila 3 % milk",
      unit: "L",
      need: 30.6,
    });
    expect(milk?.why).toContain("180 covers x 0.15 L (Rice pudding)");
  });

  it("updates shared supplier forecasts and records the sharing change", async () => {
    const api = createMockApi();
    const before = (await api.getSupplierDemand("2026-11-16", "2026-11-16")).find((row) => row.productId === "463335");

    await api.setSharing("SUP-VALIO", false, "chef");
    const after = (await api.getSupplierDemand("2026-11-16", "2026-11-16")).find((row) => row.productId === "463335");

    expect(before?.forecastDemand).toBeGreaterThan(after?.forecastDemand ?? 0);
    expect(before?.kitchens).toBe((after?.kitchens ?? 0) + 1);
    expect((await api.listAudit()).at(-1)).toMatchObject({ kind: "forecast_share", actor: "chef" });
  });

  it("derives forecast totals and kitchen counts from the named kitchens", async () => {
    const api = createMockApi();
    const rows = await api.getSupplierDemand("2026-11-16", "2026-11-16");

    for (const row of rows) {
      expect(row.kitchens).toBe(row.byKitchen.length);
      expect(row.byKitchen.reduce((sum, kitchen) => sum + kitchen.demand, 0)).toBe(row.forecastDemand);
    }
  });

  it("includes the restaurant kitchen only while sharing with Valio", async () => {
    const api = createMockApi();
    const before = await api.getSupplierDemand("2026-11-16", "2026-11-16");
    const shared = before.find((row) => row.productId === "463335");
    expect(shared?.byKitchen.some((kitchen) => kitchen.kitchenId === "K00")).toBe(true);

    await api.setSharing("SUP-VALIO", false, "chef");
    const after = await api.getSupplierDemand("2026-11-16", "2026-11-16");
    const privateRow = after.find((row) => row.productId === "463335");
    expect(privateRow?.byKitchen.some((kitchen) => kitchen.kitchenId === "K00")).toBe(false);
  });

  it("allows sharing with a supplier added later, defaulting its consent to false", async () => {
    const api = createMockApi();
    const supplier = await api.saveSupplier({
      name: "New supplier",
      adapter: "manual",
      freeDeliveryThresholdEur: null,
      deliveryFeeEur: null,
      orderDays: null,
      cutoffTime: null,
      leadTimeDays: null,
    });

    expect(await api.getSharing()).toContainEqual({ supplierId: supplier.id, shared: false });
    const returned = await api.setSharing(supplier.id, true, "chef");
    expect(returned).toEqual(await api.getSharing());
    expect(returned).toContainEqual({ supplierId: supplier.id, shared: true });
    expect((await api.listAudit()).at(-1)).toMatchObject({ kind: "forecast_share", actor: "chef" });
  });

  it("removes a deleted supplier's consent", async () => {
    const api = createMockApi();
    await api.deleteSupplier("SUP-VALIO");

    const sharing = await api.getSharing();
    expect(sharing.map((consent) => consent.supplierId)).toEqual(["SUP-BAKERY", "SUP-FISH"]);
    expect(await api.setSharing("SUP-FISH", true, "chef")).toHaveLength(2);
    // The consent went with the supplier, so Valio no longer sees this kitchen.
    const rows = await api.getSupplierDemand("2026-11-16", "2026-11-16");
    expect(rows.flatMap((row) => row.byKitchen).some((kitchen) => kitchen.kitchenId === "K00")).toBe(false);
  });

  it("marks supplier demand with unknown availability as UNKNOWN", async () => {
    const api = createMockApi();
    const milk = (await api.getSupplierDemand("2026-11-16", "2026-11-16")).find((row) => row.productId === "463335");

    expect(milk).toMatchObject({ available: null, risk: "UNKNOWN", suggestedBuy: null });
  });

  it("proposes one order from the week's demand, net of counted stock", async () => {
    const api = createMockApi();
    const approvals = await api.listApprovals();

    expect(await api.proposeOrderForPlan("2026-11-16", "2026-11-22", "2026-11-16")).toMatchObject({
      status: "READY",
      totalInclVat: 719.6,
      lineCount: 4,
      needCount: 5,
      // Eila milk and the cinnamon buns were never counted.
      uncountedCount: 2,
      // The salmon has no price in the sample data.
      shortfallCount: 1,
    });
    // A proposal only: nothing is approved or placed by it.
    expect(await api.listApprovals()).toEqual(approvals);
  });

  it("answers NOTHING_NEEDED for a week with no menu entries, or when stock covers the plan", async () => {
    const api = createMockApi();
    await expect(api.proposeOrderForPlan("2026-11-23", "2026-11-29", "2026-11-23")).rejects.toMatchObject({
      code: "NOTHING_NEEDED",
    });

    await api.saveMenuPlan("2026-W48", [{ date: "2026-11-23", meal: "Lunch", recipeId: "REC-SALMON-SOUP", covers: 1 }]);
    await api.submitStockCount([{ productId: "462775", onHand: 18 }], "chef");
    await expect(api.proposeOrderForPlan("2026-11-23", "2026-11-29", "2026-11-23")).rejects.toMatchObject({
      code: "NOTHING_NEEDED",
    });
  });

  it("rejects blank names and invalid menu cover values", async () => {
    const api = createMockApi();
    await expect(
      api.saveSupplier({
        name: " ",
        adapter: "manual",
        freeDeliveryThresholdEur: null,
        deliveryFeeEur: null,
        orderDays: null,
        cutoffTime: null,
        leadTimeDays: null,
      }),
    ).rejects.toBeInstanceOf(ApiError);
    await expect(
      api.saveMenuPlan("2026-W47", [
        {
          date: "2026-11-16",
          meal: "lunch",
          recipeId: "REC-SALMON-SOUP",
          covers: 1.5,
        },
      ]),
    ).rejects.toMatchObject({ code: "INVALID" });
  });
});
