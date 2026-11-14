import { object, text } from "@/api/gateway-map";
import type { Api, ModelUsage } from "@/api/types";
import { ApiError } from "@/api/types";

/** The gateway request of api/http.ts: a path under the base URL, the parsed JSON back. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

function count(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new ApiError(
      "INVALID_RESPONSE",
      `The gateway sent ${what} in an unexpected shape.`,
    );
  }
  return value;
}

/** `model_seconds` is a decimal string, for example "345.7". */
function seconds(value: unknown): number {
  const parsed =
    typeof value === "string" && value.trim() !== ""
      ? Number(value)
      : Number.NaN;
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new ApiError(
      "INVALID_RESPONSE",
      "The gateway sent the model seconds in an unexpected shape.",
    );
  }
  return parsed;
}

/** `GET /model-usage` -> the card on the About page. Contract: docs/contract.md, "Model usage". */
export function mapModelUsage(body: unknown): ModelUsage {
  const row = object(body, "the model usage");
  return {
    model: text(row.model, "the model name"),
    runs: count(row.runs, "the run count"),
    runsWithoutUsage: count(
      row.runs_without_usage,
      "the count of runs without usage",
    ),
    modelCalls: count(row.model_calls, "the model call count"),
    promptTokens: count(row.prompt_tokens, "the prompt token count"),
    completionTokens: count(
      row.completion_tokens,
      "the completion token count",
    ),
    modelSeconds: seconds(row.model_seconds),
  };
}

/** Model usage against the real gateway (gateway/model_usage.py). `kitchen` is `/v1/kitchens/{id}`. */
export function createUsageHttp(
  call: GatewayCall,
  kitchen: string,
): Pick<Api, "getModelUsage"> {
  return {
    async getModelUsage() {
      return mapModelUsage(await call(`${kitchen}/model-usage`));
    },
  };
}
