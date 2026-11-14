import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { mapModelUsage } from "@/api/http-usage";
import { createMockApi } from "@/api/mock";

const URL = "/api/v1/kitchens/demo-kitchen/model-usage";
const answer = {
  model: "nemotron-3.5-super-vl",
  since: "2026-11-14T18:02:11+00:00",
  runs: 14,
  finished_runs: 11,
  runs_without_usage: 5,
  model_calls: 63,
  prompt_tokens: 371250,
  completion_tokens: 16470,
  reasoning_tokens: 0,
  model_seconds: "345.7",
  last_run_at: "2026-11-14T22:40:03+00:00",
};

function gateway(body: unknown, status = 200) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    calls.push(`${init.method ?? "GET"} ${url}`);
    return new Response(JSON.stringify(body), { status });
  });
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("model usage on the real gateway", () => {
  it("reads GET /model-usage and maps the answer", async () => {
    const calls = gateway(answer);
    const api = createHttpApi("/api");
    expect(api.live!.has("getModelUsage")).toBe(true);
    await expect(api.getModelUsage()).resolves.toEqual({
      model: "nemotron-3.5-super-vl",
      runs: 14,
      runsWithoutUsage: 5,
      modelCalls: 63,
      promptTokens: 371250,
      completionTokens: 16470,
      modelSeconds: 345.7,
    });
    expect(calls).toEqual([`GET ${URL}`]);
  });

  it("maps a kitchen without runs to zeros", () => {
    expect(
      mapModelUsage({
        ...answer,
        since: null,
        runs: 0,
        finished_runs: 0,
        runs_without_usage: 0,
        model_calls: 0,
        prompt_tokens: 0,
        completion_tokens: 0,
        model_seconds: "0.0",
        last_run_at: null,
      }),
    ).toMatchObject({
      runs: 0,
      modelCalls: 0,
      promptTokens: 0,
      completionTokens: 0,
      modelSeconds: 0,
    });
  });

  it.each([
    ["a count that is text", { ...answer, model_calls: "63" }],
    ["a negative count", { ...answer, prompt_tokens: -1 }],
    ["a missing count", { ...answer, runs_without_usage: undefined }],
    [
      "seconds that are not a decimal string",
      { ...answer, model_seconds: "fast" },
    ],
    ["no model name", { ...answer, model: "" }],
    ["a list", [answer]],
  ])("refuses %s", (_, body) => {
    expect(() => mapModelUsage(body)).toThrow(
      expect.objectContaining({ code: "INVALID_RESPONSE" }),
    );
  });

  it("passes the gateway's error on", async () => {
    gateway(
      { error: { code: "SCOPE_REQUIRED", message: "kitchen:read is needed" } },
      403,
    );
    await expect(createHttpApi("/api").getModelUsage()).rejects.toMatchObject({
      code: "SCOPE_REQUIRED",
    });
  });
});

describe("model usage on the mock", () => {
  it("serves sample numbers", async () => {
    const usage = await createMockApi().getModelUsage();
    expect(usage.model).toBe("nemotron-3.5-super-vl");
    expect(usage.runs).toBeGreaterThan(usage.runsWithoutUsage);
    expect(usage.modelCalls).toBeGreaterThan(0);
  });
});
