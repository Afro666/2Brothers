import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpApi, SIGNED_OUT_EVENT } from "@/api/http";
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

const inbox = (row = proposal) => ({
  [`GET ${K}/proposals`]: () => ({ proposals: [row] }),
  [`GET ${K}/proposals/prop-1`]: () => row,
  [`GET ${K}/audit`]: () => ({ events: auditEvents }),
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
        "getApproval",
        "getForecastAccuracy",
        "getOrder",
        "getPermissions",
        "getSession",
        "listAddableProducts",
        "listApprovals",
        "listAudit",
        "listOrders",
        "reject",
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
        "getDemand",
        "getSharing",
        "setSharing",
        "getSupplierDemand",
        "getKitchenSettings",
        "saveKitchenSettings",
        "getAutoApproveLearning",
        // Standing-order drift (store/drift.py behind the gateway).
        "getDrift",
        "getSupplierDrift",
      ].sort(),
    );
    expect((await api.getMandate()).restaurant).toBeTruthy();
    expect((await api.searchProducts("milk")).length).toBeGreaterThan(0);
    expect(calls).toEqual([]);
    await expect(
      api.changeProposal("prop-1", { type: "REMOVE_LINE", productId: "900001" }, "human"),
    ).rejects.toMatchObject({
      code: "NOT_SERVED",
    });
    await expect(api.lookupKitchenBrand({ website: "example.fi" })).rejects.toMatchObject({ code: "NOT_SERVED" });
    expect(api.chooseOption).toBeUndefined();
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
    await expect(api.lookupKitchenBrand({ website: "example.fi" })).rejects.toMatchObject({ code: "NOT_SERVED" });
  });

  it("approves the exact total the person read, as that person, with no token from the browser", async () => {
    const approved = { ...proposal, status: "APPROVED", order_id: "ord-1" };
    const calls = gateway({
      ...inbox(approved),
      [`POST ${K}/proposals/prop-1/approve`]: () => ({ proposal_id: "prop-1", ...placedOrder }),
    });
    const result = await createHttpApi("/api").approve(
      { approvalId: "prop-1", expectedTotalExVat: 80, expectedTotalInclVat: 91.2 },
      "chef",
    );
    expect(result.status).toBe("APPROVED");
    expect(calls[0].route).toBe(`POST ${K}/proposals/prop-1/approve`);
    expect(calls[0].body).toEqual({
      expected_total: "91.20",
      blocks: [{ supplier_id: "sup-valio", expected_total: "91.20" }],
      idempotency_key: "web-approve:prop-1:91.20",
    });
    expect(calls[0].headers).toMatchObject({ "X-User": "chef" });
    expect(calls.every((call) => !("Authorization" in call.headers))).toBe(true);
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
      canApprove: false,
    });
    await api.approve({ approvalId: "prop-1", expectedTotalExVat: 80, expectedTotalInclVat: 91.2 }, "human");
    const approvalCall = calls.find((call) => call.route.includes("/approve"));
    expect(approvalCall?.headers).not.toHaveProperty("X-User");
    expect(calls[0].body).toEqual({ email: "buyer@example.com", password: "demo-kitchen-2026" });
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
    await api.approve({ approvalId: "prop-1", expectedTotalExVat: 80, expectedTotalInclVat: 91.2 }, "chef");

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
      [`GET ${K}/proposals/ord-1`]: () => error(404, "PROPOSAL_NOT_FOUND"),
      [`GET ${K}/orders/ord-1`]: () => placedOrder,
      [`GET ${K}/proposals`]: () => ({ proposals: [{ ...proposal, status: "APPROVED", order_id: "ord-1" }] }),
    });
    const api = createHttpApi("/api");
    expect(await api.getOrder("prop-1")).toMatchObject({ id: "prop-1", status: "NEEDS_APPROVAL" });
    expect(await api.getOrder("ord-1")).toMatchObject({ id: "ord-1", status: "PLACED", totalExVat: 80 });
    await expect(api.getOrder("nope")).rejects.toMatchObject({ code: "NO_ROUTE" });
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

  it("asks the Buyer once per request: the key survives a failure", async () => {
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
    const posts = calls.filter((call) => call.route.startsWith("POST"));
    expect(posts[0].body).toMatchObject({ text: "50 L oat drink by Friday", requested_date: "2026-11-20" });
    expect(posts[0].body.idempotency_key).toBeTruthy();
    expect(posts[1].body.idempotency_key).toBe(posts[0].body.idempotency_key);
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

  it("shows the real proposal read-only and, when the total moved, the new total before asking again", async () => {
    // As deployed: with the gateway Api, the Api-backed inbox is the live one.
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    const user = userEvent.setup();
    let current = proposal;
    gateway({
      "GET /api/v1/me": () => ({ kind: "human", name: "Demo approver", role: "approver", can_approve: true }),
      [`GET ${K}/proposals`]: () => ({ proposals: [current] }),
      [`GET ${K}/proposals/prop-1`]: () => current,
      [`GET ${K}/audit`]: () => ({ events: auditEvents }),
      [`POST ${K}/proposals/prop-1/approve`]: () => {
        current = { ...proposal, total_ex_vat: "83.33", expected_total: "95.00" };
        return error(409, "TOTAL_MISMATCH", { expected_total: "95.00" });
      },
    });
    renderApp("/approvals", createHttpApi("/api"));

    expect(await screen.findByText("50 L oat drink by Friday")).toBeVisible();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Show order lines" }));
    expect(screen.getAllByText("confirmed").length).toBeGreaterThan(0);
    expect(screen.getByText(/Free-delivery threshold and delivery fee unknown/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /^Update/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Approve €91\.20 incl VAT/ }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €91.20" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The total is now €95.00. Nothing was sent.");
    expect(await screen.findByRole("button", { name: /Approve €95\.00 incl VAT/ })).toBeEnabled();
    expect(screen.getByRole("heading", { name: "Waiting for you (1)" })).toBeVisible();
  });

  it("marks a screen that still runs on the mock, and only on the gateway", async () => {
    gateway({
      "GET /api/v1/me": () => ({ kind: "human", name: "Demo approver", role: "approver", can_approve: true }),
    });
    renderApp("/catalog", createHttpApi("/api"));
    expect(await screen.findByText("Sample data")).toBeVisible();
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
    expect((await screen.findAllByText("12 L")).length).toBeGreaterThan(0);
    expect(screen.getAllByTitle("Open orders are not counted in kitchen units yet").length).toBeGreaterThan(0);
    expect(screen.queryByText("0 L")).not.toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });

  it("does not mark anything on the mock", async () => {
    renderApp("/stock");
    expect(await screen.findByRole("heading", { name: "Stock count" })).toBeVisible();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });
});
