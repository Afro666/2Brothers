import { createOnboardingHttp } from "@/api/http-onboarding";
import { createPlanningHttp, SUPPLIER_ID } from "@/api/http-planning";
import { createTrustHttp } from "@/api/http-trust";
import {
  type Json,
  mapAddable,
  mapApproval,
  mapAudit,
  mapOrder,
  mapOrderResolution,
  mapOrderResolutionResult,
  mapPermissions,
  rows,
} from "@/api/gateway-map";
import { mapMoney } from "@/api/map";
import { mapDrift } from "@/api/map-drift";
import { forecastWindow, mapForecastAccuracy } from "@/api/map-forecast";
import { createMockApi } from "@/api/mock";
import type { Api, AuditActor, Session } from "@/api/types";
import { ApiError } from "@/api/types";
import { formatEur } from "@/lib/format";
import type { CurrentSession } from "@/types";

function uuid(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function mapCurrentSession(value: unknown): CurrentSession {
  const row = value as Record<string, unknown>;
  return {
    kind: row.kind === "human" || row.kind === "agent" || row.kind === "token" ? row.kind : null,
    name: typeof row.name === "string" ? row.name : null,
    role: typeof row.role === "string" ? row.role : null,
    kitchenId: typeof row.kitchen_id === "string" ? row.kitchen_id : null,
    canApprove: row.can_approve === true,
    scopes: Array.isArray(row.scopes) ? row.scopes.filter((scope): scope is string => typeof scope === "string") : null,
  };
}

export const SIGNED_OUT_EVENT = "kitchen-buyer:signed-out";

/** One JSON call to the gateway. Gateway errors (`{"error": {code, message}}`) become `ApiError`. */
export async function gatewayRequest(baseUrl: string, path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
      ...init,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("NETWORK", "Could not reach the gateway.");
  }
  const method = (init?.method ?? "GET").toUpperCase();
  const isSessionCheck = method === "GET" && path === "/v1/me";
  const isLogin = method === "POST" && path === "/v1/auth/login";
  if (response.status === 401 && !isSessionCheck && !isLogin) {
    window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
  }
  if (response.status === 429) {
    throw new ApiError("RATE_LIMITED", "Too many requests - wait a minute and try again.");
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
      response.status,
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
 * Hybrid: the order flow (proposals, approve and reject, orders, audit) and the planning
 * screens (api/http-planning.ts) talk to the real gateway; every other method still answers
 * from the mock, and `live` says which is which.
 *
 * No Authorization header is sent: in production the web server adds the gateway's human
 * token (web/Caddyfile).
 */
export function createHttpApi(baseUrl: string): Api {
  let currentSession: Session | null = null;
  const kitchen = `/v1/kitchens/${encodeURIComponent(import.meta.env.VITE_GATEWAY_KITCHEN_ID || "demo-kitchen")}`;
  const proposalPath = (id: string) => `${kitchen}/proposals/${encodeURIComponent(id)}`;
  const get = (path: string) => gatewayRequest(baseUrl, path);
  // X-User names the acting role only while there is no signed-in account; with an account,
  // the gateway takes the person from the session cookie.
  const post = (path: string, body: Json, actor?: AuditActor | string) =>
    gatewayRequest(baseUrl, path, {
      method: "POST",
      headers: actor && !currentSession?.email ? { "X-User": actor } : undefined,
      body: JSON.stringify(body),
    });
  // `GET /v1/me` has `kind` and `can_approve` but no email (a person's email is in `name`);
  // `POST /v1/auth/login` has the email but no `kind` or `can_approve`, and only people sign in.
  const toSession = (body: Json): Session => {
    const role = body.role === "approver" || body.role === "chef" || body.role === "viewer" ? body.role : null;
    const name = typeof body.name === "string" ? body.name : "";
    const fromLogin = body.kind === undefined;
    const human = fromLogin || body.kind === "human";
    const email = typeof body.email === "string" ? body.email : human && name.includes("@") ? name : null;
    return {
      name,
      email,
      role,
      canApprove: fromLogin ? role === "approver" : body.can_approve === true && body.kind === "human",
    };
  };
  // The gateway lists at most its 100 newest proposals.
  const proposals = async () => rows(await get(`${kitchen}/proposals`), "proposals");
  const auditEvents = async () => rows(await get(`${kitchen}/audit`), "events");
  const approval = async (id: string) => {
    const [proposal, events] = await Promise.all([get(proposalPath(id)), auditEvents()]);
    return mapApproval(proposal as Json, events);
  };
  // One key per ask, kept after a failure: a new key could create a second proposal.
  const requestKeys = new Map<string, string>();
  const resolutionKeys = new Map<string, string>();
  const reopenedApprovals = new Map<string, string>();

  const real = {
    async getSession() {
      try {
        currentSession = toSession((await get("/v1/me")) as Json);
        return currentSession;
      } catch (error) {
        if (error instanceof ApiError && (error.code === "UNAUTHENTICATED" || error.status === 401)) {
          currentSession = null;
          return null;
        }
        throw error;
      }
    },
    async signIn(email, password) {
      currentSession = toSession((await post("/v1/auth/login", { email, password })) as Json);
      return currentSession;
    },
    async signOut() {
      try {
        await post("/v1/auth/logout", {});
      } catch {
      } finally {
        currentSession = null;
      }
    },
    async changePassword(current, next) {
      await post("/v1/auth/change-password", { current_password: current, new_password: next });
    },
    ...createPlanningHttp((path, init) => gatewayRequest(baseUrl, path, init), kitchen),
    ...createOnboardingHttp((path, init) => gatewayRequest(baseUrl, path, init)),
    ...createTrustHttp((path, init) => gatewayRequest(baseUrl, path, init), kitchen),
    async listApprovals() {
      const [list, events] = await Promise.all([proposals(), auditEvents()]);
      return mapEach(list, "proposal", "proposal_id", (proposal) => mapApproval(proposal, events));
    },
    getApproval: approval,
    async chooseOption(approvalId, optionId, actor) {
      // One key per choice: kept only while that choice has not been answered, so a retry after
      // a network failure repeats it, and choosing the same option again later is a new choice.
      const identity = `${approvalId}:${optionId}`;
      const key = requestKeys.get(identity) ?? `web-choose-option:${uuid()}`;
      requestKeys.set(identity, key);
      const answered = await post(
        `${proposalPath(approvalId)}/choose-option`,
        { offer_id: optionId, idempotency_key: key },
        actor,
      );
      requestKeys.delete(identity);
      return mapApproval(answered as Json);
    },
    async approve(decision, actor) {
      const total = decision.expectedTotalInclVat.toFixed(2);
      const baseKey = `web-approve:${decision.approvalId}:${total}`;
      const reopened = reopenedApprovals.get(decision.approvalId);
      const approvalKey = reopened ? `${baseKey}:reopened:${reopened}` : baseKey;
      try {
        await post(
          `${proposalPath(decision.approvalId)}/approve`,
          {
            // docs/contract.md: the approve body is `{expected_total, idempotency_key}`.
            expected_total: total,
            // The same person approving the same figure again replays the same order.
            idempotency_key: approvalKey,
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
    async getCurrentSession() {
      return mapCurrentSession(await get("/v1/me"));
    },
    async getOrderResolution(orderId) {
      return mapOrderResolution(await get(`${kitchen}/orders/${encodeURIComponent(orderId)}/resolution`));
    },
    async resolveOrder(orderId, resolution, actor) {
      const reference = resolution.resolution === "placed" ? resolution.supplierOrderRef.trim() : null;
      if (reference !== null && (!reference || reference.length > 200)) {
        throw new ApiError("INVALID_REQUEST", "The supplier order reference must be 1 to 200 characters.");
      }
      const body: Json =
        resolution.resolution === "placed"
          ? { resolution: "placed", supplier_order_ref: resolution.supplierOrderRef.trim() }
          : { resolution: "not_sent", note: resolution.note?.trim() ?? "" };
      const identity = `${orderId}:${JSON.stringify(body)}`;
      const idempotencyKey = resolutionKeys.get(identity) ?? uuid();
      resolutionKeys.set(identity, idempotencyKey);
      const result = await post(
        `${kitchen}/orders/${encodeURIComponent(orderId)}/resolve`,
        { ...body, idempotency_key: idempotencyKey },
        actor,
      );
      const mapped = mapOrderResolutionResult(result);
      if (mapped.outcome === "NOT_SENT" && mapped.proposalId) {
        reopenedApprovals.set(mapped.proposalId, idempotencyKey);
      }
      return mapped;
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
    async getPermissions() {
      return mapPermissions(await get(`${kitchen}/permissions`));
    },
    async getDrift() {
      return mapDrift(await get(`${kitchen}/drift`));
    },
    async getSupplierDrift() {
      return mapDrift(await get(`/v1/suppliers/${encodeURIComponent(SUPPLIER_ID)}/demand/drift`));
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
    // proposal.
    async changeProposal() {
      throw new ApiError("NOT_SERVED", "The gateway cannot change a proposal yet. Reject it and ask the Buyer again");
    },
    live: new Set(Object.keys(real) as (keyof Api)[]),
  };
}
