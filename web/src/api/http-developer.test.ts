import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";

afterEach(() => vi.unstubAllGlobals());

describe("Developer gateway adapter", () => {
  it("lists, creates and tests real webhooks with snake_case mapping", async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
      calls.push({ url, init });
      if (url.endsWith("/webhooks") && !init.method) {
        return new Response(JSON.stringify({
          webhooks: [{ webhook_id: "hook-1", url: "https://hooks.example.com/one", events: ["ping", "order.placed"], created_at: "2026-11-14T10:00:00Z", created_by: "buyer" }],
          events: ["order.placed", "recall.alert"],
        }));
      }
      if (url.endsWith("/webhooks") && init.method === "POST") {
        return new Response(JSON.stringify({ webhook_id: "hook-2", url: "https://hooks.example.com/two", events: ["recall.alert"], created_at: null, created_by: "buyer", secret: "whsec_real" }));
      }
      return new Response(JSON.stringify({ delivery_id: "delivery-1", event: "ping", at: "2026-11-14T10:01:00Z", attempts: 1, status: 204, ok: true, error: null }));
    });
    const api = createHttpApi("/api");

    expect(api.live!.has("listWebhooks")).toBe(true);
    expect(api.live!.has("listRecentApiCalls")).toBe(false);
    await expect(api.listWebhooks()).resolves.toEqual({
      webhooks: [{ id: "hook-1", url: "https://hooks.example.com/one", events: ["ping", "order.placed"], createdAt: "2026-11-14T10:00:00Z", createdBy: "buyer" }],
      events: ["order.placed", "recall.alert"],
    });
    await expect(api.createWebhook({ url: "https://hooks.example.com/two", events: ["recall.alert"] }, "human")).resolves.toMatchObject({ id: "hook-2", secret: "whsec_real", createdAt: null });
    await expect(api.testWebhook("hook-2", "human")).resolves.toEqual({ id: "delivery-1", event: "ping", at: "2026-11-14T10:01:00Z", attempts: 1, status: 204, ok: true, error: null });

    expect(calls[0].url).toBe("/api/v1/kitchens/demo-kitchen/webhooks");
    expect(JSON.parse(calls[1].init.body as string)).toEqual({ url: "https://hooks.example.com/two", events: ["recall.alert"] });
    expect(calls[2].url).toBe("/api/v1/kitchens/demo-kitchen/webhooks/hook-2/test");
    expect(calls[2].init.method).toBe("POST");
  });

  it("removes a webhook with DELETE and the acting person", async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({ webhook_id: "hook-1", deleted: true }));
    });
    const api = createHttpApi("/api");

    expect(api.live!.has("deleteWebhook")).toBe(true);
    await expect(api.deleteWebhook("hook/1", "human")).resolves.toBeUndefined();
    expect(calls[0].url).toBe("/api/v1/kitchens/demo-kitchen/webhooks/hook%2F1");
    expect(calls[0].init.method).toBe("DELETE");
    expect(new Headers(calls[0].init.headers).get("X-User")).toBe("human");
  });

  it("reads health and leaves Valio mode unknown when the route does not report it", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ status: "ok" })));
    const api = createHttpApi("/api");
    await expect(api.getGatewayHealth()).resolves.toEqual({ status: "ok", valioMode: "unknown" });
  });

  it("rejects a webhook response whose webhooks field is not an array", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ webhooks: {}, events: [] })));
    const api = createHttpApi("/api");

    await expect(api.listWebhooks()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it.each(["ping", ["ping", 42]])("rejects a webhook whose events are not an array of strings: %j", async (events) => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({
      webhooks: [{ webhook_id: "hook-1", url: "https://hooks.example.com/one", events }],
      events: [],
    })));
    const api = createHttpApi("/api");

    await expect(api.listWebhooks()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
});
