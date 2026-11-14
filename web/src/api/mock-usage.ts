import type { ModelUsage } from "@/api/types";

/** Sample numbers for the mock API. Against the gateway they come from GET /model-usage (api/http-usage.ts). */
export function modelUsageMock(): ModelUsage {
  return {
    model: "nemotron-3.5-super-vl",
    runs: 14,
    runsWithoutUsage: 5,
    modelCalls: 63,
    promptTokens: 371250,
    completionTokens: 16470,
    modelSeconds: 345.7,
  };
}
