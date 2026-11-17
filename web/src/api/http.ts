import { createBrandLogosHttp } from "@/api/http-brand-logos";
import { createCatalogHttp } from "@/api/http-catalog";
import { createProductPageHttp } from "@/api/http-product-page";
import { createNutritionHttp } from "@/api/http-nutrition";
import { createOffersHttp } from "@/api/http-offers";
import { createOnboardingHttp } from "@/api/http-onboarding";
import { createPlanningHttp, SUPPLIER_ID } from "@/api/http-planning";
import { createBuyingNoteHttp } from "@/api/http-buying-note";
import { createShelfHttp } from "@/api/http-shelf";
import { createMenuPhotoHttp } from "@/api/http-menu-photo";
import { createPriceListHttp } from "@/api/http-price-list";
import { createDeliveryNoteHttp } from "@/api/http-delivery-note";
import { createLabelPhotoHttp } from "@/api/http-label-photo";
import { createTrustHttp } from "@/api/http-trust";
import { createUsageHttp } from "@/api/http-usage";
import { createAtlasHttp } from "@/api/http-atlas";
import { createTokensHttp } from "@/api/http-tokens";
import { createApprovalTokensHttp } from "@/api/http-approval-tokens";
import { createDeveloperHttp } from "@/api/http-developer";
import { createEventsHttp } from "@/api/http-events";
import { createExplanationHttp } from "@/api/http-explanation";
import { createLearnedHttp } from "@/api/http-learned";
import {
  type Json,
  mapAddable,
  mapApproval,
  mapAudit,
  mapOrder,
  mapOrderResolution,
  mapOrderResolutionResult,
  mapPermissions,
  mapRecalls,
  rows,
} from "@/api/gateway-map";
import { mapMoney } from "@/api/map";
import { mapDrift } from "@/api/map-drift";
import { forecastWindow, mapForecastAccuracy } from "@/api/map-forecast";
import { createMockApi } from "@/api/mock";
import type { Api, AuditActor, Session } from "@/api/types";
import { ApiError } from "@/api/types";
import { formatEur } from "@/lib/format";
import { dropKeptAnswers, readCacheRevision } from "@/lib/use-async";
import { randomBytes, randomHex, toHex } from "@/lib/random-id";

function uuid(): string {
  const bytes = randomBytes(16);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = toHex(bytes);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export const SIGNED_OUT_EVENT = "kitchen-buyer:signed-out";
/** Sent after a successful sign-in, so the event stream that a 401/403 stopped opens again. */
export const SIGNED_IN_EVENT = "kitchen-buyer:signed-in";

/** Run before and after every write, so a read that starts after it never joins a request from before
 * it, nor one that started while the write was in flight.
 * shortcut: an entry is never removed; the app makes one api per page. Remove on dispose if that changes. */
const beforeWrite = new Set<() => void>([dropKeptAnswers]);

/** The 429 codes that mean "busy", not "rate limited": each panel shows its own text for them. */
const BUSY_429 = new Map<unknown, string>([
  ["PRICE_LIST_BUSY", "Another price list is being read."],
  ["MENU_PHOTO_BUSY", "Another menu photo is being read."],
  ["LABEL_PHOTO_BUSY", "Another label is being read."],
  ["SUPPLIER_BUSY", "The supplier is busy - try again shortly."],
]);

/** One JSON call to the gateway. Gateway errors (`{"error": {code, message}}`) become `ApiError`. */
/** Dispatch and coalescing use exactly the same headers, including Headers/tuple inputs. */
function requestHeaders(input?: HeadersInit): Record<string, string> {
  const normalized = new Headers(input);
  const entries = input instanceof Headers || Array.isArray(input) ? Object.fromEntries(normalized.entries()) : input;
  return { ...(!normalized.has("Content-Type") ? { "Content-Type": "application/json" } : {}), ...entries };
}
const defaultReadScope = {};
const readScopes = new WeakMap<object, { revision: number; pending: Map<string, Promise<unknown>> }>();
export async function gatewayRequest(baseUrl: string, path: string, init?: RequestInit, scope: object = defaultReadScope): Promise<unknown> {
  const method = (init?.method ?? "GET").toUpperCase();
  // This one POST tool is a lookup, not a mutation. Never generalize this to approval/order POSTs.
  const search = method === "POST" && path === "/tools/search_products";
  if (method === "GET" || search) {
    const revision = readCacheRevision();
    let reads = readScopes.get(scope);
    if (!reads || reads.revision !== revision) {
      reads = { revision, pending: new Map() };
      readScopes.set(scope, reads);
    }
    const pendingReads = reads.pending;
    // Aborting one subscriber must not cancel another's request. Custom RequestInit options bypass sharing.
    if (init && Object.keys(init).some((key) => key !== "method" && key !== "headers" && !(search && key === "body"))) return send(baseUrl, path, init);
    const headers = [...new Headers(requestHeaders(init?.headers)).entries()].sort(([a], [b]) => a.localeCompare(b));
    const key = JSON.stringify([baseUrl, path, method, search ? init?.body : null, headers]);
    const existing = pendingReads.get(key);
    if (existing) return existing.then((value) => structuredClone(value));
    if (pendingReads.size >= 64) return send(baseUrl, path, init);
    const request = send(baseUrl, path, init);
    pendingReads.set(key, request);
    const forget = () => { if (pendingReads.get(key) === request) pendingReads.delete(key); };
    void request.then(forget, forget);
    // Share the network work, not mutable JSON owned by independent callers.
    return request.then((value) => structuredClone(value));
  }
  beforeWrite.forEach((drop) => drop());
  try {
    return await send(baseUrl, path, init);
  } finally {
    beforeWrite.forEach((drop) => drop());
  }
}

async function send(baseUrl: string, path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
      ...init,
      credentials: "same-origin",
      headers: requestHeaders(init?.headers),
    });
  } catch {
    throw new ApiError("NETWORK", "Could not reach the gateway.");
  }
  const method = (init?.method ?? "GET").toUpperCase();
  const isSessionCheck = method === "GET" && path === "/v1/me";
  const isLogin = method === "POST" && path === "/v1/auth/login";
  if (response.status === 401 && !isSessionCheck && !isLogin) {
    dropKeptAnswers();
    window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
  }
  if (response.status === 429) {
    // The gateway locks an account for five minutes after five wrong passwords: "wait a minute" would be wrong.
    const error = (await response.json().catch(() => null))?.error;
    const code = error?.code;
    if (isLogin && code === "ACCOUNT_LOCKED") {
      throw new ApiError("ACCOUNT_LOCKED", "Too many wrong passwords. Try again in five minutes.", {}, 429);
    }
    // One read per kitchen at a time (#1174, #1451), or the supplier asks us to wait `retry_after`:
    // "wait a minute" would be wrong too, so the busy code and its details stay for the panel.
    const busy = BUSY_429.get(code);
    if (busy) throw new ApiError(code, busy, error && typeof error === "object" ? error : {}, 429);
    throw new ApiError(
      "RATE_LIMITED",
      "Too many requests - wait a minute and try again.",
      error && typeof error === "object" ? error : {},
      429,
    );
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
 * Hybrid: the order flow (proposals, approve and reject, orders, audit), the catalog search
 * (api/http-catalog.ts) and the planning screens (api/http-planning.ts) talk to the real
 * gateway; every other method still answers from the mock, and `live` says which is which.
 *
 * No Authorization header is sent: in production the web server adds the gateway's human
 * token (web/Caddyfile).
 */
/** The gateway sends at most this many newest audit steps from `GET /audit`. */
export const AUDIT_LIMIT = 1000;

export function createHttpApi(baseUrl: string): Api {
  let currentSession: Session | null = null;
  let sessionKnown = false;
  // Bumped whenever the session is set or cleared: an older `/v1/me` answer must not
  // overwrite a newer sign-in (or sign-out) that finished while it was in flight.
  let authGeneration = 0;
  const setSession = (next: Session | null) => {
    currentSession = next;
    sessionKnown = true;
    authGeneration += 1;
  };
  const requestScope = {};
  const request = (path: string, init?: RequestInit) => gatewayRequest(baseUrl, path, init, requestScope);
  const mock = createMockApi();
  const kitchen = `/v1/kitchens/${encodeURIComponent(import.meta.env.VITE_GATEWAY_KITCHEN_ID || "demo-kitchen")}`;
  const proposalPath = (id: string) => `${kitchen}/proposals/${encodeURIComponent(id)}`;
  const get = (path: string) => request(path);
  // X-User names the acting role only while there is no signed-in account; with an account,
  // the gateway takes the person from the session cookie.
  const post = (path: string, body: Json, actor?: AuditActor | string) =>
    request(path, {
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
      kind: human ? "human" : body.kind === "agent" || body.kind === "token" ? body.kind : null,
      name,
      email,
      role,
      canApprove: fromLogin ? role === "approver" : body.can_approve === true && body.kind === "human",
    };
  };
  // One request in flight: the audit log is large and three places ask for it at once. An answer
  // is kept only for `keepMs` after it arrived (0: not at all): a call made after that, after a
  // write or after a live event asks again.
  const shared = <T,>(load: () => Promise<T>, keepMs = 0) => {
    let running: Promise<T> | null = null;
    return {
      get: () => {
        if (running) return running;
        const forget = () => {
          if (running === mine) running = null;
        };
        const mine: Promise<T> = load().then(
          (value) => {
            if (keepMs > 0) setTimeout(forget, keepMs);
            else forget();
            return value;
          },
          (error: unknown) => {
            forget();
            throw error;
          },
        );
        return (running = mine);
      },
      drop: () => {
        running = null;
      },
    };
  };
  // The gateway returns at most 100 proposals per page. The badge needs only
  // the first page's kitchen-wide count; history readers follow older pages.
  // Kept 3 s: one page load asks for the list three times in a row (the inbox, the waiting count,
  // each approved card's order) and the gateway needs about a second for it.
  const firstProposalPage = shared(async () => await get(`${kitchen}/proposals`) as Json, 3000);
  const proposalsRead = shared(async () => {
    let page = await firstProposalPage.get();
    const result = [...rows(page, "proposals")];
    const seen = new Set<string>();
    while (typeof page.next_cursor === "string") {
      if (seen.size >= 99) throw new ApiError("INVALID_RESPONSE", "The approval history is too large to load at once.");
      if (seen.has(page.next_cursor)) throw new ApiError("INVALID_RESPONSE", "The gateway repeated a proposal page.");
      seen.add(page.next_cursor);
      page = await get(`${kitchen}/proposals?cursor=${encodeURIComponent(page.next_cursor)}`) as Json;
      result.push(...rows(page, "proposals"));
    }
    return result;
  }, 3000);
  const auditRead = shared(async () => rows(await get(`${kitchen}/audit`), "events"));
  const proposals = () => proposalsRead.get();
  const auditEvents = () => auditRead.get();
  const dropReads = () => {
    // Invalidate both layers: the 3 s proposal answer and any pre-event transport read.
    dropKeptAnswers();
    proposalsRead.drop();
    firstProposalPage.drop();
    auditRead.drop();
  };
  beforeWrite.add(dropReads);
  const events = createEventsHttp(baseUrl, kitchen, () => currentSession);
  const approval = async (id: string) => {
    const [proposal, events] = await Promise.all([get(proposalPath(id)), auditEvents().catch(() => [])]);
    return mapApproval(proposal as Json, events);
  };
  // One key per ask, kept after a failure: a new key could create a second proposal.
  const requestKeys = new Map<string, string>();
  const resolutionKeys = new Map<string, string>();

  const real = {
    async getSession() {
      const startedAt = authGeneration;
      try {
        const next = toSession((await get("/v1/me")) as Json);
        if (startedAt !== authGeneration) return currentSession;
        if (sessionKnown && JSON.stringify(currentSession) !== JSON.stringify(next)) {
          dropKeptAnswers();
          dropReads();
        }
        setSession(next);
        return currentSession;
      } catch (error) {
        if (startedAt !== authGeneration) return currentSession;
        if (error instanceof ApiError && (error.code === "UNAUTHENTICATED" || error.status === 401)) {
          dropKeptAnswers();
          dropReads();
          setSession(null);
          return null;
        }
        throw error;
      }
    },
    async signIn(email, password) {
      const session = toSession((await post("/v1/auth/login", { email, password })) as Json);
      setSession(session);
      window.dispatchEvent(new Event(SIGNED_IN_EVENT));
      return session;
    },
    async signOut() {
      try {
        await post("/v1/auth/logout", {});
      } catch {
      } finally {
        setSession(null);
      }
    },
    async changePassword(current, next) {
      await post("/v1/auth/change-password", { current_password: current, new_password: next });
    },
    ...createPlanningHttp((path, init) => request(path, init), kitchen),
    ...createLearnedHttp((path, init) => request(path, init), kitchen),
    ...createBuyingNoteHttp((path, init) => request(path, init)),
    ...createNutritionHttp((path, init) => request(path, init), kitchen),
    ...createOnboardingHttp((path, init) => request(path, init)),
    ...createBrandLogosHttp((path, init) => request(path, init)),
    ...createShelfHttp((path, init) => request(path, init), kitchen),
    ...createMenuPhotoHttp((path, init) => request(path, init), kitchen),
    ...createPriceListHttp((path, init) => request(path, init), kitchen),
    ...createDeliveryNoteHttp((path, init) => request(path, init), kitchen),
    ...createLabelPhotoHttp((path, init) => request(path, init), kitchen),
    ...createTrustHttp((path, init) => request(path, init), kitchen),
    ...createUsageHttp((path, init) => request(path, init), kitchen),
    ...createAtlasHttp((path, init) => request(path, init), kitchen),
    ...createOffersHttp((path, init) => request(path, init), kitchen),
    ...createTokensHttp((path, init) => request(path, init), kitchen),
    ...createApprovalTokensHttp((path, init) => request(path, init), kitchen),
    ...createDeveloperHttp((path, init) => request(path, init), kitchen),
    ...createCatalogHttp((path, init) => request(path, init), kitchen),
    ...createProductPageHttp((path, init) => request(path, init), kitchen),
    // A live event or a new connection means the lists may have changed since a request began.
    subscribeEvents: (onEvent, onStatus) =>
      events.subscribeEvents!(
        (event) => {
          dropReads();
          onEvent(event);
        },
        (connected) => {
          dropReads();
          onStatus?.(connected);
        },
      ),
    ...createExplanationHttp((path, init) => request(path, init), kitchen),
    async listApprovals() {
      const [list, events] = await Promise.all([proposals(), auditEvents().catch(() => [])]);
      return mapEach(list, "proposal", "proposal_id", (proposal) => mapApproval(proposal, events));
    },
    async countPendingApprovals() {
      const page = await firstProposalPage.get();
      if (typeof page.pending_count === "number" && Number.isSafeInteger(page.pending_count) && page.pending_count >= 0) return page.pending_count;
      const list = await proposals(); // Compatibility with older gateways without count metadata.
      return mapEach(list, "proposal", "proposal_id", (proposal) => mapApproval(proposal)).filter(
        (approval) => approval.status === "PENDING",
      ).length;
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
      const approvalKey = `web-approve:${decision.approvalId}:${total}:${decision.approvalRef ?? "first"}`;
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
        if (error instanceof ApiError && error.code === "BLOCKED_BY_RECALL") {
          throw new ApiError(
            error.code,
            "This order is blocked by a recall and cannot be approved. Reject it and approve the replacement order instead.",
            error.details,
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
    async changeProposal(orderId, change, actor) {
      // docs/contract.md "Changing a proposal": SET_QUANTITY and REMOVE_LINE are one `lines`
      // entry (0 removes), ADD_LINE is one `add` entry. Quantities go as decimal strings.
      const body: Json =
        change.type === "ADD_LINE"
          ? { add: [{ product_id: change.productId, quantity: String(change.quantity) }] }
          : {
              lines: [
                {
                  product_id: change.productId,
                  quantity: change.type === "REMOVE_LINE" ? "0" : String(change.quantity),
                  ...(change.reason ? { reason: change.reason } : {}),
                  ...(change.reason === "OTHER" && change.note ? { note: change.note } : {}),
                },
              ],
            };
      // One key per change, kept only until it is answered: a retry after a network failure
      // repeats it, and making the same change again later is a new change.
      const identity = `change:${orderId}:${JSON.stringify(body)}`;
      const key = requestKeys.get(identity) ?? `web-change:${uuid()}`;
      requestKeys.set(identity, key);
      let answered: Json;
      try {
        answered = (await post(`${proposalPath(orderId)}/change`, { ...body, idempotency_key: key }, actor)) as Json;
      } catch (error) {
        // A definite refusal means nothing was applied: the next try is a new change.
        const status = error instanceof ApiError ? error.status : undefined;
        if (status !== undefined && status >= 400 && status < 500 && status !== 408 && status !== 429) {
          requestKeys.delete(identity);
        }
        throw error;
      }
      // The change is made: an unreadable audit log only loses who asked, never the new total.
      const events = await auditEvents().catch(() => []);
      const result = { order: mapOrder(answered, null), approval: mapApproval(answered, events) };
      // Keep the key until the answer is mapped: a mapper failure must repeat the same key.
      requestKeys.delete(identity);
      return result;
    },
    async listOrders() {
      const [placed, list] = await Promise.all([get(`${kitchen}/orders`), proposals()]);
      return mapEach(rows(placed, "orders"), "order", "order_id", (order) =>
        mapOrder(list.find((proposal) => proposal.order_id === order.order_id) ?? null, order),
      );
    },
    async getOrder(id) {
      // The id is a proposal's or a placed order's. The proposals list says which, so the page
      // does not ask the proposal route for an order id and get a 404 on every order page.
      const list = await proposals();
      const placedBy = list.find((row) => row.order_id === id);
      if (placedBy) {
        // A placed order: its basket is on the proposal that placed it.
        return mapOrder(placedBy, (await get(`${kitchen}/orders/${encodeURIComponent(id)}`)) as Json);
      }
      if (!list.some((row) => row.proposal_id === id)) {
        // On the list neither way: an order whose proposal is gone or never existed (the demo
        // seed's, #1726) is asked as an order first; the proposal route only if no order has the id.
        try {
          return mapOrder(null, (await get(`${kitchen}/orders/${encodeURIComponent(id)}`)) as Json);
        } catch (error) {
          if (!(error instanceof ApiError && error.code === "ORDER_NOT_FOUND")) throw error;
        }
      }
      // #1858: both routes answer the same `_proposal_out` (gateway/service.py), so the list row is
      // the proposal; the single route is asked only when the row is not on the list (100 newest).
      const proposal = (list.find((row) => row.proposal_id === id) ?? (await get(proposalPath(id)))) as Json;
      const orderId = proposal.order_id;
      return mapOrder(
        proposal,
        typeof orderId === "string" ? ((await get(`${kitchen}/orders/${encodeURIComponent(orderId)}`)) as Json) : null,
      );
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
      return mapOrderResolutionResult(result);
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
    async listRecalls() {
      return mapRecalls(await get(`${kitchen}/recalls`));
    },
    async checkRecalls(actor) {
      const key = Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) =>
        value.toString(16).padStart(2, "0"),
      ).join("");
      return mapRecalls(await post(`${kitchen}/recalls/check`, { idempotency_key: `recall-check-${key}` }, actor));
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
      const key = requestKeys.get(identity) ?? randomHex(16);
      requestKeys.set(identity, key);
      const receipt = (await post(`${kitchen}/proposals`, { ...ask, idempotency_key: key })) as Json;
      // The Buyer answers with a short receipt; the stored proposal has the full basket.
      const proposal = (await get(proposalPath(String(receipt.proposal_id)))) as Json;
      // shortcut: the gateway's substitute baskets (several lines each) do not fit the one-product
      // SubstituteOption; pages/live-buyer.tsx shows them. Map them when the demo page needs them.
      const result = {
        order: mapOrder(proposal, null),
        substitutes: [],
        approval: proposal.approval_id == null ? null : mapApproval(proposal),
      };
      // A valid answer: the same text sent again is a new request (#1818). A failure above keeps the key for the retry.
      requestKeys.delete(identity);
      return result;
    },
  } satisfies Partial<Api>;

  return {
    ...mock,
    ...real,
    live: new Set(Object.keys(real) as (keyof Api)[]),
  };
}
