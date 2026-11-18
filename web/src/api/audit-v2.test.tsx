import { afterEach, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { createEventsHttp } from "@/api/http-events";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it("keeps the session when an older /v1/me answer arrives after a newer sign-in", async () => {
  let answerMe!: (response: Response) => void;
  const writes: RequestInit[] = [];
  vi.stubGlobal("fetch", (url: string, init: RequestInit = {}) => {
    if (url.endsWith("/v1/me")) return new Promise<Response>((resolve) => { answerMe = resolve; });
    if (url.endsWith("/auth/login")) {
      return Promise.resolve(new Response(JSON.stringify({ email: "new@example.test", name: "New", role: "approver" })));
    }
    writes.push(init);
    return Promise.resolve(new Response("{}"));
  });
  const api = createHttpApi("/api");

  const old = api.getSession();
  await api.signIn("new@example.test", "fixture-password");
  answerMe(new Response(JSON.stringify({ error: { code: "UNAUTHENTICATED" } }), { status: 401 }));

  expect(await old).toMatchObject({ email: "new@example.test", name: "New" });
  await api.chooseOption!("p", "o", "human").catch(() => undefined);
  expect(new Headers(writes[0].headers).has("X-User")).toBe(false);
});

it("keeps the change key when the response cannot be mapped, so a retry repeats it", async () => {
  const keys: string[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    if (url.endsWith("/change")) keys.push(JSON.parse(String(init.body)).idempotency_key);
    return new Response(JSON.stringify(url.endsWith("/audit") ? { events: [] } : {}));
  });
  const api = createHttpApi("/api");
  const change = { type: "ADD_LINE" as const, productId: "x", quantity: 1 };

  await expect(api.changeProposal("p", change, "human")).rejects.toBeDefined();
  await expect(api.changeProposal("p", change, "human")).rejects.toBeDefined();

  expect(keys).toHaveLength(2);
  expect(keys[0]).toBe(keys[1]);
});

it("retries a temporary 503 from the event stream with the backoff", async () => {
  vi.useFakeTimers();
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({
    error: { code: "EVENTS_BUSY", message: "too many open event streams; try again later" },
  }), { status: 503 }));
  vi.stubGlobal("fetch", fetchMock);
  const api = createEventsHttp("/api", "/v1/kitchens/k", () => null);
  const stop = api.subscribeEvents!(() => {});

  await vi.advanceTimersByTimeAsync(0);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(4_999);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(9_999);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(1);
  expect(fetchMock).toHaveBeenCalledTimes(3);
  stop();
});

it("stops for good when the gateway has no change streams", async () => {
  vi.useFakeTimers();
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({
    error: { code: "EVENTS_UNAVAILABLE", message: "the event stream needs MongoDB change streams (a replica set)" },
  }), { status: 503 }));
  vi.stubGlobal("fetch", fetchMock);
  const api = createEventsHttp("/api", "/v1/kitchens/k", () => null);
  const stop = api.subscribeEvents!(() => {});

  await vi.advanceTimersByTimeAsync(120_000);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  stop();
});
