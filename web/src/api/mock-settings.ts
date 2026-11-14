import { ApiError, type Api, type AuditActor } from "@/api/types";
import { formatEur, formatNumber } from "@/lib/format";
import type { AuditEvent, DemandClass, KitchenSettings } from "@/types";

type SettingsApi = Pick<Api, "getKitchenSettings" | "saveKitchenSettings">;
type AuditRecorder = (event: Pick<AuditEvent, "kind" | "actor" | "summary" | "reason">) => void;

const DEFAULT_SETTINGS: KitchenSettings = {
  approveUnconfirmedManual: false,
  serviceLevelPercent: { A: 97.5, B: 95, C: 90 },
  maxDaysOfCover: [
    { category: "Dairy", maxDays: 5 },
    { category: "Bakery", maxDays: 2 },
    { category: "Fish", maxDays: 2 },
  ],
  stockOutDemandCap: 1.8,
  budgetWarningPerOrderExVat: 1500,
  budgetWarningPerWeekExVat: 6000,
  excludedAllergens: ["AP", "AN", "AS"],
};

const copy = <T>(value: T): T => structuredClone(value);
const demandClasses: DemandClass[] = ["A", "B", "C"];

function validate(settings: KitchenSettings): void {
  for (const demandClass of demandClasses) {
    const level = settings.serviceLevelPercent[demandClass];
    if (!Number.isFinite(level) || level < 50 || level > 99.9) {
      throw new ApiError("INVALID", `Service level ${demandClass} must be between 50 and 99.9 percent.`);
    }
  }
  if (
    !Number.isFinite(settings.stockOutDemandCap) ||
    settings.stockOutDemandCap < 1 ||
    settings.stockOutDemandCap > 3
  ) {
    throw new ApiError("INVALID", "Stock-out demand cap must be between 1 and 3.");
  }
  const categories = new Set<string>();
  for (const rule of settings.maxDaysOfCover) {
    const category = rule.category.trim();
    if (!category) throw new ApiError("INVALID", "Cover category names must not be blank.");
    if (categories.has(category.toLocaleLowerCase())) {
      throw new ApiError("INVALID", `Cover category ${category} is duplicated.`);
    }
    categories.add(category.toLocaleLowerCase());
    if (!Number.isInteger(rule.maxDays) || rule.maxDays < 1) {
      throw new ApiError("INVALID", `Days of cover for ${category} must be a whole number greater than or equal to 1.`);
    }
  }
  for (const [label, amount] of [
    ["Per-order budget warning", settings.budgetWarningPerOrderExVat],
    ["Weekly budget warning", settings.budgetWarningPerWeekExVat],
  ] as const) {
    if (amount !== null && (!Number.isFinite(amount) || amount < 0)) {
      throw new ApiError("INVALID", `${label} must be greater than or equal to zero, or empty.`);
    }
  }
}

function changedReason(previous: KitchenSettings, next: KitchenSettings): string[] {
  const changes: string[] = [];
  for (const demandClass of demandClasses) {
    const before = previous.serviceLevelPercent[demandClass];
    const after = next.serviceLevelPercent[demandClass];
    if (before !== after) {
      changes.push(`Service level ${demandClass}: ${formatNumber(before)} % to ${formatNumber(after)} %`);
    }
  }
  const previousCover = new Map(
    previous.maxDaysOfCover.map(({ category, maxDays }) => [
      category.trim().toLocaleLowerCase(),
      { category, maxDays },
    ]),
  );
  const nextCover = new Map(
    next.maxDaysOfCover.map(({ category, maxDays }) => [category.trim().toLocaleLowerCase(), { category, maxDays }]),
  );
  for (const [key, before] of previousCover) {
    const after = nextCover.get(key);
    if (!after) changes.push(`Days of cover ${before.category}: ${formatNumber(before.maxDays)} to not set`);
    else if (before.maxDays !== after.maxDays) {
      changes.push(
        `Days of cover ${after.category}: ${formatNumber(before.maxDays)} to ${formatNumber(after.maxDays)}`,
      );
    }
  }
  for (const [key, after] of nextCover) {
    if (!previousCover.has(key)) {
      changes.push(`Days of cover ${after.category}: not set to ${formatNumber(after.maxDays)}`);
    }
  }
  if (previous.stockOutDemandCap !== next.stockOutDemandCap) {
    changes.push(
      `Stock-out demand cap: ${formatNumber(previous.stockOutDemandCap)} to ${formatNumber(next.stockOutDemandCap)}`,
    );
  }
  if (previous.budgetWarningPerOrderExVat !== next.budgetWarningPerOrderExVat) {
    changes.push(
      `Per-order budget warning: ${
        previous.budgetWarningPerOrderExVat === null ? "not set" : formatEur(previous.budgetWarningPerOrderExVat)
      } to ${next.budgetWarningPerOrderExVat === null ? "not set" : formatEur(next.budgetWarningPerOrderExVat)}`,
    );
  }
  if (previous.budgetWarningPerWeekExVat !== next.budgetWarningPerWeekExVat) {
    changes.push(
      `Weekly budget warning: ${
        previous.budgetWarningPerWeekExVat === null ? "not set" : formatEur(previous.budgetWarningPerWeekExVat)
      } to ${next.budgetWarningPerWeekExVat === null ? "not set" : formatEur(next.budgetWarningPerWeekExVat)}`,
    );
  }
  const previousAllergens = new Set(previous.excludedAllergens);
  const nextAllergens = new Set(next.excludedAllergens);
  for (const code of previousAllergens) {
    if (!nextAllergens.has(code)) changes.push(`Excluded allergen ${code} removed`);
  }
  for (const code of nextAllergens) {
    if (!previousAllergens.has(code)) changes.push(`Excluded allergen ${code} added`);
  }
  return changes;
}

export function createSettingsMock(recordAudit: AuditRecorder): SettingsApi {
  let settings = copy(DEFAULT_SETTINGS);

  return {
    async getKitchenSettings() {
      return copy(settings);
    },
    async saveKitchenSettings(next, actor: AuditActor) {
      validate(next);
      const saved = copy(next);
      saved.maxDaysOfCover = saved.maxDaysOfCover.map((rule) => ({ ...rule, category: rule.category.trim() }));
      const changes = changedReason(settings, saved);
      settings = saved;
      if (changes.length > 0) {
        recordAudit({
          kind: "settings",
          actor,
          summary: "Kitchen settings updated",
          reason: changes.join("; "),
        });
      }
      return copy(settings);
    },
  };
}
