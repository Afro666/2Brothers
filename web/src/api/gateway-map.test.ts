import { describe, expect, it } from "vitest";

import { mapAddable, mapApproval, mapAudit, mapOrder, mapPermissions, mapRecalls } from "@/api/gateway-map";
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
    ["PENDING", "IN_PROGRESS"],
    ["APPROVING", "IN_PROGRESS"],
    ["COMMITTING", "IN_PROGRESS"],
    ["BLOCKED_BY_RECALL", "BLOCKED_BY_RECALL"],
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

describe("mapRecalls", () => {
  const body = {
    last_check: {
      checked_at: "2026-11-14T04:30:00+00:00",
      checked_by: "chef@example.test",
      source: "recording",
      live_error: "NO_KEY",
      fetched_at: "2026-11-13T22:17:51+00:00",
      details_fetched_at: "2026-11-13T22:18:51+00:00",
      via: "Context.dev /v1/web/scrape (json)",
      notices_scanned: 38,
      scanned_since: "2026-03-02",
      notices_listed: null,
      notices_unread: null,
    },
    alerts: [
      {
        event_id: "recall-example",
        product_id: "100001",
        product_name: "Example ingredient",
        match: "possible",
        why: "Example match reason",
        where: ["on the open purchase proposal"],
        recall: {
          url: "https://www.ruokavirasto.fi/example-notice",
          date: "2026-03-06",
          title: "Example notice",
          reason: "Example hazard",
          action: "Example action",
          recalled_product: "Example recalled product",
          brand: "Example brand",
          gtin: null,
          package_size: "500 g",
          lot: "Example lot",
        },
        next_step: "Check the example packs.",
        replacement_proposal: [{ product_id: "100002", name: "Example alternative", brand: "Other brand" }],
        detected_at: "2026-11-14T04:30:00+00:00",
        status: "dismissed",
        dismissed_by: "chef@example.test",
        dismissed_at: "2026-11-14T05:00:00+00:00",
        dismiss_reason: "The example lot is not held here.",
        proposals: [
          {
            proposal_id: "held-example",
            status: "BLOCKED_BY_RECALL",
            recall_replan_error: null,
            replacement: {
              proposal_id: "replacement-example",
              status: "READY",
              expected_total: "56.75",
              currency: "EUR",
              lines: [{ product_id: "100002", product_name: "Example alternative", quantity: "1.5", unit: "KG" }],
            },
          },
          {
            proposal_id: "second-held-example",
            status: "BLOCKED_BY_RECALL",
            recall_replan_error: "NO_SAFE_REPLACEMENT",
            replacement: null,
          },
        ],
      },
    ],
  };

  it("maps the check and one camel-case alert per held proposal with decimal strings as numbers", () => {
    const result = mapRecalls(body);
    expect(result.lastCheck).toEqual({
      checkedAt: "2026-11-14T04:30:00+00:00",
      checkedBy: "chef@example.test",
      source: "recording",
      liveError: "NO_KEY",
      fetchedAt: "2026-11-13T22:17:51+00:00",
      detailsFetchedAt: "2026-11-13T22:18:51+00:00",
      via: "Context.dev /v1/web/scrape (json)",
      noticesScanned: 38,
      scannedSince: "2026-03-02",
      noticesListed: null,
      noticesUnread: null,
    });
    expect(result.alerts).toHaveLength(2);
    expect(result.alerts[0]).toMatchObject({
      eventId: "recall-example",
      productId: "100001",
      orderId: "held-example",
      proposalStatus: "BLOCKED_BY_RECALL",
      lineStatus: "BLOCKED_BY_RECALL",
      status: "dismissed",
      dismissedBy: "chef@example.test",
      dismissedAt: "2026-11-14T05:00:00+00:00",
      dismissReason: "The example lot is not held here.",
      replacement: {
        orderId: "replacement-example",
        status: "READY",
        expectedTotal: 56.75,
        lines: [{ productId: "100002", productName: "Example alternative", quantity: 1.5, unit: "KG" }],
      },
      replacementIdeas: [{ productId: "100002", name: "Example alternative", brand: "Other brand" }],
    });
    expect(result.alerts[0].recall).toMatchObject({
      recalledProduct: "Example recalled product",
      packageSize: "500 g",
      title: "Example notice",
      lot: "Example lot",
    });
    expect(result.alerts[1]).toMatchObject({
      eventId: "recall-example",
      orderId: "second-held-example",
      replacement: null,
      replanError: "NO_SAFE_REPLACEMENT",
    });
  });

  it("keeps an alert without a proposal, derives review warnings, and distinguishes an empty first state", () => {
    const alert = { ...body.alerts[0], match: "review", status: "active", proposals: [] };
    const result = mapRecalls({ last_check: null, alerts: [alert] });
    expect(result.lastCheck).toBeNull();
    expect(result.alerts).toHaveLength(1);
    expect(result.alerts[0]).toMatchObject({
      orderId: null,
      proposalStatus: "UNKNOWN",
      lineStatus: "WARNING",
      replacement: null,
      status: "active",
    });
  });

  it.each(["javascript:alert(1)", "data:text/html,<script>alert(1)</script>", "/recalls/example-notice"])(
    "maps an unsafe or relative source URL %s to null",
    (url) => {
      const alert = { ...body.alerts[0], recall: { ...body.alerts[0].recall, url } };
      const result = mapRecalls({ ...body, alerts: [alert] });
      expect(result.alerts[0].recall.url).toBeNull();
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
        summary: "Buyer is asking for an offer",
        reason: 'product_ids: ["900001"]; requested_date: 2026-11-20',
      },
      {
        id: "ev-2",
        at: null,
        orderId: undefined,
        kind: "approval",
        actor: "agent",
        summary: "Buyer asked for approval: it failed",
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

  it("maps a refused 403 to the 'refused' kind with code and path; a token is not a person", () => {
    const refused = {
      seq: 9,
      event_id: "ev-9",
      kind: "refused",
      actor: "token:pos",
      at: "2026-11-14T08:00:00+00:00",
      code: "SCOPE_MISSING",
      method: "POST",
      path: "/kitchens/k-1/orders",
    };
    expect(mapAudit([refused])).toEqual([
      {
        id: "ev-9",
        at: "2026-11-14T08:00:00+00:00",
        orderId: undefined,
        kind: "refused",
        actor: "system",
        summary: "Refused: the gateway said no (403)",
        reason: "code: SCOPE_MISSING; method: POST; path: /kitchens/k-1/orders",
      },
    ]);
    expect(mapAudit([{ ...refused, actor: "buyer-agent" }])[0].actor).toBe("agent");
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
