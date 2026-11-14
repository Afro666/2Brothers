import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { mapProposalExplanation } from "@/api/http-explanation";
import { createMockApi } from "@/api/mock";

const URL = "/api/v1/kitchens/demo-kitchen/proposals/prop-1?explanation_language=en";
const explanation = {
  text: "You chose 950 L of Valio Eila 3 %. It is over the €1,500 warning level.",
  language: "en",
  model: "nemotron-3.5-super-vl",
  checked: true,
  source_hash: "abc",
  duration_ms: 1540,
};

function gateway(answer: unknown, status = 200) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    calls.push(`${init.method ?? "GET"} ${url}`);
    return new Response(JSON.stringify(answer), { status });
  });
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("proposal explanation on the real gateway (#1173)", () => {
  it("asks for the proposal with the language and maps a checked explanation", async () => {
    const calls = gateway({ proposal_id: "prop-1", explanation });
    const api = createHttpApi("/api");
    expect(api.live!.has("getProposalExplanation")).toBe(true);
    await expect(api.getProposalExplanation("prop-1", "en")).resolves.toEqual({
      text: explanation.text,
      model: "nemotron-3.5-super-vl",
      durationMs: 1540,
    });
    expect(calls).toEqual([`GET ${URL}`]);
  });

  it("asks in Finnish when the person reads Finnish", async () => {
    const calls = gateway({ explanation: { ...explanation, language: "fi" } });
    await createHttpApi("/api").getProposalExplanation("prop-1", "fi");
    expect(calls).toEqual([`GET ${URL.replace("=en", "=fi")}`]);
  });

  it.each([
    ["null", null],
    ["absent", undefined],
    ["unchecked", { ...explanation, checked: false }],
    ["another language", { ...explanation, language: "fi" }],
    ["empty text", { ...explanation, text: "  " }],
    ["no text", { ...explanation, text: 42 }],
    ["not an object", "words"],
  ])("answers null for a %s explanation", (_what, value) => {
    expect(mapProposalExplanation(value, "en")).toBeNull();
  });

  it("answers null for a proposal without the field", () => {
    expect(mapProposalExplanation({ proposal_id: "prop-1" }, "en")).toBeNull();
  });

  it("keeps a missing duration or model without failing", () => {
    expect(mapProposalExplanation({ ...explanation, duration_ms: null, model: undefined }, "en")).toEqual({
      text: explanation.text,
      model: "",
      durationMs: null,
    });
  });

  it.each([404, 422, 500])("answers null, never an error, when the gateway says %i", async (status) => {
    gateway({ error: { code: "PROPOSAL_NOT_FOUND", message: "no" } }, status);
    await expect(createHttpApi("/api").getProposalExplanation("prop-1", "en")).resolves.toBeNull();
  });

  it("answers null when the network fails", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(createHttpApi("/api").getProposalExplanation("prop-1", "en")).resolves.toBeNull();
  });
});

describe("proposal explanation on the mock", () => {
  it("answers null by default, so the sample data looks as before", async () => {
    await expect(createMockApi().getProposalExplanation("APR-311", "en")).resolves.toBeNull();
  });

  it("gives the explanation a test asked for, in its own language", async () => {
    const api = createMockApi({
      explanations: { "APR-311": { fi: { text: "Valitsit 950 L.", model: "nemotron-3.5-super-vl", durationMs: 1200 } } },
    });
    await expect(api.getProposalExplanation("APR-311", "fi")).resolves.toEqual({
      text: "Valitsit 950 L.",
      model: "nemotron-3.5-super-vl",
      durationMs: 1200,
    });
    await expect(api.getProposalExplanation("APR-311", "en")).resolves.toBeNull();
  });
});
