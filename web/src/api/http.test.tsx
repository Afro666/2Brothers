import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
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
    const answer = routes[route] ? routes[route](body) : error(404, "NO_ROUTE");
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
        "getApproval",
        "getForecastAccuracy",
        "getOrder",
        "getPermissions",
        "listAddableProducts",
        "listApprovals",
        "listAudit",
        "listOrders",
        "reject",
        "submitChefRequest",
      ].sort(),
    );
    expect((await api.getStock()).length).toBeGreaterThan(0);
    expect((await api.listSuppliers()).length).toBeGreaterThan(0);
    expect(calls).toEqual([]);
    await expect(
      api.changeProposal("prop-1", { type: "REMOVE_LINE", productId: "900001" }, "human"),
    ).rejects.toMatchObject({
      code: "NOT_SERVED",
    });
    await expect(api.lookupKitchenBrand({ website: "example.fi" })).rejects.toMatchObject({ code: "NOT_SERVED" });
    expect(api.chooseOption).toBeUndefined();
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
  it("shows the real proposal read-only and, when the total moved, the new total before asking again", async () => {
    // As deployed: with the gateway Api, the Api-backed inbox is the live one.
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    const user = userEvent.setup();
    let current = proposal;
    gateway({
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
    gateway({});
    renderApp("/stock", createHttpApi("/api"));
    expect(await screen.findByText("Sample data")).toBeVisible();
  });

  it("does not mark anything on the mock", async () => {
    renderApp("/stock");
    expect(await screen.findByRole("heading", { name: "Stock count" })).toBeVisible();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });
});
