import { afterEach, expect, it, vi } from "vitest";
import { createHttpApi } from "@/api/http";
import { proposal } from "@/test/gateway-fixtures";

afterEach(() => vi.unstubAllGlobals());

it("uses the kitchen-wide pending count without loading older pages", async () => {
  const fetch = vi.fn(async () => new Response(JSON.stringify({ proposals: [], next_cursor: "older", pending_count: 7 })));
  vi.stubGlobal("fetch", fetch);
  expect(await createHttpApi("/api").countPendingApprovals!()).toBe(7);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("loads older approval pages and keeps the pending count independent of page size", async () => {
  vi.stubGlobal("fetch", async (url: string) => {
    const body = url.endsWith("/audit") ? { events: [] }
      : url.includes("?cursor=") ? { proposals: [{ ...proposal, proposal_id: "older" }], next_cursor: null }
      : { proposals: [{ ...proposal, proposal_id: "newer" }], next_cursor: "next", pending_count: 2 };
    return new Response(JSON.stringify(body));
  });
  const api = createHttpApi("/api");
  expect((await api.listApprovals()).map((p) => p.id)).toEqual(["newer", "older"]);
  expect(await api.countPendingApprovals!()).toBe(2);
});

it("registers the learned-facts HTTP adapter in live mode", async () => {
  const fetch = vi.fn(async (_url: string) => new Response(JSON.stringify({ facts: [] })));
  vi.stubGlobal("fetch", fetch);
  const api = createHttpApi("/api");
  expect(api.live?.has("listLearnedFacts")).toBe(true);
  expect(api.live?.has("setLearnedFactActive")).toBe(true);
  expect(await api.listLearnedFacts()).toEqual([]);
  expect(fetch.mock.calls[0][0]).toBe("/api/v1/kitchens/demo-kitchen/learned");
});
