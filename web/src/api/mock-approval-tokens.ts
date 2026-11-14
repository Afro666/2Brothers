import type { Api, ApprovalToken } from "@/api/types";
import { ApiError } from "@/api/types";

const HOUR_MS = 3_600_000;

/**
 * A per-Api in-memory store of personal approval tokens, with the gateway's rules:
 * hours 1 to 24, a name of 1 to 80 characters, the secret only in the create answer.
 * `person` is the signed-in account's email, or null in the open demo (403, as on the gateway).
 */
export function createApprovalTokensMock(
  person: () => Promise<string | null> = async () => "buyer@demo.kitchen",
): Pick<Api, "listApprovalTokens" | "createApprovalToken" | "revokeApprovalToken"> {
  const tokens: ApprovalToken[] = [];
  let sequence = 0;
  const signedIn = async () => {
    const email = await person();
    if (!email) {
      throw new ApiError(
        "PERSONAL_TOKEN_NEEDS_SIGN_IN",
        "a personal approval token needs a real signed-in account",
        {},
        403,
      );
    }
    return email;
  };
  return {
    async listApprovalTokens() {
      const email = await signedIn();
      return structuredClone(tokens.filter((token) => token.person === email));
    },
    async createApprovalToken({ hours, name = "chat" }) {
      const email = await signedIn();
      if (!Number.isInteger(hours) || hours < 1 || hours > 24) {
        throw new ApiError("INVALID_REQUEST", "hours: an integer from 1 to 24", {}, 422);
      }
      const trimmed = name.trim();
      if (!trimmed || trimmed.length > 80) {
        throw new ApiError("INVALID_REQUEST", "name: 1 to 80 characters", {}, 422);
      }
      sequence += 1;
      const token = `tka_demo_${sequence.toString().padStart(4, "0")}`;
      const now = Date.now();
      const row: ApprovalToken = {
        id: `approval-token-demo-${sequence}`,
        name: trimmed,
        person: email,
        prefix: token.slice(0, 8),
        createdAt: new Date(now).toISOString(),
        createdBy: email,
        expiresAt: new Date(now + hours * HOUR_MS).toISOString(),
        lastUsedAt: null,
        revokedAt: null,
      };
      tokens.unshift(row);
      return { ...structuredClone(row), token };
    },
    async revokeApprovalToken(id) {
      const email = await signedIn();
      const row = tokens.find((token) => token.id === id && token.person === email);
      if (!row) throw new ApiError("TOKEN_NOT_FOUND", "no such approval token in this kitchen", {}, 404);
      if (row.revokedAt === null) row.revokedAt = new Date().toISOString();
      return structuredClone(row);
    },
  };
}
