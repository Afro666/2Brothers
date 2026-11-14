import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpApi, gatewayRequest, SIGNED_OUT_EVENT } from "@/api/http";
import { ApiError } from "@/api/types";
import { auditEvents, placedOrder, proposal } from "@/test/gateway-fixtures";
import { renderApp } from "@/test/render";

const K = "/api/v1/kitchens/demo-kitchen";
type Handler = (body: Record<string, unknown>) => unknown;

function error(status: number, code: string, extra: object = {}) {
  return new Response(JSON.stringify({ error: { code, message: code, ...extra } }), { status });
}

/** A fake gateway: `"POST /path"` -> the JSON it answers. Returns the calls it received. */
function gateway(routes: Record<string, Handler>) {
  const calls: { route: string; headers: Record<string, string>; body: Record<string, unknown> }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    const route = `${init.method ?? "GET"} ${url}`;
    const body = init.body ? JSON.parse(init.body as string) : {};
    calls.push({ route, headers: init.headers as Record<string, string>, body });
    // A signed-in approver unless the test says otherwise: every screen asks who is signed in first.
    const fallback =
      route === "GET /api/v1/me"
        ? { kind: "human", name: "Demo approver", role: "approver", can_approve: true }
        : null;
    const answer = routes[route] ? routes[route](body) : (fallback ?? error(404, "NO_ROUTE"));
    return answer instanceof Response ? answer : new Response(JSON.stringify(answer));
  });
  return calls;
}

const inbox = (row: object = proposal) => ({
  [`GET ${K}/proposals`]: () => ({ proposals: [row] }),
  [`GET ${K}/proposals/prop-1`]: () => row,
  [`GET ${K}/audit`]: () => ({ events: auditEvents }),
});

const substituteOption = (offerId: string, overrides: Record<string, unknown> = {}) => ({
  tier: "good",
  source: "original",
  offer_id: offerId,
  expected_total: "91.20",
  currency: "EUR",
  lines: proposal.lines,
  why: "Re-simulated basket.",
  requires_chef_approval: true,
  stock_confirmed: true,
  allergen_data_known: true,
  ...overrides,
});

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("createHttpApi", () => {
  it("says which methods are real and answers the rest from the mock, without a request", async () => {
    const calls = gateway({});
    const api = createHttpApi("/api");
    expect([...api.live!].sort()).toEqual(
      [
        "approve",
        "changePassword",
        "changeProposal",
        "chooseOption",
        "getApproval",
        "getAtlasFacts",
        "getForecastAccuracy",
        "getOrder",
        "getOrderResolution",
        "getPermissions",
        "getProposalExplanation",
        "listApiTokens",
        "createApiToken",
        "revokeApiToken",
        "listApprovalTokens",
        "createApprovalToken",
        "revokeApprovalToken",
        "createWebhook",
        "testWebhook",
        "deleteWebhook",
        "listWebhooks",
        "getGatewayHealth",
        "getSession",
        "listAddableProducts",
        "listApprovals",
        "countPendingApprovals",
        "listAudit",
        "listBrandLogos",
        "subscribeEvents",
        "listOrders",
        "listRecalls",
        "checkRecalls",
        "reject",
        "resolveOrder",
        "signIn",
        "signOut",
        "submitChefRequest",
        // The planning screens (api/http-planning.ts).
        "listSuppliers",
        "saveSupplier",
        "deleteSupplier",
        "listOwnProducts",
        "saveOwnProduct",
        "deleteOwnProduct",
        "listRecipes",
        "saveRecipe",
        "deleteRecipe",
        "getMenuPlan",
        "saveMenuPlan",
        "getStock",
        "submitStockCount",
        "readShelfPhoto",
        // Plan from a menu photo (api/http-menu-photo.ts).
        "readMenuPhoto",
        "readPriceListPhoto",
        "readDeliveryNote",
        "readLabelPhoto",
        "getDemand",
        "proposeOrderForPlan",
        "getSharing",
        "setSharing",
        "getSupplierDemand",
        "getKitchenSettings",
        "saveKitchenSettings",
        "getAutoApproveLearning",
        "getBuyingNote",
        // Standing-order drift (store/drift.py behind the gateway).
        "getDrift",
        "getSupplierDrift",
        // Onboarding (api/http-onboarding.ts).
        "lookupKitchenBrand",
        // Catalog search and products by code (api/http-catalog.ts).
        "searchProducts",
        "getProductPage",
        "getProducts",
        // The Trust page (api/http-trust.ts).
        "listAuditChain",
        "verifyAuditChain",
        "tamperAuditRow",
        "restoreAuditRow",
        // The model usage card on the About page (api/http-usage.ts).
        "getModelUsage",
        // Supplier offers (api/http-offers.ts).
        "listSupplierOffers",
        "acceptSupplierOffer",
        "declineSupplierOffer",
        // Nutrition from the label data and the kitchen's own words (api/http-nutrition.ts).
        "getRecipeNutrition",
        "getRecipesNutrition",
        "getNutrition",
        "getKitchenWords",
        "linkWord",
        "forgetWord",
      ].sort(),
    );
    expect((await api.getMandate()).restaurant).toBeTruthy();
    expect((await api.listTeamMembers()).length).toBeGreaterThan(0);
    expect(calls).toEqual([]);
    expect(api.chooseOption).toBeTypeOf("function");
  });

  it("chooses an option and maps the answered proposal, including its refreshed offer ids", async () => {
    const lines = proposal.lines.map((line) => ({ ...line, product_name: "Oat drink 1 L" }));
    const answered = {
      ...proposal,
      lines,
      offer_id: "offer-refreshed",
      total_ex_vat: "131.07",
      expected_total: "148.76",
      substitute_options: [
        substituteOption("offer-requested"),
        substituteOption("offer-refreshed", {
          tier: "better",
          source: "confirmed",
          lines,
          recommended: true,
          held: { quantity: "949", unit: "L" },
        }),
      ],
    };
    const calls = gateway({ [`POST ${K}/proposals/prop-1/choose-option`]: () => answered });

    const result = await createHttpApi("/api").chooseOption!("prop-1", "offer-requested", "chef");

    expect(calls).toEqual([
      expect.objectContaining({
        route: `POST ${K}/proposals/prop-1/choose-option`,
        headers: expect.objectContaining({ "X-User": "chef" }),
        body: { offer_id: "offer-requested", idempotency_key: expect.stringMatching(/^web-choose-option:/) },
      }),
    ]);
    expect(result).toMatchObject({ totalExVat: 131.07, totalInclVat: 148.76 });
    expect(result.options).toEqual([
      expect.objectContaining({ id: "offer-requested", chosen: false }),
      expect.objectContaining({
        id: "offer-refreshed",
        source: "confirmed",
        recommended: true,
        held: { quantity: 949, unit: "L" },
        chosen: true,
        lines: [expect.objectContaining({ productName: "Oat drink 1 L" })],
      }),
    ]);
  });

  it("repeats the key when a failed choice is retried, and uses a new one for every answered choice", async () => {
    const answered = {
      ...proposal,
      offer_id: "offer-refreshed",
      substitute_options: [substituteOption("offer-refreshed")],
    };
    let down = true;
    const calls = gateway({
      [`POST ${K}/proposals/prop-1/choose-option`]: () => (down ? error(503, "UNAVAILABLE") : answered),
    });
    const api = createHttpApi("/api");

    await expect(api.chooseOption!("prop-1", "offer-a", "human")).rejects.toMatchObject({ code: "UNAVAILABLE" });
    down = false;
    await api.chooseOption!("prop-1", "offer-a", "human");
    await api.chooseOption!("prop-1", "offer-b", "human");
    await api.chooseOption!("prop-1", "offer-a", "human");

    const keys = calls.map((call) => call.body.idempotency_key);
    expect(keys[1]).toBe(keys[0]);
    expect(new Set(keys.slice(1)).size).toBe(3);
  });

  it.each([
    [409, "STOCK_UNKNOWN"],
    [409, "CLOSING_PASSED"],
    [409, "OPTION_UNAVAILABLE"],
    [409, "NOT_PENDING"],
    [403, "HUMAN_SESSION_REQUIRED"],
  ])("passes %i %s back to the option card", async (status, code) => {
    gateway({ [`POST ${K}/proposals/prop-1/choose-option`]: () => error(status, code) });
    await expect(createHttpApi("/api").chooseOption!("prop-1", "offer-a", "human")).rejects.toMatchObject({
      code,
    });
  });

  it.each([
    [
      { type: "SET_QUANTITY", productId: "900001", quantity: 30 },
      { lines: [{ product_id: "900001", quantity: "30" }] },
    ],
    [
      { type: "SET_QUANTITY", productId: "900001", quantity: 20, reason: "TOO_MUCH" },
      { lines: [{ product_id: "900001", quantity: "20", reason: "TOO_MUCH" }] },
    ],
    [
      { type: "REMOVE_LINE", productId: "900001", reason: "OTHER", note: "Event cancelled" },
      { lines: [{ product_id: "900001", quantity: "0", reason: "OTHER", note: "Event cancelled" }] },
    ],
    [
      { type: "SET_QUANTITY", productId: "900001", quantity: 20, reason: "TOO_MUCH", note: "Not sent" },
      { lines: [{ product_id: "900001", quantity: "20", reason: "TOO_MUCH" }] },
    ],
    [
      { type: "REMOVE_LINE", productId: "900001", reason: "OTHER", note: "" },
      { lines: [{ product_id: "900001", quantity: "0", reason: "OTHER" }] },
    ],
    [{ type: "REMOVE_LINE", productId: "900001" }, { lines: [{ product_id: "900001", quantity: "0" }] }],
    [
      { type: "ADD_LINE", productId: "900002", quantity: 8 },
      { add: [{ product_id: "900002", quantity: "8" }] },
    ],
  ] as const)("changes a proposal on the gateway: %o is sent as %o", async (change, sent) => {
    const changed = {
      ...proposal,
      offer_id: "offer-2",
      total_ex_vat: "60.00",
      expected_total: "68.40",
      lines: [{ ...proposal.lines[0], quantity: "30", total: "60.00", why: "Quantity set by chef." }],
    };
    const calls = gateway({
      [`POST ${K}/proposals/prop-1/change`]: () => changed,
      [`GET ${K}/audit`]: () => ({ events: auditEvents }),
    });

    const result = await createHttpApi("/api").changeProposal("prop-1", change, "chef");

    const post = calls.find((call) => call.route === `POST ${K}/proposals/prop-1/change`);
    expect(post?.body).toEqual({ ...sent, idempotency_key: expect.stringMatching(/^web-change:/) });
    expect(post?.headers).toMatchObject({ "X-User": "chef" });
    expect(result.order).toMatchObject({ id: "prop-1", totalExVat: 60, totalInclVat: 68.4 });
    expect(result.order.lines[0]).toMatchObject({ quantity: 30, why: "Quantity set by chef." });
    expect(result.approval).toMatchObject({ id: "prop-1", status: "PENDING", totalInclVat: 68.4 });
  });

  it("repeats the change key when a failed change is retried, and uses a new one once answered", async () => {
    let down = true;
    const calls = gateway({
      [`POST ${K}/proposals/prop-1/change`]: () => (down ? error(503, "SUPPLIER_BUSY") : proposal),
      [`GET ${K}/audit`]: () => ({ events: auditEvents }),
    });
    const api = createHttpApi("/api");
    const change = { type: "SET_QUANTITY", productId: "900001", quantity: 30 } as const;

    await expect(api.changeProposal("prop-1", change, "human")).rejects.toMatchObject({ code: "SUPPLIER_BUSY" });
    down = false;
    await api.changeProposal("prop-1", change, "human");
    await api.changeProposal("prop-1", change, "human");

    const keys = calls.filter((call) => call.route.endsWith("/change")).map((call) => call.body.idempotency_key);
    expect(keys).toHaveLength(3);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[1]);
  });

  it("keeps the changed proposal when the audit log cannot be read after the change", async () => {
    gateway({
      [`POST ${K}/proposals/prop-1/change`]: () => proposal,
      [`GET ${K}/audit`]: () => error(503, "UNAVAILABLE"),
    });
    const result = await createHttpApi("/api").changeProposal(
      "prop-1",
      { type: "REMOVE_LINE", productId: "900001" },
      "human",
    );
    expect(result.approval).toMatchObject({ id: "prop-1", totalInclVat: 91.2 });
  });

  it.each([
    [409, "NOT_PENDING"],
    [409, "NOT_ADDABLE"],
    [409, "CLOSING_PASSED"],
    [409, "LINE_UNAVAILABLE"],
    [404, "LINE_NOT_FOUND"],
    [422, "EMPTY_PROPOSAL"],
    [503, "SUPPLIER_BUSY"],
  ])("passes a refused change (%i %s) back to the card", async (status, code) => {
    gateway({ [`POST ${K}/proposals/prop-1/change`]: () => error(status, code) });
    await expect(
      createHttpApi("/api").changeProposal("prop-1", { type: "REMOVE_LINE", productId: "900001" }, "human"),
    ).rejects.toMatchObject({ code, status });
  });

  // #1286: SUPPLIER_BUSY sends `retry_after_s`, as LOOKUP_RATE_LIMITED does. A gateway from before
  // #1286 sends `retry_after`; the web reads both for one release.
  it.each([
    [{ retry_after_s: 27 }, 27],
    [{ retry_after: 12 }, 12],
    [{ retry_after_s: 27, retry_after: 12 }, 27],
    [{}, undefined],
    [{ retry_after_s: "soon" }, undefined],
  ])("reads the wait of a busy answer (%o)", async (extra, seconds) => {
    gateway({ [`POST ${K}/proposals/prop-1/change`]: () => error(503, "SUPPLIER_BUSY", extra) });
    const refused = await createHttpApi("/api")
      .changeProposal("prop-1", { type: "REMOVE_LINE", productId: "900001" }, "human")
      .catch((reason: unknown) => reason);
    expect(refused).toBeInstanceOf(ApiError);
    expect((refused as ApiError).retryAfterS).toBe(seconds);
  });

  it("reads standing-order drift from the gateway for the kitchen and for the supplier", async () => {
    const warning = {
      product_id: "460008",
      product_name: "Barilla 5kg Fusilli dry pasta",
      kind: "portion_creep",
      change: 0.631,
      unit: "BAG",
      qty_per_100: 0.15,
      baseline_qty: 0.09,
      spend_per_100: 2.67,
      baseline_spend: 1.64,
      baseline_weeks: 4,
      why: "0.15 BAG per 100 guests last week, 0.09 on average over the 4 weeks before (+63%).",
    };
    const calls = gateway({
      [`GET ${K}/drift`]: () => ({ week: "2026-11-02", warnings: [warning] }),
      "GET /api/v1/suppliers/sup-valio/demand/drift": () => ({
        week: "2026-11-02",
        warnings: [{ ...warning, kitchen_id: "K01", kitchen_name: "School 1 Tampere" }],
      }),
    });
    const api = createHttpApi("/api");

    const own = await api.getDrift();
    expect(own).toMatchObject({ week: "2026-11-02" });
    expect(own.warnings[0]).toMatchObject({ productId: "460008", productName: "Barilla 5kg Fusilli dry pasta" });
    const shared = await api.getSupplierDrift();
    expect(shared.warnings[0]).toMatchObject({ kitchenId: "K01", kitchenName: "School 1 Tampere" });
    expect(calls.map((call) => call.route)).toEqual([
      `GET ${K}/drift`,
      "GET /api/v1/suppliers/sup-valio/demand/drift",
    ]);
  });

  it("passes a drift error on, so the tile shows it instead of sample data", async () => {
    gateway({ [`GET ${K}/drift`]: () => error(503, "DRIFT_UNAVAILABLE") });
    await expect(createHttpApi("/api").getDrift()).rejects.toMatchObject({ code: "DRIFT_UNAVAILABLE" });
  });

  it("is not a thenable, so awaiting the Api itself settles", async () => {
    gateway({});
    const api = createHttpApi("/api");
    expect((api as unknown as { then?: unknown }).then).toBeUndefined();
    await expect(Promise.resolve(api)).resolves.toBe(api);
  });

  it("approves the exact total the person read, as that person, with no token from the browser", async () => {
    const approved = { ...proposal, status: "APPROVED", order_id: "ord-1" };
    const calls = gateway({
      ...inbox(approved),
      [`POST ${K}/proposals/prop-1/approve`]: () => ({ proposal_id: "prop-1", ...placedOrder }),
    });
    const result = await createHttpApi("/api").approve(
      { approvalId: "prop-1", approvalRef: "appr-1", expectedTotalExVat: 80, expectedTotalInclVat: 91.2 },
      "chef",
    );
    expect(result.status).toBe("APPROVED");
    expect(calls[0].route).toBe(`POST ${K}/proposals/prop-1/approve`);
    expect(calls.filter((call) => call.route === `POST ${K}/proposals/prop-1/approve`)).toHaveLength(1);
    const approvalCall = calls.find((call) => call.route === `POST ${K}/proposals/prop-1/approve`);
    expect(approvalCall?.body).toEqual({
      expected_total: "91.20",
      idempotency_key: "web-approve:prop-1:91.20:appr-1",
    });
    expect(approvalCall?.headers).toMatchObject({ "X-User": "chef" });
    expect(calls.every((call) => !("Authorization" in call.headers))).toBe(true);
  });

  it("reuses one idempotency key when the same approval decision is retried", async () => {
    const approved = { ...proposal, status: "APPROVED", order_id: "ord-1" };
    const calls = gateway({
      ...inbox(approved),
      [`POST ${K}/proposals/prop-1/approve`]: () => ({ proposal_id: "prop-1", ...placedOrder }),
    });
    const api = createHttpApi("/api");
    const decision = { approvalId: "prop-1", approvalRef: "appr-1", expectedTotalExVat: 80, expectedTotalInclVat: 91.2 };

    await api.approve(decision, "human");
    await api.approve(decision, "human");

    const keys = calls.filter((call) => call.route.endsWith("/approve")).map((call) => call.body.idempotency_key);
    expect(keys).toEqual(["web-approve:prop-1:91.20:appr-1", "web-approve:prop-1:91.20:appr-1"]);
  });

  it("uses a stable first-attempt key when the gateway sent no approval id", async () => {
    const approved = { ...proposal, status: "APPROVED", order_id: "ord-1" };
    const calls = gateway({
      ...inbox(approved),
      [`POST ${K}/proposals/prop-1/approve`]: () => ({ proposal_id: "prop-1", ...placedOrder }),
    });
    const api = createHttpApi("/api");
    const decision = { approvalId: "prop-1", approvalRef: null, expectedTotalExVat: 80, expectedTotalInclVat: 91.2 };

    await api.approve(decision, "human");
    await api.approve(decision, "human");

    const keys = calls.filter((call) => call.route.endsWith("/approve")).map((call) => call.body.idempotency_key);
    expect(keys).toEqual(["web-approve:prop-1:91.20:first", "web-approve:prop-1:91.20:first"]);
  });

  it("rejects with the reason", async () => {
    const calls = gateway({
      ...inbox({ ...proposal, status: "REJECTED" }),
      [`POST ${K}/proposals/prop-1/reject`]: () => ({ status: "REJECTED" }),
    });
    expect((await createHttpApi("/api").reject("prop-1", "Too much", "human")).status).toBe("REJECTED");
    expect(calls[0].body).toEqual({ reason: "Too much", idempotency_key: "web-reject:prop-1" });
    expect(calls[0].headers).toMatchObject({ "X-User": "human" });
  });

  describe("one request while one is in flight", () => {
    /** A gateway whose GETs wait for the test, so it decides when they settle. */
    function slowGateway() {
      const pending: (() => void)[] = [];
      const calls: string[] = [];
      vi.stubGlobal("fetch", (url: string, init: RequestInit = {}) => {
        const route = `${init.method ?? "GET"} ${url}`;
        calls.push(route);
        if (route === `POST ${K}/proposals/prop-1/reject`) {
          return Promise.resolve(new Response(JSON.stringify({ status: "REJECTED" })));
        }
        return new Promise((reply) => {
          pending.push(() => {
            const body = route.endsWith("/audit") ? { events: auditEvents } : { proposals: [proposal] };
            reply(new Response(JSON.stringify(body)));
          });
        });
      });
      return {
        answer: () => pending.splice(0).forEach((reply) => reply()),
        count: (route: string) => calls.filter((call) => call === route).length,
      };
    }

    it("shares the proposals and audit GETs between calls started together", async () => {
      const gateway = slowGateway();
      const api = createHttpApi("/api");
      const first = api.listApprovals();
      const second = api.listApprovals();
      const audit = api.listAudit();
      expect(gateway.count(`GET ${K}/proposals`)).toBe(1);
      expect(gateway.count(`GET ${K}/audit`)).toBe(1);
      gateway.answer();
      await Promise.all([first, second, audit]);

      const again = api.listAudit();
      expect(gateway.count(`GET ${K}/audit`)).toBe(2);
      gateway.answer();
      await again;
    });

    it("does not reuse a GET that started before a POST began", async () => {
      const calls: string[] = [];
      let run = 0;
      vi.stubGlobal("fetch", (url: string, init: RequestInit = {}) => {
        const route = `${init.method ?? "GET"} ${url}`;
        calls.push(route);
        if (route === "GET /api/v1/me") return Promise.resolve(new Response("null"));
        if (route === `GET ${K}/proposals` && run++ === 0) return new Promise<Response>(() => {});
        const rejected = { ...proposal, status: "REJECTED" };
        const body =
          route === `GET ${K}/proposals`
            ? { proposals: [rejected] }
            : route === `GET ${K}/proposals/prop-1`
              ? rejected
              : route === `GET ${K}/audit`
                ? { events: auditEvents }
                : { status: "REJECTED" };
        return Promise.resolve(new Response(JSON.stringify(body)));
      });
      const api = createHttpApi("/api");
      void api.listApprovals();
      await api.reject("prop-1", "Too much", "human");
      const after = api.listApprovals();
      expect(calls.filter((call) => call === `GET ${K}/proposals`)).toHaveLength(2);
      await after;
    });

    it("rejects every caller of a failed GET, then asks again", async () => {
      let answers = 1;
      const calls: string[] = [];
      vi.stubGlobal("fetch", (url: string) => {
        calls.push(`GET ${url}`);
        return Promise.resolve(
          answers-- > 0
            ? error(503, "UNAVAILABLE")
            : new Response(JSON.stringify({ events: auditEvents })),
        );
      });
      const api = createHttpApi("/api");
      const first = api.listAudit();
      const second = api.listAudit();
      await expect(first).rejects.toMatchObject({ code: "UNAVAILABLE" });
      await expect(second).rejects.toMatchObject({ code: "UNAVAILABLE" });
      await expect(api.listAudit()).resolves.toBeInstanceOf(Array);
      expect(calls).toEqual([`GET ${K}/audit`, `GET ${K}/audit`]);
    });

    it("does not reuse a GET that started before a write another module sent", async () => {
      const calls: string[] = [];
      vi.stubGlobal("fetch", (url: string, init: RequestInit = {}) => {
        const route = `${init.method ?? "GET"} ${url}`;
        calls.push(route);
        if (route === `GET ${K}/proposals` || route === `GET ${K}/audit`) return new Promise<Response>(() => {});
        return Promise.resolve(new Response("{}"));
      });
      const api = createHttpApi("/api");
      void api.listApprovals();
      // The request form, the offers and the planning screens send their writes through gatewayRequest.
      await gatewayRequest("/api", "/v1/kitchens/demo-kitchen/proposals", { method: "POST", body: "{}" });
      void api.listApprovals();
      expect(calls.filter((call) => call === `GET ${K}/proposals`)).toHaveLength(2);
      expect(calls.filter((call) => call === `GET ${K}/audit`)).toHaveLength(2);
    });

    it("does not reuse a GET that started while a POST was in flight", async () => {
      const calls: string[] = [];
      let finishPost: () => void = () => {};
      vi.stubGlobal("fetch", (url: string, init: RequestInit = {}) => {
        const route = `${init.method ?? "GET"} ${url}`;
        calls.push(route);
        if (route === `POST ${K}/proposals`) {
          return new Promise<Response>((reply) => (finishPost = () => reply(new Response("{}"))));
        }
        return new Promise<Response>(() => {});
      });
      const api = createHttpApi("/api");
      const write = gatewayRequest("/api", "/v1/kitchens/demo-kitchen/proposals", { method: "POST", body: "{}" });
      void api.listApprovals();
      finishPost();
      await write;
      void api.listApprovals();
      expect(calls.filter((call) => call === `GET ${K}/proposals`)).toHaveLength(2);
      expect(calls.filter((call) => call === `GET ${K}/audit`)).toHaveLength(2);
    });

    it("does not reuse a GET that started before a live event", async () => {
      const calls: string[] = [];
      const encoder = new TextEncoder();
      vi.stubGlobal("fetch", (url: string, init: RequestInit = {}) => {
        const route = `${init.method ?? "GET"} ${url}`;
        calls.push(route);
        if (route === `GET ${K}/events`) {
          const body = new ReadableStream<Uint8Array>({
            start: (controller) => controller.enqueue(encoder.encode('event: proposal\ndata: {"operation":"insert"}\n\n')),
          });
          return Promise.resolve(new Response(body));
        }
        return new Promise<Response>(() => {});
      });
      const api = createHttpApi("/api");
      void api.listApprovals();
      const seen: string[] = [];
      const stop = api.subscribeEvents!((event) => {
        // What a list does on a live event: it reads again, and that read must be a new request.
        seen.push(event.kind);
        void api.listApprovals();
      });
      await waitFor(() => expect(seen).toEqual(["proposal"]));
      expect(calls.filter((call) => call === `GET ${K}/proposals`)).toHaveLength(2);
      stop();
    });

    it("does not reuse a GET that started before the event stream connected again", async () => {
      const calls: string[] = [];
      vi.stubGlobal("fetch", (url: string, init: RequestInit = {}) => {
        const route = `${init.method ?? "GET"} ${url}`;
        calls.push(route);
        // An open stream with no event: only the connection itself is reported.
        if (route === `GET ${K}/events`) return Promise.resolve(new Response(new ReadableStream<Uint8Array>()));
        return new Promise<Response>(() => {});
      });
      const api = createHttpApi("/api");
      void api.listAudit();
      let connected = false;
      const stop = api.subscribeEvents!(
        () => {},
        (isConnected) => {
          connected = isConnected;
          if (isConnected) void api.listAudit();
        },
      );
      await waitFor(() => expect(connected).toBe(true));
      expect(calls.filter((call) => call === `GET ${K}/audit`)).toHaveLength(2);
      stop();
    });

    it("counts pending approvals from the proposals alone", async () => {
      const waiting = { ...proposal, status: "READY" };
      const calls = gateway({
        [`GET ${K}/proposals`]: () => ({
          proposals: [
            waiting,
            { ...waiting, proposal_id: "prop-2", approval_id: "appr-2" },
            { ...proposal, status: "REJECTED", approval_id: "appr-3" },
          ],
        }),
      });
      expect(await createHttpApi("/api").countPendingApprovals!()).toBe(2);
      expect(calls.map((call) => call.route)).toEqual([`GET ${K}/proposals`]);
    });
  });

  it("lists and checks recalls through the gateway with a fresh key and actor on every check", async () => {
    const answer = { last_check: null, alerts: [] };
    const calls = gateway({
      [`GET ${K}/recalls`]: () => answer,
      [`POST ${K}/recalls/check`]: () => answer,
    });
    const api = createHttpApi("/api");
    expect(await api.listRecalls!()).toEqual({ lastCheck: null, alerts: [] });
    expect(await api.checkRecalls!("chef")).toEqual({ lastCheck: null, alerts: [] });
    await api.checkRecalls!("human");
    expect(calls.map((call) => call.route)).toEqual([
      `GET ${K}/recalls`,
      `POST ${K}/recalls/check`,
      `POST ${K}/recalls/check`,
    ]);
    const checks = calls.filter((call) => call.route.startsWith("POST"));
    expect(checks[0].headers).toMatchObject({ "X-User": "chef" });
    expect(checks[1].headers).toMatchObject({ "X-User": "human" });
    expect(checks[0].body.idempotency_key).toMatch(/^recall-check-[0-9a-f]{32}$/);
    expect(checks[1].body.idempotency_key).toMatch(/^recall-check-[0-9a-f]{32}$/);
    expect(checks[1].body.idempotency_key).not.toBe(checks[0].body.idempotency_key);
  });

  it("explains an attempted approval of a held proposal as blocked by a recall", async () => {
    gateway({ [`POST ${K}/proposals/prop-1/approve`]: () => error(409, "BLOCKED_BY_RECALL") });
    await expect(
      createHttpApi("/api").approve(
        { approvalId: "prop-1", approvalRef: "appr-1", expectedTotalExVat: 80, expectedTotalInclVat: 91.2 },
        "human",
      ),
    ).rejects.toMatchObject({ code: "BLOCKED_BY_RECALL", message: expect.stringContaining("blocked by a recall") });
  });

  it("omits X-User on decisions after signing in with an email", async () => {
    const calls = gateway({
      ...inbox({ ...proposal, status: "APPROVED", order_id: "ord-1" }),
      "POST /api/v1/auth/login": () => ({
        email: "buyer@example.com",
        name: "Buyer",
        role: "approver",
        kitchen_id: "demo-kitchen",
      }),
      [`POST ${K}/proposals/prop-1/approve`]: () => ({ proposal_id: "prop-1", ...placedOrder }),
    });
    const api = createHttpApi("/api");
    expect(await api.signIn("buyer@example.com", "demo-kitchen-2026")).toMatchObject({
      email: "buyer@example.com",
      role: "approver",
      canApprove: true,
    });
    await api.approve({ approvalId: "prop-1", approvalRef: "appr-1", expectedTotalExVat: 80, expectedTotalInclVat: 91.2 }, "human");
    const approvalCall = calls.find((call) => call.route.includes("/approve"));
    expect(approvalCall?.headers).not.toHaveProperty("X-User");
    expect(calls[0].body).toEqual({ email: "buyer@example.com", password: "demo-kitchen-2026" });
  });

  it("lets a signed-in chef not approve, and reads a person's email from the /v1/me name", async () => {
    gateway({
      "POST /api/v1/auth/login": () => ({ email: "chef@example.com", name: "Chef", role: "chef" }),
      "GET /api/v1/me": () => ({ kind: "human", name: "a@b.c", role: "approver", can_approve: true }),
    });
    const api = createHttpApi("/api");
    expect(await api.signIn("chef@example.com", "demo-kitchen-2026")).toMatchObject({ canApprove: false });
    expect(await api.getSession()).toMatchObject({ name: "a@b.c", email: "a@b.c", canApprove: true });
  });

  it("does not take an agent's name as an email", async () => {
    gateway({
      "GET /api/v1/me": () => ({ kind: "agent", name: "bot@example.com", role: "approver", can_approve: true }),
    });
    expect(await createHttpApi("/api").getSession()).toMatchObject({ email: null, canApprove: false });
  });

  it("does not allow an agent session to approve even when the approval flag is true", async () => {
    gateway({
      "POST /api/v1/auth/login": () => ({
        email: "agent@example.com",
        name: "Buyer agent",
        role: "approver",
        kind: "agent",
        can_approve: true,
      }),
    });
    expect(await createHttpApi("/api").signIn("agent@example.com", "demo-kitchen-2026")).toMatchObject({
      role: "approver",
      canApprove: false,
    });
  });

  it("maps login errors and treats an unauthenticated session as signed out", async () => {
    gateway({
      "POST /api/v1/auth/login": () => error(401, "INVALID_LOGIN", { message: "wrong email or password" }),
      "GET /api/v1/me": () => error(401, "SESSION_EXPIRED"),
    });
    const api = createHttpApi("/api");
    await expect(api.signIn("nobody@example.com", "not-the-password")).rejects.toMatchObject({
      code: "INVALID_LOGIN",
      message: "wrong email or password",
      status: 401,
    });
    expect(await api.getSession()).toBeNull();
  });

  it("says a locked account must wait five minutes, not the one minute of a rate limit", async () => {
    gateway({
      "POST /api/v1/auth/login": () => error(429, "ACCOUNT_LOCKED", { message: "too many wrong passwords" }),
      "GET /api/v1/me": () => error(429, "ACCOUNT_LOCKED"),
    });
    const api = createHttpApi("/api");
    await expect(api.signIn("buyer@example.com", "demo-kitchen-2026")).rejects.toMatchObject({
      code: "ACCOUNT_LOCKED",
      message: "Too many wrong passwords. Try again in five minutes.",
      status: 429,
    });
    // Any other 429 stays the rate limit, whatever code it names.
    await expect(api.getSession()).rejects.toMatchObject({ code: "RATE_LIMITED" });
  });

  it.each(["PRICE_LIST_BUSY", "MENU_PHOTO_BUSY", "LABEL_PHOTO_BUSY"])("keeps the busy code %s of a 429", async (code) => {
    gateway({ "GET /api/v1/me": () => error(429, code) });
    await expect(createHttpApi("/api").getSession()).rejects.toMatchObject({ code, status: 429 });
  });

  it("keeps SUPPLIER_BUSY of a 429 with its retry_after", async () => {
    gateway({ "GET /api/v1/me": () => error(429, "SUPPLIER_BUSY", { retry_after: 30 }) });
    await expect(createHttpApi("/api").getSession()).rejects.toMatchObject({
      code: "SUPPLIER_BUSY",
      status: 429,
      details: { retry_after: 30 },
    });
  });

  it("clears the local account when logout fails", async () => {
    const approved = { ...proposal, status: "APPROVED", order_id: "ord-1" };
    const calls = gateway({
      ...inbox(approved),
      "POST /api/v1/auth/login": () => ({
        email: "buyer@example.com",
        name: "Buyer",
        role: "approver",
        kind: "human",
        can_approve: true,
      }),
      "POST /api/v1/auth/logout": () => error(401, "UNAUTHENTICATED"),
      [`POST ${K}/proposals/prop-1/approve`]: () => ({ proposal_id: "prop-1", ...placedOrder }),
    });
    const api = createHttpApi("/api");
    await api.signIn("buyer@example.com", "demo-kitchen-2026");

    await expect(api.signOut()).resolves.toBeUndefined();
    await api.approve({ approvalId: "prop-1", approvalRef: "appr-1", expectedTotalExVat: 80, expectedTotalInclVat: 91.2 }, "chef");

    expect(calls.find((call) => call.route.includes("/approve"))?.headers).toMatchObject({ "X-User": "chef" });
  });

  it("announces an expired session for other requests and still throws the gateway error", async () => {
    gateway({ [`GET ${K}/audit`]: () => error(401, "SESSION_EXPIRED") });
    const signedOut = vi.fn();
    window.addEventListener(SIGNED_OUT_EVENT, signedOut);
    try {
      await expect(createHttpApi("/api").listAudit()).rejects.toMatchObject({
        code: "SESSION_EXPIRED",
        status: 401,
      });
      expect(signedOut).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener(SIGNED_OUT_EVENT, signedOut);
    }
  });

  it("changes the password through the gateway", async () => {
    const calls = gateway({ "POST /api/v1/auth/change-password": () => ({ changed: true }) });
    await createHttpApi("/api").changePassword("demo-kitchen-2026", "a-new-demo-password");
    expect(calls[0].body).toEqual({ current_password: "demo-kitchen-2026", new_password: "a-new-demo-password" });
  });

  it("lists placed orders with the basket of the proposal that placed them", async () => {
    gateway({
      [`GET ${K}/orders`]: () => ({ orders: [placedOrder, { ...placedOrder, order_id: "ord-old" }] }),
      [`GET ${K}/proposals`]: () => ({ proposals: [{ ...proposal, status: "APPROVED", order_id: "ord-1" }] }),
    });
    const [joined, alone] = await createHttpApi("/api").listOrders();
    expect(joined).toMatchObject({ id: "ord-1", status: "PLACED", deliveryDate: "2026-11-20", totalExVat: 80 });
    expect(alone).toMatchObject({ id: "ord-old", status: "PLACED", deliveryDate: null, totalExVat: null });
  });

  it("reads the totals of an order from the order answer, not only from its proposal (#1630)", async () => {
    const own = { total_ex_vat: "80.00", vat: "11.20", total_incl_vat: "91.20", vat_unknown: [], delivery_fee: null };
    const oat = { ...placedOrder.lines[0], product_name: "Oat drink" };
    gateway({
      [`GET ${K}/orders`]: () => ({
        orders: [
          { ...placedOrder, ...own },
          {
            ...placedOrder,
            order_id: "ord-unknown",
            lines: [oat],
            total_ex_vat: "80.00",
            vat: null,
            total_incl_vat: null,
            vat_unknown: ["900001"],
            expected_total: "80.00",
          },
        ],
      }),
      [`GET ${K}/proposals`]: () => ({ proposals: [] }),
    });
    const [known, unknown] = await createHttpApi("/api").listOrders();
    // No proposal at hand: the ex-VAT total still comes from the order itself.
    expect(known).toMatchObject({ id: "ord-1", totalExVat: 80, vat: 11.2, inclVat: 91.2, vatUnknown: [] });
    // An unknown rate: incl VAT is unknown, never the ex-VAT sum; the approve figure stays.
    expect(unknown).toMatchObject({ totalExVat: 80, vat: null, inclVat: null, vatUnknown: ["Oat drink"], totalInclVat: 80 });
  });

  it("skips a malformed proposal or order and lists the rest", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    gateway({
      [`GET ${K}/proposals`]: () => ({ proposals: [proposal, { proposal_id: "prop-old" }] }),
      [`GET ${K}/audit`]: () => ({ events: auditEvents }),
      [`GET ${K}/orders`]: () => ({ orders: [placedOrder, { order_id: "ord-bad", expected_total: "1.00" }] }),
    });
    const api = createHttpApi("/api");
    const approvals = await api.listApprovals();
    expect(approvals.map((a) => a.id)).toEqual(["prop-1"]);
    const orders = await api.listOrders();
    expect(orders.map((o) => o.id)).toEqual(["ord-1"]);
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("prop-old"), expect.anything());
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("ord-bad"), expect.anything());
    warn.mockRestore();
  });

  it("gets an order by its order id or by the id of a waiting proposal", async () => {
    gateway({
      ...inbox(),
      // No `GET /proposals/ord-1` route: asking the proposal route for an order id (a 404 on
      // every order page) would fail this test with NO_ROUTE.
      [`GET ${K}/orders/ord-1`]: () => placedOrder,
      [`GET ${K}/proposals`]: () => ({
        proposals: [proposal, { ...proposal, proposal_id: "prop-2", status: "APPROVED", order_id: "ord-1" }],
      }),
    });
    const api = createHttpApi("/api");
    expect(await api.getOrder("prop-1")).toMatchObject({ id: "prop-1", status: "NEEDS_APPROVAL" });
    expect(await api.getOrder("ord-1")).toMatchObject({ id: "ord-1", status: "PLACED", totalExVat: 80 });
    await expect(api.getOrder("nope")).rejects.toMatchObject({ code: "NO_ROUTE" });
  });

  // The demo seed's delivery order (#1726): placed without a proposal, VAT not known.
  const seededOrder = {
    ...placedOrder,
    order_id: "ord-seed",
    placed_by: "demo-seed",
    receipt: null,
    supplier_must_confirm: [],
    expected_total: "178.09",
    total_ex_vat: "178.09",
    vat: null,
    total_incl_vat: null,
    vat_unknown: ["900001"],
    delivery_fee: null,
    lines: [{ product_id: "900001", name: "Kieku barn eggs L, 180 pcs", product_name: "Kieku Barn Eggs L180", quantity: "3", unit: "KI", unit_price: "59.36", total: "178.09", unknown_stock: false, reason_codes: [], vat_rate: null, vat_source: null }],
  };

  it("asks the order route first for an id that is on the proposals list neither way", async () => {
    const calls = gateway({
      [`GET ${K}/proposals`]: () => ({ proposals: [] }),
      [`GET ${K}/orders/ord-seed`]: () => seededOrder,
    });
    const order = await createHttpApi("/api").getOrder("ord-seed");
    expect(calls.map((call) => call.route)).not.toContain(`GET ${K}/proposals/ord-seed`);
    // The money is the order row's own; the VAT it does not know stays unknown, never 0.
    expect(order).toMatchObject({ id: "ord-seed", status: "PLACED", totalExVat: 178.09, vat: null, deliveryFee: null, withoutProposal: true });
  });

  it("still opens a waiting proposal that is somehow not on the list", async () => {
    gateway({
      [`GET ${K}/proposals`]: () => ({ proposals: [] }),
      [`GET ${K}/orders/prop-1`]: () => error(404, "ORDER_NOT_FOUND"),
      [`GET ${K}/proposals/prop-1`]: () => proposal,
    });
    const order = await createHttpApi("/api").getOrder("prop-1");
    expect(order).toMatchObject({ id: "prop-1", status: "NEEDS_APPROVAL" });
    expect(order.withoutProposal).toBeUndefined();
  });

  it("shows an order recorded without its proposal without a column of unknowns", async () => {
    const calls = gateway({
      [`GET ${K}/proposals`]: () => ({ proposals: [] }),
      [`GET ${K}/orders/ord-seed`]: () => seededOrder,
      [`GET ${K}/audit`]: () => ({ events: [] }),
    });
    renderApp("/orders/ord-seed", createHttpApi("/api"));

    const lines = await screen.findByRole("list", { name: "Lines" });
    expect(within(lines).getByText("Kieku Barn Eggs L180")).toBeVisible();
    expect(within(lines).getByText("Unit price ex VAT")).toBeVisible();
    for (const left of ["Compare", "Available", "Order by", "Why: ", "pack size not in the catalog"]) {
      expect(within(lines).queryByText(left)).not.toBeInTheDocument();
    }
    expect(screen.getByText("This order was recorded without its proposal, so the offer details are not shown.")).toBeVisible();
    expect(screen.getByText("not recorded")).toBeVisible();
    const totals = screen.getByText("Total ex VAT").closest("dl")!;
    expect(within(totals).getByText("Total ex VAT").nextElementSibling).toHaveTextContent("178.09");
    expect(within(totals).getByText("VAT").nextElementSibling).toHaveTextContent("unknown");
    expect(within(totals).getByText("Total incl VAT").nextElementSibling).toHaveTextContent("unknown");
    expect(totals).not.toHaveTextContent(/€\s?0[.,]00/);
    expect(calls.map((call) => call.route)).not.toContain(`GET ${K}/proposals/ord-seed`);
  });

  it("reads the current role and what is known about an unknown send", async () => {
    const calls = gateway({
      "GET /api/v1/me": () => ({
        kind: "human",
        name: "aron",
        role: "approver",
        kitchen_id: "demo-kitchen",
        can_approve: true,
        scopes: null,
      }),
      [`GET ${K}/orders/ord-unknown/resolution`]: () => ({
        order_id: "ord-unknown",
        proposal_id: "prop-1",
        proposal_status: "COMMITTING",
        idempotency_key: "approve-7",
        payload_hash: "abc123",
        offer_id: "offer-1",
        supplier_id: "sup-valio",
        approved_by: "aron",
        outcome: "UNCONFIRMED",
        status: null,
        expected_total: "74.51",
        lines: [proposal.lines[0]],
        created_at: "2026-11-14T02:10:00+00:00",
        updated_at: "2026-11-14T02:10:01+00:00",
        resolvable: true,
        resolution: null,
      }),
    });
    const api = createHttpApi("/api");
    expect(await api.getSession()).toEqual({
      kind: "human",
      name: "aron",
      email: null,
      role: "approver",
      canApprove: true,
    });
    expect(await api.getOrderResolution("ord-unknown")).toMatchObject({
      orderId: "ord-unknown",
      proposalId: "prop-1",
      idempotencyKey: "approve-7",
      expectedTotal: 74.51,
      approvedBy: "aron",
      outcome: "UNCONFIRMED",
      status: null,
      resolvable: true,
      resolution: null,
      lines: [{ quantity: 40 }],
    });
    expect(calls.map((call) => call.route)).toEqual([
      "GET /api/v1/me",
      `GET ${K}/orders/ord-unknown/resolution`,
    ]);
  });

  it("records placed and not_sent with their distinct request bodies, without resending", async () => {
    const placedResult = {
      order_id: "ord-unknown",
      proposal_id: "prop-1",
      proposal_status: "APPROVED",
      outcome: "CONFIRMED",
      status: "RECORDED",
      resolution: {
        resolution: "placed",
        supplier_order_ref: "VAL-2026-00123",
        note: "",
        resolved_by: "aron",
        resolved_at: "2026-11-14T02:31:00+00:00",
        from_outcome: "UNCONFIRMED",
      },
    };
    const calls = gateway({
      [`POST ${K}/orders/ord-unknown/resolve`]: (_body) => placedResult,
    });
    const api = createHttpApi("/api");
    expect(
      await api.resolveOrder("ord-unknown", { resolution: "placed", supplierOrderRef: " VAL-2026-00123 " }, "aron"),
    ).toMatchObject({ outcome: "CONFIRMED", resolution: { supplierOrderRef: "VAL-2026-00123" } });
    await api.resolveOrder("ord-unknown", { resolution: "not_sent", note: " Valio has no such order " }, "aron");
    expect(calls).toHaveLength(2);
    expect(calls[0]).toMatchObject({
      route: `POST ${K}/orders/ord-unknown/resolve`,
      headers: { "X-User": "aron" },
      body: { resolution: "placed", supplier_order_ref: "VAL-2026-00123" },
    });
    expect(calls[0].body.idempotency_key).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    expect(calls[1].body).toEqual({
      resolution: "not_sent",
      note: "Valio has no such order",
      idempotency_key: expect.any(String),
    });
    expect(calls.every((call) => !call.route.endsWith("/approve"))).toBe(true);
  });

  it("uses the new server approval id for a fresh key after not_sent and a reload", async () => {
    let currentProposal = proposal;
    const calls = gateway({
      ...inbox(),
      [`GET ${K}/proposals/prop-1`]: () => currentProposal,
      [`POST ${K}/orders/ord-unknown/resolve`]: () => {
        currentProposal = { ...proposal, approval_id: "appr-2" };
        return {
          order_id: "ord-unknown",
          proposal_id: "prop-1",
          proposal_status: "READY",
          outcome: "NOT_SENT",
          status: null,
          resolution: {
            resolution: "not_sent",
            supplier_order_ref: null,
            note: "No such order",
            resolved_by: "aron",
            resolved_at: "2026-11-14T02:31:00+00:00",
            from_outcome: "UNCONFIRMED",
          },
        };
      },
      [`POST ${K}/proposals/prop-1/approve`]: () => placedOrder,
    });
    const api = createHttpApi("/api");
    const decision = { approvalId: "prop-1", approvalRef: "appr-1", expectedTotalExVat: 80, expectedTotalInclVat: 91.2 };
    await api.approve(decision, "human");
    const originalKey = calls.find((call) => call.route.endsWith("/approve"))!.body.idempotency_key;
    await api.resolveOrder("ord-unknown", { resolution: "not_sent", note: "No such order" }, "aron");
    const reloaded = createHttpApi("/api");
    const reopened = await reloaded.getApproval("prop-1");
    expect(reopened.approvalRef).toBe("appr-2");
    await reloaded.approve({ ...decision, approvalRef: reopened.approvalRef }, "human");
    const approvalCalls = calls.filter((call) => call.route.endsWith("/approve"));
    expect(originalKey).toBe("web-approve:prop-1:91.20:appr-1");
    expect(approvalCalls[1].body.idempotency_key).toBe("web-approve:prop-1:91.20:appr-2");
    expect(approvalCalls[1].body.idempotency_key).not.toBe(originalKey);
  });

  it("reads the forecast check from the two forecast routes; nothing compared stays unknown", async () => {
    const empty = { predicted: 0, actual: 0, wape: 0, bias: 0, under: 0, over: 0, series: 0 };
    const calls = gateway({});
    vi.stubGlobal("fetch", async (url: string) => {
      calls.push({ route: `GET ${url}`, headers: {}, body: {} });
      return new Response(
        JSON.stringify(
          url.includes("/forecast-accuracy?")
            ? { methods: { engine: { total: empty, weeks: [] }, "weekday-average": { total: empty, weeks: [] } } }
            : { lines: [] },
        ),
      );
    });
    const result = await createHttpApi("/api").getForecastAccuracy();
    expect(result.kitchen).toMatchObject({ weeks: [], engine: { wape: null }, baseline: { wape: null } });
    expect(calls.map((call) => call.route).sort()).toEqual([
      expect.stringMatching(
        new RegExp(`^GET ${K}/forecast-accuracy\\?from=\\d{4}-\\d\\d-\\d\\d&to=\\d{4}-\\d\\d-\\d\\d$`),
      ),
      expect.stringMatching(new RegExp(`^GET ${K}/forecast\\?from=\\d{4}-\\d\\d-\\d\\d&to=\\d{4}-\\d\\d-\\d\\d$`)),
    ]);
  });

  it("reuses the Buyer request key after a failure and replaces it after an answer", async () => {
    let attempts = 0;
    const calls = gateway({
      ...inbox(),
      [`POST ${K}/proposals`]: () =>
        attempts++ ? { proposal_id: "prop-1", status: "READY" } : error(503, "BUYER_TIMEOUT"),
    });
    const api = createHttpApi("/api");
    const request = { text: " 50 L oat drink by Friday ", covers: null, deliveryDate: "2026-11-20" };
    await expect(api.submitChefRequest(request)).rejects.toMatchObject({ code: "BUYER_TIMEOUT" });
    const result = await api.submitChefRequest(request);
    expect(result).toMatchObject({
      order: { id: "prop-1", status: "NEEDS_APPROVAL" },
      approval: { id: "prop-1" },
      substitutes: [],
    });
    await api.submitChefRequest(request);
    const posts = calls.filter((call) => call.route.startsWith("POST"));
    expect(posts[0].body).toMatchObject({ text: "50 L oat drink by Friday", requested_date: "2026-11-20" });
    expect(posts[0].body.idempotency_key).toBeTruthy();
    expect(posts[1].body.idempotency_key).toBe(posts[0].body.idempotency_key);
    expect(posts[2].body.idempotency_key).not.toBe(posts[0].body.idempotency_key);
  });
});

describe("the app on the gateway", () => {
  it("shows sign-in when a request after the session check answers 401", async () => {
    gateway({
      "GET /api/v1/me": () => ({ kind: "human", name: "Demo approver", role: "approver", can_approve: true }),
      [`GET ${K}/proposals`]: () => error(401, "SESSION_EXPIRED"),
      [`GET ${K}/audit`]: () => ({ events: auditEvents }),
    });
    renderApp("/approvals", createHttpApi("/api"));

    expect(await screen.findByRole("heading", { name: "Sign in to Kitchen Buyer" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Open menu" })).not.toBeInTheDocument();
  });

  it("shows the real proposal and, when the total moved, the new total before asking again", async () => {
    // As deployed: with the gateway Api, the Api-backed inbox is the live one.
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    const user = userEvent.setup();
    let current = proposal;
    gateway({
      "GET /api/v1/me": () => ({ kind: "human", name: "Demo approver", role: "approver", can_approve: true }),
      [`GET ${K}/proposals`]: () => ({ proposals: [current] }),
      [`GET ${K}/proposals/prop-1`]: () => current,
      [`GET ${K}/proposals/prop-1/addable`]: () => ({ proposal_id: "prop-1", rows: [], skipped: [] }),
      [`GET ${K}/audit`]: () => ({ events: auditEvents }),
      [`POST ${K}/proposals/prop-1/approve`]: () => {
        current = { ...proposal, total_ex_vat: "83.33", expected_total: "95.00" };
        return error(409, "TOTAL_MISMATCH", { expected_total: "95.00" });
      },
    });
    renderApp("/approvals", createHttpApi("/api"));

    expect(await screen.findByText("50 L oat drink by Friday")).toBeVisible();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /^Inspect/ }));
    expect(screen.getAllByText("confirmed").length).toBeGreaterThan(0);
    expect(screen.getByText(/Free-delivery threshold and delivery fee unknown/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: /Approve €91\.20/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €91.20" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The total is now €95.00. Nothing was sent.");
    expect(await screen.findByRole("button", { name: /Approve €95\.00/ })).toBeEnabled();
    expect(screen.getByRole("heading", { name: "Waiting for you (1)" })).toBeVisible();
  });

  it("shows incl VAT as unknown when a rate is unknown, and still approves expected_total (#1630)", async () => {
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    const user = userEvent.setup();
    const unknownVat = {
      ...proposal,
      lines: [{ ...proposal.lines[0], product_name: "Oat drink" }],
      vat: null,
      total_incl_vat: null,
      vat_unknown: ["900001"],
      expected_total: "80.00",
    };
    const calls = gateway({
      ...inbox(unknownVat),
      [`GET ${K}/proposals/prop-1/addable`]: () => ({ proposal_id: "prop-1", rows: [], skipped: [] }),
      [`POST ${K}/proposals/prop-1/approve`]: () => ({ proposal_id: "prop-1", ...placedOrder, expected_total: "80.00" }),
      [`GET ${K}/orders/ord-1`]: () => ({ ...placedOrder, expected_total: "80.00" }),
    });
    renderApp("/approvals", createHttpApi("/api"));

    expect(await screen.findByText("incl VAT unknown: no VAT rate for Oat drink")).toBeVisible();
    expect(screen.queryByText(/€80\.00 incl VAT/)).not.toBeInTheDocument();
    // #1858: no "=": the card shows no fee that the approve figure is the sum with.
    expect(screen.getByText("Total to approve €80.00")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Approve €80.00" }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €80.00" }));
    await waitFor(() => expect(calls.some((call) => call.route === `POST ${K}/proposals/prop-1/approve`)).toBe(true));
    const approve = calls.find((call) => call.route === `POST ${K}/proposals/prop-1/approve`);
    expect(approve?.body).toMatchObject({ expected_total: "80.00" });
    expect(await screen.findByTestId("approval-toast")).toHaveTextContent(
      "Approved and recorded: €80.00 in all (€80.00 ex VAT). Nothing is sent to the supplier.",
    );
    expect(screen.getByTestId("approval-toast")).not.toHaveTextContent("€80.00 incl VAT");
  });

  it("shows the approval and keeps the inbox readable when the audit log fails after approval", async () => {
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    const user = userEvent.setup();
    let current = proposal;
    let auditBroken = false;
    gateway({
      "GET /api/v1/me": () => ({ kind: "human", name: "Demo approver", role: "approver", can_approve: true }),
      [`GET ${K}/proposals`]: () => ({ proposals: [current] }),
      [`GET ${K}/proposals/prop-1`]: () => current,
      [`GET ${K}/proposals/prop-1/addable`]: () => ({ proposal_id: "prop-1", rows: [], skipped: [] }),
      [`GET ${K}/audit`]: () => (auditBroken ? error(503, "UNAVAILABLE") : { events: auditEvents }),
      [`POST ${K}/proposals/prop-1/approve`]: () => {
        current = { ...proposal, status: "APPROVED", order_id: "ord-1" };
        auditBroken = true;
        return { proposal_id: "prop-1", ...placedOrder };
      },
      [`GET ${K}/orders/ord-1`]: () => placedOrder,
    });
    renderApp("/approvals", createHttpApi("/api"));

    await user.click(await screen.findByRole("button", { name: /Approve €91\.20 incl VAT/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €91.20" }));

    expect(await screen.findByTestId("approval-toast")).toHaveTextContent(
      "Approved and recorded: €91.20 in all (€80.00 ex VAT). Nothing is sent to the supplier.",
    );
    expect(await screen.findByRole("heading", { name: "Decided" })).toBeVisible();
    expect(screen.queryByText("UNAVAILABLE")).not.toBeInTheDocument();
  });

  it("shows a proposal's incl VAT from total_incl_vat, not from expected_total (#1630)", async () => {
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    gateway({
      ...inbox({ ...proposal, delivery_fee: "9.90", total_incl_vat: "91.20", vat_unknown: [], expected_total: "101.10" }),
      [`GET ${K}/proposals/prop-1/addable`]: () => ({ proposal_id: "prop-1", rows: [], skipped: [] }),
    });
    renderApp("/approvals", createHttpApi("/api"));

    expect(await screen.findByText("€91.20")).toBeVisible();
    // The approve button keeps the exact figure a person approves, and never calls it incl VAT (#1738).
    expect(screen.getByRole("button", { name: "Approve €101.10" })).toBeVisible();
    expect(screen.queryByText(/€101\.10 incl VAT/)).toBeNull();
  });

  it("shows goods incl VAT + the delivery fee = the amount a person approves, on one card (mock jury, 14 Nov)", async () => {
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    gateway({
      ...inbox({ ...proposal, delivery_fee: "25.00", total_incl_vat: "37.74", vat_unknown: [], expected_total: "62.74" }),
      [`GET ${K}/proposals/prop-1/addable`]: () => ({ proposal_id: "prop-1", rows: [], skipped: [] }),
    });
    renderApp("/approvals", createHttpApi("/api"));

    expect(await screen.findByText("€37.74")).toBeVisible();
    expect(screen.getByText(/^Delivery fee €25\.00/)).toBeVisible();
    expect(screen.getByText("= €62.74 to approve")).toBeVisible();
  });

  it("names both gateway figures when the approve total holds a charge with no fee sent (#1858)", async () => {
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    gateway({
      ...inbox({ ...proposal, delivery_fee: null, total_incl_vat: "347.74", vat_unknown: [], expected_total: "372.74" }),
      [`GET ${K}/proposals/prop-1/addable`]: () => ({ proposal_id: "prop-1", rows: [], skipped: [] }),
    });
    renderApp("/approvals", createHttpApi("/api"));

    expect(await screen.findByText("€347.74")).toBeVisible();
    expect(screen.getByText("Lines incl VAT")).toBeVisible();
    expect(screen.getByText("Total to approve €372.74")).toBeVisible();
    expect(
      screen.getByText("The total to approve includes delivery or other charges the gateway does not itemise."),
    ).toBeVisible();
    expect(screen.queryByText(/Delivery fee/)).not.toBeInTheDocument();
    expect(screen.queryByText(/€25\.00/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve €372\.74 incl VAT/ })).toBeEnabled();
  });

  it("shows each supplier block's own delivery fee when the proposal sends no single fee (#1858)", async () => {
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    const blocks = [
      { supplier_id: "sup-demo-fish", name: "Baltic Catch Fish Wholesale (demo)", delivery_fee: "0.00", lines: [] },
      { supplier_id: "sup-valio", name: "Valio Aimo", delivery_fee: "25.00", lines: [] },
    ];
    gateway({
      ...inbox({ ...proposal, blocks, delivery_fee: null, total_incl_vat: "347.74", vat_unknown: [], expected_total: "372.74" }),
      [`GET ${K}/proposals/prop-1/addable`]: () => ({ proposal_id: "prop-1", rows: [], skipped: [] }),
    });
    renderApp("/approvals", createHttpApi("/api"));

    expect(await screen.findByText("€347.74")).toBeVisible();
    expect(screen.getByText("Delivery fee €25.00 (Valio Aimo)")).toBeVisible();
    expect(screen.queryByText(/Baltic Catch Fish Wholesale \(demo\)\)$/)).not.toBeInTheDocument();
    expect(screen.getByText("Lines incl VAT")).toBeVisible();
    expect(screen.getByText("Total to approve €372.74")).toBeVisible();
    expect(screen.queryByText(/^= /)).not.toBeInTheDocument();
    expect(screen.queryByText(/does not itemise/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve €372\.74 incl VAT/ })).toBeEnabled();
  });

  it("names the figures without the note when the approve total is below the lines total (#1858)", async () => {
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    gateway({
      ...inbox({ ...proposal, delivery_fee: null, total_incl_vat: "347.74", vat_unknown: [], expected_total: "340.00" }),
      [`GET ${K}/proposals/prop-1/addable`]: () => ({ proposal_id: "prop-1", rows: [], skipped: [] }),
    });
    renderApp("/approvals", createHttpApi("/api"));

    expect(await screen.findByText("Total to approve €340.00")).toBeVisible();
    expect(screen.getByText("Lines incl VAT")).toBeVisible();
    expect(screen.queryByText(/does not itemise/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve €340\.00 incl VAT/ })).toBeEnabled();
  });

  it("reads each card's proposal from the list, not one by one (#1858)", async () => {
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    const calls = gateway({
      ...inbox(),
      [`GET ${K}/proposals/prop-1/addable`]: () => ({ proposal_id: "prop-1", rows: [], skipped: [] }),
    });
    renderApp("/approvals", createHttpApi("/api"));

    expect(await screen.findByRole("button", { name: /Approve €91\.20 incl VAT/ })).toBeEnabled();
    expect(calls.filter((call) => call.route === `GET ${K}/proposals/prop-1`)).toEqual([]);
  });

  it("shows the person's reject reason on a rejected card (#1858)", async () => {
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    gateway({
      ...inbox({ ...proposal, status: "REJECTED" }),
      [`GET ${K}/audit`]: () => ({
        events: [
          ...auditEvents,
          { kind: "proposal_rejected", proposal_id: "prop-1", actor: "aron", reason: "Too dear this week", at: "2026-11-14T10:00:00Z" },
        ],
      }),
    });
    renderApp("/approvals", createHttpApi("/api"));

    expect(await screen.findByText("Reason: Too dear this week")).toBeVisible();
  });

  it("shows no breakdown when the amount to approve is the total incl VAT", async () => {
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    gateway({
      ...inbox({ ...proposal, delivery_fee: "0.00", total_incl_vat: "91.20", vat_unknown: [], expected_total: "91.20" }),
      [`GET ${K}/proposals/prop-1/addable`]: () => ({ proposal_id: "prop-1", rows: [], skipped: [] }),
    });
    renderApp("/approvals", createHttpApi("/api"));

    expect(await screen.findByText("€91.20")).toBeVisible();
    expect(screen.queryByText(/to approve/)).not.toBeInTheDocument();
  });

  it("lets a person change the pcs of a READY proposal and then approve the new total", async () => {
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    const user = userEvent.setup();
    let current = proposal;
    const calls = gateway({
      [`GET ${K}/proposals`]: () => ({ proposals: [current] }),
      [`GET ${K}/proposals/prop-1`]: () => current,
      [`GET ${K}/proposals/prop-1/addable`]: () => ({ proposal_id: "prop-1", rows: [], skipped: [] }),
      [`GET ${K}/audit`]: () => ({ events: auditEvents }),
      [`POST ${K}/proposals/prop-1/change`]: () => {
        current = {
          ...proposal,
          offer_id: "offer-2",
          total_ex_vat: "60.00",
          vat: "8.40",
          expected_total: "68.40",
          lines: [{ ...proposal.lines[0], quantity: "30", total: "60.00", why: "Quantity set by Demo approver." }],
        };
        return current;
      },
      [`POST ${K}/proposals/prop-1/approve`]: () => {
        current = { ...current, status: "APPROVED", order_id: "ord-1" };
        return { proposal_id: "prop-1", ...placedOrder, expected_total: "68.40" };
      },
      [`GET ${K}/orders/ord-1`]: () => ({ ...placedOrder, expected_total: "68.40" }),
    });
    renderApp("/approvals", createHttpApi("/api"));

    await user.click(await screen.findByRole("button", { name: /^Inspect/ }));
    const quantity = await screen.findByLabelText(/Quantity for 900001/);
    await user.clear(quantity);
    await user.type(quantity, "30");
    await user.click(screen.getByRole("button", { name: "Update 900001" }));

    expect(await screen.findByRole("button", { name: /Approve €68\.40/ })).toBeEnabled();
    const change = calls.find((call) => call.route === `POST ${K}/proposals/prop-1/change`);
    expect(change?.body).toEqual({
      lines: [{ product_id: "900001", quantity: "30" }],
      idempotency_key: expect.stringMatching(/^web-change:/),
    });

    await user.click(screen.getByRole("button", { name: /Approve €68\.40/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €68.40" }));

    expect(await screen.findByTestId("approval-toast")).toHaveTextContent(
      "Approved and recorded: €68.40 in all (€60.00 ex VAT). Nothing is sent to the supplier.",
    );
    const approve = calls.find((call) => call.route === `POST ${K}/proposals/prop-1/approve`);
    expect(approve?.body).toMatchObject({ expected_total: "68.40" });
  });

  it("marks a screen that still runs on the mock, and only on the gateway", async () => {
    gateway({
      "GET /api/v1/me": () => ({ kind: "human", name: "Demo approver", role: "approver", can_approve: true }),
    });
    // Every screen in SCREEN_DATA is on the gateway now: take one method out of `live` to see the mark.
    const api = createHttpApi("/api");
    const live = new Set(api.live);
    live.delete("searchProducts");
    renderApp("/catalog", { ...api, live });
    expect(await screen.findByText("Sample data")).toBeVisible();
  });

  it("shows the Catalog page on the gateway without the Sample data mark", async () => {
    gateway({
      "GET /api/v1/me": () => ({ kind: "human", name: "Demo approver", role: "approver", can_approve: true }),
    });
    renderApp("/catalog", createHttpApi("/api"));
    expect(await screen.findByText("Atlas Search")).toBeVisible();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });

  it("gives a real Set for live, so the Trust page shows the gateway's error instead of crashing", async () => {
    expect(createHttpApi("/api").live).toBeInstanceOf(Set);
    gateway({ [`GET ${K}/audit/chain?limit=5`]: () => error(503, "NOT_SERVED") });
    renderApp("/trust", createHttpApi("/api"));
    expect(await screen.findByRole("alert", {}, { timeout: 5000 })).toHaveTextContent("NOT_SERVED");
    expect(screen.getByText("Audit log stored in MongoDB Atlas")).toBeVisible();
  });

  it("shows the gateway's own stock without the mark, with on order unknown and not zero", async () => {
    gateway({
      [`GET ${K}/stock`]: () => ({
        as_of: "2026-11-14T10:00:00+02:00",
        items: [
          { product_id: "900001", unit: "L", on_hand: "12", counted_at: null, on_order: "0", on_order_known: false },
        ],
      }),
    });
    renderApp("/stock", createHttpApi("/api"));
    expect((await screen.findAllByText("12 l")).length).toBeGreaterThan(0);
    expect(screen.getAllByTitle("Open orders are not counted in kitchen units yet").length).toBeGreaterThan(0);
    expect(screen.queryByText("0 l")).not.toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });

  it("does not mark anything on the mock", async () => {
    renderApp("/stock");
    expect(await screen.findByRole("heading", { name: "Stock count" })).toBeVisible();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });
});
