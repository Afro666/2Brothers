import { describe, expect, it } from "vitest";

import { createTokensMock } from "@/api/mock-tokens";

describe("In-memory API tokens", () => {
  it("returns the secret only on create and retains a revoked row", async () => {
    const api = createTokensMock();
    const created = await api.createApiToken({ name: "  Claude MCP  ", scopes: ["kitchen:propose"] });
    expect(created).toMatchObject({ name: "Claude MCP", token: expect.stringMatching(/^tkb_/) });
    expect((await api.listApiTokens())[0]).not.toHaveProperty("token");
    const revoked = await api.revokeApiToken(created.id);
    expect(revoked.revokedAt).toEqual(expect.any(String));
    expect(await api.revokeApiToken(created.id)).toEqual(revoked);
    expect((await api.listApiTokens()).find((token) => token.id === created.id)?.revokedAt).toBe(revoked.revokedAt);
  });

  it("uses the gateway's validation and not-found codes", async () => {
    const api = createTokensMock();
    await expect(api.createApiToken({ name: " ", scopes: ["kitchen:read"] })).rejects.toMatchObject({
      code: "INVALID_REQUEST",
      status: 422,
    });
    await expect(api.revokeApiToken("missing")).rejects.toMatchObject({ code: "TOKEN_NOT_FOUND", status: 404 });
  });
});
