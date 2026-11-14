import { object } from "@/api/gateway-map";
import type { Api, ProposalExplanation } from "@/api/types";

/** The gateway request of api/http.ts: a path under the base URL, the parsed JSON back. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

/**
 * The checked explanation, or null when it is absent, not checked, in another language or not
 * usable. Nothing here throws for the card: a missing explanation leaves it as it is (#1173).
 */
export function mapProposalExplanation(value: unknown, language: "en" | "fi"): ProposalExplanation | null {
  if (value == null) return null;
  try {
    const row = object(value, "the explanation");
    if (row.checked !== true || row.language !== language) return null;
    if (typeof row.text !== "string" || row.text.trim() === "") return null;
    // "Written by" names the model the gateway names; without one the text is not shown.
    if (typeof row.model !== "string" || !row.model) return null;
    return {
      text: row.text,
      model: row.model,
      durationMs: typeof row.duration_ms === "number" && Number.isFinite(row.duration_ms) ? row.duration_ms : null,
    };
  } catch {
    return null;
  }
}

/**
 * `GET /v1/kitchens/{kitchen_id}/proposals/{proposal_id}?explanation_language=` against the real
 * gateway. Contract: docs/contract.md, "Optional Nemotron proposal explanation (#1173)".
 */
export function createExplanationHttp(call: GatewayCall, kitchen: string): Pick<Api, "getProposalExplanation"> {
  return {
    async getProposalExplanation(proposalId, language) {
      try {
        const body = object(
          await call(
            `${kitchen}/proposals/${encodeURIComponent(proposalId)}?explanation_language=${encodeURIComponent(language)}`,
          ),
          "the proposal",
        );
        return mapProposalExplanation(body.explanation, language);
      } catch {
        return null;
      }
    },
  };
}
