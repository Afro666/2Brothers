import { describe, expect, it } from "vitest";

import { mapAddable, mapApproval, mapAudit, mapOrder, mapPermissions } from "@/api/gateway-map";
import { addable, auditEvents, placedOrder, proposal } from "@/test/gateway-fixtures";

describe("mapPermissions", () => {
  it("maps the gateway matrix, keeps the rule, and shows an unknown audit kind as other", () => {
    const body = {
      alone: [{ action: "Search the catalog", audit_kind: "search", rule: "Read-only search." }],
      person: [{ action: "Every order", audit_kind: "approval", rule: "An approver says yes." }],
      never: [
        { action: "Place an order nobody approved", audit_kind: "order", rule: "403 NEEDS_APPROVAL." },
        { action: "Act for another kitchen", audit_kind: "token_created", rule: "403 KITCHEN_SCOPE." },
      ],
    };
    expect(mapPermissions(body)).toEqual({
      alone: [{ action: "Search the catalog", auditKind: "search", rule: "Read-only search." }],
      person: [{ action: "Every order", auditKind: "approval", rule: "An approver says yes." }],
      never: [
        { action: "Place an order nobody approved", auditKind: "order", rule: "403 NEEDS_APPROVAL." },
        { action: "Act for another kitchen", auditKind: "other", rule: "403 KITCHEN_SCOPE." },
      ],
    });
  });

  it("refuses a body without the three groups", () => {
    expect(() => mapPermissions({ alone: [] })).toThrow(/unexpected shape/);
  });
});

describe("mapApproval", () => {
  it("maps a proposal to the approval card, with who asked and when from the audit log", () => {
    expect(mapApproval(proposal, auditEvents)).toEqual({
      id: "prop-1",
      orderId: "prop-1",
      requestedBy: "buyer-agent",
      createdAt: "2026-11-14T10:00:00+00:00",
      summary: "50 L oat drink by Friday",
      lineCount: 1,
      deliveryDate: "2026-11-20",
      totalExVat: 80,
      totalInclVat: 91.2,
      reasons: [
        { rule: "10 L of the request cannot be covered for this date.", detail: "" },
        { rule: "OVER_BUDGET_WARNING", detail: "A warning. It does not block the order.", warning: true },
      ],
      status: "PENDING",
      options: [],
    });
  });

  it("carries the gateway's substitute baskets as options, the proposal's own offer marked chosen", () => {
    const basket = {
      tier: "better",
      source: "supplier",
      offer_id: "offer-1",
      expected_total: "91.20",
      currency: "EUR",
      lines: proposal.lines,
      why: "Supplier-linked substitute sized by the engine.",
      requires_chef_approval: true,
      stock_confirmed: true,
      allergen_data_known: false,
    };
    expect(mapApproval({ ...proposal, substitute_options: [basket] }).options).toEqual([
      expect.objectContaining({
        id: "offer-1",
        tier: "better",
        totalInclVat: 91.2,
        stockConfirmed: true,
        chosen: true,
      }),
    ]);
  });

  it("keeps who and when unknown without a creation event, and always gives a reason", () => {
    const bare = { ...proposal, request: { ...proposal.request, text: "" }, mandate: { verdict: "NEEDS_APPROVAL" } };
    const approval = mapApproval(bare);
    expect(approval).toMatchObject({ requestedBy: "unknown", createdAt: null, summary: "50 L" });
    expect(approval.reasons).toEqual([expect.objectContaining({ rule: "A person approves every order" })]);
  });

  it.each([
    ["READY", "PENDING"],
    ["APPROVING", "PENDING"],
    ["APPROVED", "APPROVED"],
    ["REJECTED", "REJECTED"],
    ["EXPIRED", "REJECTED"],
  ])("reads proposal status %s as %s", (status, expected) => {
    expect(mapApproval({ ...proposal, status }).status).toBe(expected);
  });

  it.each([{ expected_total: 91.2 }, { total_ex_vat: null }, { lines: "none" }, { request: null }])(
    "refuses a malformed proposal %j",
    (broken) => {
      expect(() => mapApproval({ ...proposal, ...broken })).toThrow(
        expect.objectContaining({ code: "INVALID_RESPONSE" }),
      );
    },
  );
});

describe("mapOrder", () => {
  it("maps a waiting proposal; what the gateway does not send stays unknown, never zero", () => {
    const order = mapOrder(proposal, null);
    expect(order).toMatchObject({
      id: "prop-1",
      status: "NEEDS_APPROVAL",
      urgency: "UNKNOWN",
      deliveryDate: "2026-11-20",
      totalExVat: 80,
      totalInclVat: 91.2,
      mov: null,
    });
    expect(order.lines).toHaveLength(1);
    expect(order.lines[0]).toMatchObject({ quantity: 40, why: "40 ST of oat drink = 40 L, confirmed in stock." });
    expect(order.lines[0].product).toMatchObject({
      id: "900001",
      names: { en: "900001" },
      salesUnit: "ST",
      baseUnitsPerSalesUnit: null,
      allergens: null,
    });
    expect(order.lines[0].offer).toMatchObject({
      priceExVat: 2,
      taxRatePercent: null,
      availableAmount: null,
      stockConfirmed: true,
      closingTime: null,
      availableDate: null,
    });
  });

  it.each([true, undefined, "false"])("treats unknown_stock %j as not confirmed", (unknown_stock) => {
    const order = mapOrder({ ...proposal, lines: [{ ...proposal.lines[0], unknown_stock }] }, null);
    expect(order.lines[0].offer.stockConfirmed).toBe(false);
  });

  it("derives the free-delivery threshold from the gap when the supplier's terms are known", () => {
    expect(mapOrder({ ...proposal, mov_gap: "20.00", delivery_fee: "25.00" }, null).mov).toEqual({
      threshold: 100,
      current: 80,
      deliveryFee: 25,
    });
  });

  it.each([
    ["CONFIRMED", "PLACED"],
    ["NOT_SENT", "NOT_SENT"],
    ["SENT_READ_FAILED", "SENT_READ_FAILED"],
    ["UNCONFIRMED", "UNCONFIRMED"],
    [null, "UNCONFIRMED"],
    ["SOMETHING_NEW", "UNCONFIRMED"],
  ])("reads order outcome %j as %s", (outcome, status) => {
    expect(mapOrder(proposal, { ...placedOrder, outcome })).toMatchObject({ id: "ord-1", status });
  });

  it("never shows an approved proposal without its order row as placed", () => {
    expect(mapOrder({ ...proposal, status: "APPROVED" }, null).status).toBe("UNCONFIRMED");
    expect(mapOrder({ ...proposal, status: "REJECTED" }, null).status).toBe("REFUSED");
  });

  it("keeps an order without its proposal: date, ex-VAT total and delivery terms unknown", () => {
    const order = mapOrder(null, placedOrder);
    expect(order).toMatchObject({
      id: "ord-1",
      status: "PLACED",
      deliveryDate: null,
      totalExVat: null,
      totalInclVat: 91.2,
      mov: null,
    });
    expect(order.lines[0]).toMatchObject({ quantity: 40, why: "Not recorded with the order." });
  });
});

describe("mapAudit", () => {
  it("maps agent tool events and gateway events; a missing time stays unknown", () => {
    expect(mapAudit(auditEvents)).toEqual([
      {
        id: "ev-1",
        at: null,
        orderId: undefined,
        kind: "offer",
        actor: "agent",
        summary: "Buyer called get_offer",
        reason: 'product_ids: ["900001"]; requested_date: 2026-11-20',
      },
      {
        id: "ev-2",
        at: null,
        orderId: undefined,
        kind: "approval",
        actor: "agent",
        summary: "request_approval failed",
        reason: "error: Rejected by buyer policy; reason_code: POLICY_VIOLATION",
      },
      {
        id: "ev-3",
        at: "2026-11-14T10:00:00+00:00",
        orderId: "prop-1",
        kind: "approval",
        actor: "agent",
        summary: "Approval requested",
        reason: "expected_total: 91.20",
      },
      {
        id: "ev-4",
        at: "2026-11-14T10:05:00+00:00",
        orderId: "ord-1",
        kind: "order",
        actor: "chef",
        summary: "Order placed",
        reason: "expected_total: 91.20",
      },
      {
        id: "ev-5",
        at: "2026-11-14T10:06:00+00:00",
        orderId: undefined,
        kind: "other",
        actor: "human",
        summary: "something_new",
        reason: "No details recorded.",
      },
    ]);
  });

  it("gives an order its own steps and those of the proposal that placed it", () => {
    expect(mapAudit(auditEvents, "ord-1").map((event) => event.id)).toEqual(["ev-3", "ev-4"]);
    expect(mapAudit(auditEvents, "prop-1").map((event) => event.id)).toEqual(["ev-3", "ev-4"]);
    expect(mapAudit(auditEvents, "ord-none")).toEqual([]);
  });
});

describe("mapAddable", () => {
  it("keeps the rows that can be added; a stock that was not counted stays null", () => {
    const [row, ...rest] = mapAddable(addable, "2026-11-20");
    expect(rest).toEqual([]);
    expect(row).toMatchObject({ onHand: null, onOrder: 0, suggestedQuantity: 12 });
    expect(row.product).toMatchObject({ id: "900002", names: { en: "Oat cream 1 L" }, salesUnit: "ST" });
    expect(row.offer).toMatchObject({ priceExVat: 3.1, requestedDate: "2026-11-20", stockConfirmed: false });
  });
});
