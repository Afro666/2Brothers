import type { Api } from "@/api/types";

/**
 * The gateway serves neither route yet, so the screen runs on these values.
 * The thresholds are the ones in the earned auto-approve issue (#299):
 * 4 weeks, 20 decisions, at most 10 % of them edited.
 */
export const permissionsMock: Pick<Api, "getPermissions" | "getAutoApproveLearning"> = {
  async getPermissions() {
    return {
      alone: [
        { action: "Search the catalog", auditKind: "search" },
        { action: "Compare price, reliability and carbon", auditKind: "offer" },
        { action: "Choose products", auditKind: "offer" },
        { action: "Size quantities", auditKind: "simulate" },
        { action: "Split an order", auditKind: "simulate" },
        { action: "Refuse unsafe lines", auditKind: "mandate_check" },
        { action: "Ask for approval", auditKind: "approval" },
      ],
      person: [
        { action: "Every order", auditKind: "approval" },
        { action: "Any substitute", auditKind: "approval" },
        { action: "Standing-order changes", auditKind: "settings" },
        { action: "Sharing forecasts", auditKind: "forecast_share" },
      ],
      never: [
        { action: "Approve an order", auditKind: "approval" },
        { action: "Cancel an order", auditKind: "order" },
        { action: "Change a quantity after approval", auditKind: "order" },
      ],
    };
  },
  async getAutoApproveLearning() {
    return { weeks: 1, weeksNeeded: 4, decisions: 6, decisionsNeeded: 20, editRate: 2 / 6, maxEditRate: 0.1 };
  },
};
