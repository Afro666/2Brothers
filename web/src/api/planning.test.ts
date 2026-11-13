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

  it("marks supplier demand with unknown availability as UNKNOWN", async () => {
    const api = createMockApi();
    const milk = (await api.getSupplierDemand("2026-11-16", "2026-11-16")).find((row) => row.productId === "463335");

    expect(milk).toMatchObject({ available: null, risk: "UNKNOWN", suggestedBuy: null });
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
