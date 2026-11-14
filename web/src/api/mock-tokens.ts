import type { Api, ApiToken, ApiTokenScope } from "@/api/types";
import { ApiError } from "@/api/types";

const ALLOWED = new Set<ApiTokenScope>(["kitchen:read", "kitchen:propose", "kitchen:write"]);

/** A per-Api in-memory token store. Secrets exist only in the create response. */
export function createTokensMock(): Pick<Api, "listApiTokens" | "createApiToken" | "revokeApiToken"> {
  const tokens: ApiToken[] = [
    {
      id: "token-demo-reader",
      name: "Kitchen reader",
      scopes: ["kitchen:read"],
      prefix: "tkb_demo",
      createdAt: "2026-11-01T09:00:00Z",
      createdBy: "demo-visitor",
      lastUsedAt: null,
      revokedAt: null,
    },
  ];
  let sequence = 0;
  return {
    async listApiTokens() {
      return structuredClone(tokens);
    },
    async createApiToken({ name, scopes }) {
      const trimmed = name.trim();
      if (!trimmed || trimmed.length > 80) {
        throw new ApiError("INVALID_REQUEST", "name: 1 to 80 characters", {}, 422);
      }
      if (!scopes.length || scopes.some((scope) => !ALLOWED.has(scope))) {
        throw new ApiError(
          "INVALID_REQUEST",
          "scopes: at least one of kitchen:read, kitchen:propose, kitchen:write",
          {},
          422,
        );
      }
      sequence += 1;
      const token = `tkb_demo_${sequence.toString().padStart(4, "0")}`;
      const row: ApiToken = {
        id: `token-demo-${sequence}`,
        name: trimmed,
        scopes: [...new Set(scopes)].sort(),
        prefix: token.slice(0, 8),
        createdAt: new Date().toISOString(),
        createdBy: "demo-visitor",
        lastUsedAt: null,
        revokedAt: null,
      };
      tokens.unshift(row);
      return { ...structuredClone(row), token };
    },
    async revokeApiToken(id) {
      const row = tokens.find((token) => token.id === id);
      if (!row) throw new ApiError("TOKEN_NOT_FOUND", "no such token", {}, 404);
      if (row.revokedAt === null) row.revokedAt = new Date().toISOString();
      return structuredClone(row);
    },
  };
}
