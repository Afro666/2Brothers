import { object, rows, text } from "@/api/gateway-map";
import type { Api, ApprovalToken, CreatedApprovalToken } from "@/api/types";
import { ApiError } from "@/api/types";

type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

function nullableTimestamp(row: Record<string, unknown>, key: string): string | null {
  const value = row[key];
  if (value === null || value === undefined) return null;
  if (typeof value !== "string" || !value) {
    throw new ApiError("INVALID_RESPONSE", `The gateway sent ${key} in an unexpected shape.`);
  }
  return value;
}

/** `gateway/approval_tokens.py` row to the UI row; a create answer's secret is never kept here. */
export function mapApprovalToken(row: Record<string, unknown>): ApprovalToken {
  return {
    id: text(row.token_id, "an approval token id"),
    name: text(row.name, "an approval token name"),
    person: text(row.person, "the approval token's person"),
    prefix: text(row.prefix, "an approval token prefix"),
    createdAt: text(row.created_at, "an approval token creation time"),
    createdBy: text(row.created_by, "an approval token creator"),
    expiresAt: text(row.expires_at, "an approval token expiry time"),
    lastUsedAt: nullableTimestamp(row, "last_used_at"),
    revokedAt: nullableTimestamp(row, "revoked_at"),
  };
}

/** Personal approval tokens: `POST`, `GET`, `DELETE /v1/kitchens/{id}/approval-tokens` (docs/contract.md). */
export function createApprovalTokensHttp(
  call: GatewayCall,
  kitchen: string,
): Pick<Api, "listApprovalTokens" | "createApprovalToken" | "revokeApprovalToken"> {
  const base = `${kitchen}/approval-tokens`;
  return {
    async listApprovalTokens() {
      return rows(await call(base), "tokens").map(mapApprovalToken);
    },
    async createApprovalToken({ hours, name }): Promise<CreatedApprovalToken> {
      const body = name === undefined ? { hours } : { hours, name };
      const row = object(await call(base, { method: "POST", body: JSON.stringify(body) }), "the created approval token");
      return { ...mapApprovalToken(row), token: text(row.token, "the one-time approval token") };
    },
    async revokeApprovalToken(id) {
      return mapApprovalToken(
        object(await call(`${base}/${encodeURIComponent(id)}`, { method: "DELETE" }), "the revoked approval token"),
      );
    },
  };
}
