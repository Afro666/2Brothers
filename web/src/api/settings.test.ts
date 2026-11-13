import { describe, expect, it } from "vitest";

import { ApiError } from "@/api/types";
import { createMockApi } from "@/api/mock";

describe("kitchen settings mock", () => {
  it("returns engine defaults and validates settings before saving", async () => {
    const api = createMockApi();
    const settings = await api.getKitchenSettings();

    expect(settings).toMatchObject({
      serviceLevelPercent: { A: 97.5, B: 95, C: 90 },
      stockOutDemandCap: 1.8,
      budgetWarningPerOrderExVat: 1500,
      budgetWarningPerWeekExVat: 6000,
      excludedAllergens: ["AP", "AN", "AS"],
    });
    expect(settings.maxDaysOfCover).toEqual([
      { category: "Dairy", maxDays: 5 },
      { category: "Bakery", maxDays: 2 },
      { category: "Fish", maxDays: 2 },
    ]);

    await expect(
      api.saveKitchenSettings(
        {
          ...settings,
          serviceLevelPercent: { ...settings.serviceLevelPercent, A: 100 },
        },
        "human",
      ),
    ).rejects.toMatchObject({
      code: "INVALID",
      message: "Service level A must be between 50 and 99.9 percent.",
    } satisfies Partial<ApiError>);
    expect(await api.getKitchenSettings()).toEqual(settings);
  });

  it("records a settings audit event with the changed service level", async () => {
    const api = createMockApi();
    const settings = await api.getKitchenSettings();
    await api.saveKitchenSettings(
      { ...settings, serviceLevelPercent: { ...settings.serviceLevelPercent, A: 98 } },
      "human",
    );

    expect((await api.listAudit()).at(-1)).toMatchObject({
      kind: "settings",
      actor: "human",
      summary: "Kitchen settings updated",
      reason: "Service level A: 97.5 % to 98 %",
    });
  });
});
