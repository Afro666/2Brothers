import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { mapApprovalToken } from "@/api/http-approval-tokens";
import type { Api } from "@/api/types";

const ROW = {
  token_id: "atk-123",
  kind: "personal_approval",
  name: "chat",
  person: "buyer@example.com",
  kitchen_id: "demo-kitchen",
  prefix: "tka_exam",
  created_at: "2026-11-14T08:00:00+00:00",
  created_by: "buyer@example.com",
  expires_at: "2026-11-14T16:00:00+00:00",
  last_used_at: null,
  revoked_at: null,
};

afterEach(() => vi.unstubAllGlobals());

describe("Personal approval tokens over HTTP", () => {
  it("maps the contract row and keeps no secret", () => {
    expect(mapApprovalToken({ ...ROW, token: "tka_secret" })).toEqual({
      id: "atk-123",
      name: "chat",
      person: "buyer@example.com",
      prefix: "tka_exam",
      createdAt: "2026-11-14T08:00:00+00:00",
      createdBy: "buyer@example.com",
      expiresAt: "2026-11-14T16:00:00+00:00",
      lastUsedAt: null,
      revokedAt: null,
    });
    expect(() => mapApprovalToken({ ...ROW, expires_at: null })).toThrow();
    expect(() => mapApprovalToken({ ...ROW, last_used_at: 5 })).toThrow("last_used_at");
  });

  it("calls the three routes with the exact paths and bodies", async () => {
    const routes: { route: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      routes.push({ route: `${method} ${url}`, body: init.body ? JSON.parse(init.body as string) : null });
      const row = method === "DELETE" ? { ...ROW, revoked_at: "2026-11-14T09:00:00+00:00" } : ROW;
      return new Response(
        JSON.stringify(method === "GET" ? { tokens: [row] } : method === "POST" ? { ...row, token: "tka_once" } : row),
      );
    });
    const api = createHttpApi("/api");
    expect(api.live!.has("listApprovalTokens")).toBe(true);
    expect(api.live!.has("createApprovalToken")).toBe(true);
    expect(api.live!.has("revokeApprovalToken")).toBe(true);

    await expect(api.listApprovalTokens()).resolves.toEqual([mapApprovalToken(ROW)]);
    await expect(api.createApprovalToken({ hours: 8 })).resolves.toEqual({ ...mapApprovalToken(ROW), token: "tka_once" });
    await expect(api.createApprovalToken({ hours: 2, name: "desk" })).resolves.toHaveProperty("token", "tka_once");
    await expect(api.revokeApprovalToken("atk / 1")).resolves.toHaveProperty("revokedAt", "2026-11-14T09:00:00+00:00");
    expect(routes).toEqual([
      { route: "GET /api/v1/kitchens/demo-kitchen/approval-tokens", body: null },
      { route: "POST /api/v1/kitchens/demo-kitchen/approval-tokens", body: { hours: 8 } },
      { route: "POST /api/v1/kitchens/demo-kitchen/approval-tokens", body: { hours: 2, name: "desk" } },
      { route: "DELETE /api/v1/kitchens/demo-kitchen/approval-tokens/atk%20%2F%201", body: null },
    ]);
  });

  it("keeps the gateway's refusal codes", async () => {
    for (const [status, code, operation] of [
      [403, "PERSONAL_TOKEN_NEEDS_SIGN_IN", (api: Api) => api.createApprovalToken({ hours: 8 })],
      [403, "ROLE_REQUIRED", (api: Api) => api.createApprovalToken({ hours: 8 })],
      [403, "HUMAN_SESSION_REQUIRED", (api: Api) => api.listApprovalTokens()],
      [422, "INVALID_REQUEST", (api: Api) => api.createApprovalToken({ hours: 30 })],
      [404, "TOKEN_NOT_FOUND", (api: Api) => api.revokeApprovalToken("missing")],
    ] as const) {
      vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ error: { code, message: code } }), { status }));
      await expect(operation(createHttpApi("/api"))).rejects.toMatchObject({ status, code });
    }
  });
});
