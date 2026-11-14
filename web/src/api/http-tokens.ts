import { object, rows, text } from "@/api/gateway-map";
import type { Api, ApiToken, ApiTokenScope, CreatedApiToken } from "@/api/types";
import { ApiError } from "@/api/types";

type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

function optionalTimestamp(row: Record<string, unknown>, key: string): string | null | undefined {
  if (!Object.hasOwn(row, key)) return undefined;
  const value = row[key];
  if (value === null) return null;
  if (typeof value !== "string" || !value) {
    throw new ApiError("INVALID_RESPONSE", `The gateway sent ${key} in an unexpected shape.`);
  }
  return value;
}

/** `gateway/tokens.py::_out` to the UI row, without retaining a create response's secret. */
export function mapApiToken(row: Record<string, unknown>): ApiToken {
  if (!Array.isArray(row.scopes)) {
    throw new ApiError("INVALID_RESPONSE", "The gateway sent token scopes in an unexpected shape.");
  }
  const scopes = row.scopes.map((scope): ApiTokenScope => {
    if (scope !== "kitchen:read" && scope !== "kitchen:propose" && scope !== "kitchen:write") {
      throw new ApiError("INVALID_RESPONSE", "The gateway sent an unknown token scope.");
    }
    return scope;
  });
  return {
    id: text(row.token_id, "a token id"),
    name: text(row.name, "a token name"),
    scopes,
    prefix: text(row.prefix, "a token prefix"),
    createdAt: text(row.created_at, "a token creation time"),
    createdBy: text(row.created_by, "a token creator"),
    lastUsedAt: optionalTimestamp(row, "last_used_at"),
    revokedAt: optionalTimestamp(row, "revoked_at") ?? null,
  };
}

/** Kitchen tokens against `POST`, `GET`, and `DELETE /v1/kitchens/{id}/tokens`. */
export function createTokensHttp(
  call: GatewayCall,
  kitchen: string,
): Pick<Api, "listApiTokens" | "createApiToken" | "revokeApiToken"> {
  const tokenPath = (id: string) => `${kitchen}/tokens/${encodeURIComponent(id)}`;
  return {
    async listApiTokens() {
      return rows(await call(`${kitchen}/tokens`), "tokens").map(mapApiToken);
    },
    async createApiToken({ name, scopes }): Promise<CreatedApiToken> {
      const row = object(
        await call(`${kitchen}/tokens`, { method: "POST", body: JSON.stringify({ name, scopes }) }),
        "the created token",
      );
      return { ...mapApiToken(row), token: text(row.token, "the one-time token secret") };
    },
    async revokeApiToken(id) {
      return mapApiToken(object(await call(tokenPath(id), { method: "DELETE" }), "the revoked token"));
    },
  };
}
