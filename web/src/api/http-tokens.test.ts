import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { mapApiToken } from "@/api/http-tokens";
import type { Api } from "@/api/types";

const ROW = {
  token_id: "token-123",
  name: "Inventory feed",
  scopes: ["kitchen:write", "kitchen:read"],
  prefix: "tkb_exam",
  created_at: "2026-11-14T08:00:00+00:00",
  created_by: "chef@example.com",
  last_used_at: null,
  revoked_at: null,
};

function gateway(answer: unknown, status = 200) {
  const calls: { route: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    calls.push({ route: `${init.method ?? "GET"} ${url}`, body: init.body ? JSON.parse(init.body as string) : null });
    return new Response(JSON.stringify(answer), { status });
  });
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("Kitchen API tokens", () => {
  it("maps the exact gateway row and does not invent an absent last-used value", () => {
    expect(mapApiToken(ROW)).toEqual({
      id: "token-123",
      name: "Inventory feed",
      scopes: ["kitchen:write", "kitchen:read"],
      prefix: "tkb_exam",
      createdAt: "2026-11-14T08:00:00+00:00",
      createdBy: "chef@example.com",
      lastUsedAt: null,
      revokedAt: null,
    });
    const { last_used_at: _absent, ...withoutLastUsed } = ROW;
    expect(mapApiToken(withoutLastUsed).lastUsedAt).toBeUndefined();
    expect(() => mapApiToken({ ...ROW, scopes: ["kitchen:approve"] })).toThrow("unknown token scope");
  });

  it("returns the secret with the mapped create row", async () => {
    gateway({ ...ROW, token: "tkb_shown_once" });
    const api = createHttpApi("/api");
    expect(api.live!.has("listApiTokens")).toBe(true);
    expect(api.live!.has("createApiToken")).toBe(true);
    expect(api.live!.has("revokeApiToken")).toBe(true);

    await expect(api.createApiToken({ name: "Claude", scopes: ["kitchen:read"] })).resolves.toEqual({
      ...mapApiToken(ROW),
      token: "tkb_shown_once",
    });
  });

  it("reads each response shape returned by its three routes", async () => {
    const routes: { route: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
      routes.push({
        route: `${init.method ?? "GET"} ${url}`,
        body: init.body ? JSON.parse(init.body as string) : null,
      });
      const method = init.method ?? "GET";
      const row = method === "DELETE" ? { ...ROW, revoked_at: "2026-11-14T09:00:00+00:00" } : ROW;
      return new Response(
        JSON.stringify(
          method === "GET" ? { tokens: [row] } : method === "POST" ? { ...row, token: "tkb_shown_once" } : row,
        ),
      );
    });
    const api = createHttpApi("/api");
    await expect(api.listApiTokens()).resolves.toHaveLength(1);
    await expect(
      api.createApiToken({ name: "Inventory feed", scopes: ["kitchen:read", "kitchen:write"] }),
    ).resolves.toHaveProperty("token", "tkb_shown_once");
    await expect(api.revokeApiToken("token / 123")).resolves.toHaveProperty("revokedAt", "2026-11-14T09:00:00+00:00");
    expect(routes).toEqual([
      { route: "GET /api/v1/kitchens/demo-kitchen/tokens", body: null },
      {
        route: "POST /api/v1/kitchens/demo-kitchen/tokens",
        body: { name: "Inventory feed", scopes: ["kitchen:read", "kitchen:write"] },
      },
      { route: "DELETE /api/v1/kitchens/demo-kitchen/tokens/token%20%2F%20123", body: null },
    ]);
  });

  it("preserves the exact validation, permission and not-found error codes", async () => {
    for (const [status, code, operation] of [
      [422, "INVALID_REQUEST", (api: Api) => api.createApiToken({ name: "", scopes: [] })],
      [403, "HUMAN_SESSION_REQUIRED", (api: Api) => api.createApiToken({ name: "Agent", scopes: ["kitchen:read"] })],
      [403, "ROLE_REQUIRED", (api: Api) => api.listApiTokens()],
      [404, "TOKEN_NOT_FOUND", (api: Api) => api.revokeApiToken("missing")],
    ] as const) {
      gateway({ error: { code, message: code } }, status);
      await expect(operation(createHttpApi("/api"))).rejects.toMatchObject({ status, code });
    }
  });
});
