import { afterEach, expect, it, vi } from "vitest";
import { createHttpApi, gatewayRequest } from "@/api/http";
import { dropKeptAnswers } from "@/lib/use-async";
afterEach(() => { dropKeptAnswers(); vi.unstubAllGlobals(); });
function deferredFetch() {
  const answers: ((r: Response) => void)[] = [];
  const fetch = vi.fn(() => new Promise<Response>((resolve) => answers.push(resolve)));
  vi.stubGlobal("fetch", fetch);
  return { fetch, answer: (i: number, value: unknown) => answers[i](new Response(JSON.stringify(value))) };
}
it("shares identical pending reads, but never reuses a completed response", async () => {
  const { fetch, answer } = deferredFetch();
  const a = gatewayRequest("/api", "/read"), b = gatewayRequest("/api", "/read");
  expect(fetch).toHaveBeenCalledTimes(1);
  answer(0, { revision: 1 });
  expect(await a).toEqual({ revision: 1 }); expect(await b).toEqual({ revision: 1 });
  const c = gatewayRequest("/api", "/read");
  expect(fetch).toHaveBeenCalledTimes(2);
  answer(1, { revision: 2 }); expect(await c).toEqual({ revision: 2 });
});
it("isolates base URLs, query parameters and acting users", async () => {
  const { fetch, answer } = deferredFetch();
  const all = [gatewayRequest("/api", "/read?a=1"), gatewayRequest("/api", "/read?a=2"), gatewayRequest("/other", "/read?a=1"), gatewayRequest("/api", "/read?a=1", { headers: { "X-User": "chef" } })];
  expect(fetch).toHaveBeenCalledTimes(4);
  all.forEach((_, i) => answer(i, {})); await Promise.all(all);
});
it("invalidates reads before and after writes, and ignores a late old completion", async () => {
  const { fetch, answer } = deferredFetch();
  const old = gatewayRequest("/api", "/read");
  const write = gatewayRequest("/api", "/write", { method: "POST" });
  const during = gatewayRequest("/api", "/read");
  answer(1, {}); await write;
  const fresh = gatewayRequest("/api", "/read");
  expect(fetch).toHaveBeenCalledTimes(4);
  answer(0, {}); await old;
  const joined = gatewayRequest("/api", "/read"); expect(fetch).toHaveBeenCalledTimes(4);
  answer(2, {}); answer(3, { fresh: true }); await during;
  expect(await fresh).toEqual({ fresh: true }); expect(await joined).toEqual({ fresh: true });
});
it("does not retain failures or share abortable requests", async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError("offline")).mockResolvedValueOnce(new Response("{}"));
  vi.stubGlobal("fetch", fetch);
  await expect(gatewayRequest("/api", "/read")).rejects.toMatchObject({ code: "NETWORK" });
  await gatewayRequest("/api", "/read"); expect(fetch).toHaveBeenCalledTimes(2);
  const d = deferredFetch();
  const a = gatewayRequest("/api", "/read", { signal: new AbortController().signal });
  const b = gatewayRequest("/api", "/read", { signal: new AbortController().signal });
  expect(d.fetch).toHaveBeenCalledTimes(2); d.answer(0, {}); d.answer(1, {}); await Promise.all([a, b]);
});

it("a detected account change or expired session invalidates existing reads", async () => {
  const d = deferredFetch();
  const api = createHttpApi("/api");
  const old = gatewayRequest("/api", "/read");
  const loginCheck = api.getSession();
  d.answer(1, { kind: "human", name: "one@example.test", role: "chef", can_approve: false });
  await loginCheck;
  const after = gatewayRequest("/api", "/read");
  expect(d.fetch).toHaveBeenCalledTimes(3);
  const checkAgain = api.getSession();
  d.answer(3, { kind: "human", name: "two@example.test", role: "viewer", can_approve: false });
  await checkAgain;
  const changed = gatewayRequest("/api", "/read");
  expect(d.fetch).toHaveBeenCalledTimes(5);
  d.answer(0, {}); d.answer(2, {}); d.answer(4, {});
  await Promise.all([old, after, changed]);
});

it("never coalesces reads across different API instances", async () => {
  const d = deferredFetch();
  const a = createHttpApi("/api"), b = createHttpApi("/api");
  const first = a.countPendingApprovals!(), second = b.countPendingApprovals!();
  expect(d.fetch).toHaveBeenCalledTimes(2);
  d.answer(0, { proposals: [] }); d.answer(1, { proposals: [] });
  await Promise.all([first, second]);
});
