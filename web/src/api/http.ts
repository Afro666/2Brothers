import { type Json, mapAddable, mapApproval, mapAudit, mapOrder, rows } from "@/api/gateway-map";
import { mapMoney } from "@/api/map";
import { forecastWindow, mapForecastAccuracy } from "@/api/map-forecast";
import { createMockApi } from "@/api/mock";
import type { Api, AuditActor } from "@/api/types";
import { ApiError } from "@/api/types";
import { formatEur } from "@/lib/format";

/** One JSON call to the gateway. Gateway errors (`{"error": {code, message}}`) become `ApiError`. */
export async function gatewayRequest(baseUrl: string, path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("NETWORK", "Could not reach the gateway.");
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError("INVALID_RESPONSE", "The gateway did not return JSON.");
  }
  if (!response.ok) {
    const error = (body as { error?: { code?: unknown; message?: unknown } } | null)?.error;
    throw new ApiError(
      typeof error?.code === "string" ? error.code : "GATEWAY_ERROR",
      typeof error?.message === "string" ? error.message : `The gateway answered ${response.status}.`,
      error && typeof error === "object" ? (error as Record<string, unknown>) : {},
    );
  }
  return body;
}

/** Maps each row on its own: a row that does not map is logged and skipped, not fatal for the list. */
function mapEach<T>(list: Json[], what: string, idKey: string, map: (row: Json) => T): T[] {
  return list.flatMap((row) => {
    try {
      return [map(row)];
    } catch (error) {
      console.warn(`Skipped ${what} ${String(row?.[idKey] ?? "(no id)")}:`, error);
      return [];
    }
  });
}

/**
 * Hybrid: the order flow (proposals, approve and reject, orders, audit) talks to the real
 * gateway; every other method still answers from the mock, and `live` says which is which.
 *
 * No Authorization header is sent: in production the web server adds the gateway's human
 * token (web/Caddyfile). A decision names the person's role in `X-User`.
 */
export function createHttpApi(baseUrl: string): Api {
  const kitchen = `/v1/kitchens/${encodeURIComponent(import.meta.env.VITE_GATEWAY_KITCHEN_ID || "demo-kitchen")}`;
  const proposalPath = (id: string) => `${kitchen}/proposals/${encodeURIComponent(id)}`;
  const get = (path: string) => gatewayRequest(baseUrl, path);
  const post = (path: string, body: Json, actor?: AuditActor) =>
    gatewayRequest(baseUrl, path, {
      method: "POST",
      headers: actor ? { "X-User": actor } : undefined,
      body: JSON.stringify(body),
    });
  // The gateway lists at most its 100 newest proposals.
  const proposals = async () => rows(await get(`${kitchen}/proposals`), "proposals");
  const auditEvents = async () => rows(await get(`${kitchen}/audit`), "events");
  const approval = async (id: string) => {
    const [proposal, events] = await Promise.all([get(proposalPath(id)), auditEvents()]);
    return mapApproval(proposal as Json, events);
  };
  // One key per ask, kept after a failure: a new key could create a second proposal.
  const requestKeys = new Map<string, string>();

  const real = {
    async listApprovals() {
      const [list, events] = await Promise.all([proposals(), auditEvents()]);
      return mapEach(list, "proposal", "proposal_id", (proposal) => mapApproval(proposal, events));
    },
    getApproval: approval,
    async approve(decision, actor) {
      const total = decision.expectedTotalInclVat.toFixed(2);
      try {
        await post(
          `${proposalPath(decision.approvalId)}/approve`,
          {
            // The gateway reads `expected_total`; docs/contract.md asks for `blocks`. Both say the same figure.
            expected_total: total,
            blocks: [{ supplier_id: "sup-valio", expected_total: total }],
            // The same person approving the same figure again replays the same order.
            idempotency_key: `web-approve:${decision.approvalId}:${total}`,
          },
          actor,
        );
      } catch (error) {
        if (error instanceof ApiError && error.code === "TOTAL_MISMATCH" && error.details.expected_total != null) {
          const now = formatEur(mapMoney(error.details.expected_total, "expected_total"));
          throw new ApiError(
            error.code,
            `The total is now ${now}. Nothing was sent. Check the new total and approve again`,
          );
        }
        throw error;
      }
      return approval(decision.approvalId);
    },
    async reject(approvalId, reason, actor) {
      await post(`${proposalPath(approvalId)}/reject`, { reason, idempotency_key: `web-reject:${approvalId}` }, actor);
      return approval(approvalId);
    },
    async listAddableProducts(orderId, query = "") {
      const [proposal, addable] = await Promise.all([
        get(proposalPath(orderId)),
        get(`${proposalPath(orderId)}/addable`),
      ]);
      const requested = ((proposal as Json).request as Json | undefined)?.requested_date;
      const words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
      return mapAddable(addable, typeof requested === "string" ? requested : "").filter(({ product }) =>
        words.every((word) => product.names.en.toLocaleLowerCase().includes(word)),
      );
    },
    async listOrders() {
      const [placed, list] = await Promise.all([get(`${kitchen}/orders`), proposals()]);
      return mapEach(rows(placed, "orders"), "order", "order_id", (order) =>
        mapOrder(list.find((proposal) => proposal.order_id === order.order_id) ?? null, order),
      );
    },
    async getOrder(id) {
      let proposal: Json;
      try {
        proposal = (await get(proposalPath(id))) as Json;
      } catch (error) {
        if (!(error instanceof ApiError && error.code === "PROPOSAL_NOT_FOUND")) throw error;
        // Not a proposal id, so a placed order: its basket is on the proposal that placed it.
        const [placed, list] = await Promise.all([get(`${kitchen}/orders/${encodeURIComponent(id)}`), proposals()]);
        return mapOrder(list.find((row) => row.order_id === id) ?? null, placed as Json);
      }
      const orderId = proposal.order_id;
      return mapOrder(
        proposal,
        typeof orderId === "string" ? ((await get(`${kitchen}/orders/${encodeURIComponent(orderId)}`)) as Json) : null,
      );
    },
    async listAudit(filter) {
      return mapAudit(await auditEvents(), filter?.orderId);
    },
    async getForecastAccuracy() {
      const w = forecastWindow(new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Helsinki" }));
      const [accuracy, forecast] = await Promise.all([
        get(`${kitchen}/forecast-accuracy?from=${w.pastFrom}&to=${w.pastTo}`),
        get(`${kitchen}/forecast?from=${w.aheadFrom}&to=${w.aheadTo}`),
      ]);
      return mapForecastAccuracy(accuracy, forecast);
    },
    async submitChefRequest(request) {
      const ask = { text: request.text.trim(), requested_date: request.deliveryDate };
      const identity = JSON.stringify(ask);
      // getRandomValues, not randomUUID: it also works on a plain-HTTP address.
      const key =
        requestKeys.get(identity) ??
        Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, "0")).join("");
      requestKeys.set(identity, key);
      const receipt = (await post(`${kitchen}/proposals`, { ...ask, idempotency_key: key })) as Json;
      // The Buyer answers with a short receipt; the stored proposal has the full basket.
      const proposal = (await get(proposalPath(String(receipt.proposal_id)))) as Json;
      // shortcut: the gateway's substitute baskets (several lines each) do not fit the one-product
      // SubstituteOption; pages/live-buyer.tsx shows them. Map them when the demo page needs them.
      return {
        order: mapOrder(proposal, null),
        substitutes: [],
        approval: proposal.approval_id == null ? null : mapApproval(proposal),
      };
    },
  } satisfies Partial<Api>;

  return {
    ...createMockApi(),
    ...real,
    // Never the mock for what acts on real input: it would change a sample order, not the real
    // proposal, or answer a lookup of the person's own kitchen with sample data.
    chooseOption: undefined,
    async changeProposal() {
      throw new ApiError("NOT_SERVED", "The gateway cannot change a proposal yet. Reject it and ask the Buyer again");
    },
    async lookupKitchenBrand() {
      throw new ApiError("NOT_SERVED", "The gateway does not serve this yet.");
    },
    live: new Set(Object.keys(real) as (keyof Api)[]),
  };
}
