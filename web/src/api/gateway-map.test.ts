import { describe, expect, it } from "vitest";

import { askedBy, mapAddable, mapApproval, mapAudit, mapOrder, mapPermissions, mapRecalls } from "@/api/gateway-map";
import { translate } from "@/lib/i18n";
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
      approvalRef: "appr-1",
      orderId: "prop-1",
      requestedBy: "the Buyer agent",
      createdAt: "2026-11-14T10:00:00+00:00",
      summary: "50 L oat drink by Friday",
      lineCount: 1,
      deliveryDate: "2026-11-20",
      totalExVat: 80,
      totalInclVat: 91.2,
      reasons: [
        { rule: "10 L of the request cannot be covered for this date.", detail: "" },
        {
          rule: "The total is above your kitchen's budget warning.",
          detail: "A warning only. It does not block the order.",
          warning: true,
        },
      ],
      suppliersToConfirm: [],
      blockDeliveryFees: [],
      rejectReason: null,
      cutoffs: [{ closingTime: null, supplierName: null }],
      status: "PENDING",
      options: [],
      modelTrace: null, // no model_trace on this proposal (#1197)
    });
  });

  it("lists non-Valio blocks with unknown stock whose supplier must confirm", () => {
    const unknown = { ...proposal.lines[0], unknown_stock: true };
    const confirmed = { ...proposal.lines[0], unknown_stock: false };
    const result = mapApproval({
      ...proposal,
      blocks: [
        { supplier_id: "sup-bakery", name: "Leipomo Demo", lines: [unknown] },
        { supplier_id: "sup-nameless", lines: [{ ...confirmed, unknown_stock: true }] },
        { supplier_id: "sup-valio", name: "Valio Aimo", lines: [unknown] },
        { supplier_id: "sup-confirmed", name: "Confirmed Supplier", lines: [confirmed] },
      ],
    });
    expect(result.suppliersToConfirm).toEqual([
      { supplierId: "sup-bakery", name: "Leipomo Demo", count: 1 },
      { supplierId: "sup-nameless", name: "sup-nameless", count: 1 },
    ]);
  });

  it("counts each other supplier's unconfirmed lines (#1865)", () => {
    const unknown = { ...proposal.lines[0], unknown_stock: true };
    const confirmed = { ...proposal.lines[0], unknown_stock: false };
    const result = mapApproval({
      ...proposal,
      blocks: [{ supplier_id: "sup-fish", name: "Baltic Catch", lines: [unknown, confirmed, unknown] }],
    });
    expect(result.suppliersToConfirm).toEqual([{ supplierId: "sup-fish", name: "Baltic Catch", count: 2 }]);
  });

  it("counts Valio's own block's unknown-stock lines, and none without blocks (#1899)", () => {
    const unknown = { ...proposal.lines[0], unknown_stock: true };
    const confirmed = { ...proposal.lines[0], unknown_stock: false };
    const blocks = [
      { supplier_id: "sup-valio", name: "Valio Aimo", lines: [unknown, confirmed, unknown] },
      { supplier_id: "sup-fish", name: "Baltic Catch", lines: [unknown] },
    ];
    expect(mapApproval({ ...proposal, blocks }).valioToConfirm).toBe(2);
    expect(mapApproval({ ...proposal, blocks: [blocks[1]] }).valioToConfirm).toBe(0);
    expect(mapApproval(proposal).valioToConfirm).toBeUndefined();
  });

  it("shows the gateway's must-confirm sentence as it is (Valio, 14 Nov)", () => {
    const sentence = "Valio must confirm stock for: Valio Eila 3 % 1 L.";
    const result = mapApproval({ ...proposal, mandate: { ...proposal.mandate, reasons: [sentence] } });
    expect(result.reasons.map((reason) => reason.rule)).toContain(sentence);
  });

  it("maps each line's closing time and the name of its supplier block", () => {
    const closingTime = "2026-11-15T17:00:00+02:00";
    const result = mapApproval({
      ...proposal,
      lines: [{ ...proposal.lines[0], closing_time: closingTime }],
      blocks: [{ supplier_id: "sup-valio", name: "Valio Aimo", lines: proposal.lines }],
    });
    expect(result.cutoffs).toEqual([{ closingTime, supplierName: "Valio" }]);
  });

  it("uses product names and plain sentences for known reason codes, leaving unknown codes alone", () => {
    const result = mapApproval({
      ...proposal,
      lines: [{ ...proposal.lines[0], product_name: "Oat drink 1 L" }],
      excluded: [{ product_id: "461332", name: "Coffee 500 g", reason: "BLOCKED_BY_RECALL" }],
      mandate: {
        ...proposal.mandate,
        warnings: [],
        reasons: [
          "461332: BLOCKED_BY_RECALL",
          "900001: order cut-off has passed for this delivery",
          "900001: pack size unknown; check the pack",
          "CLOSING_PASSED",
          "STOCK_UNKNOWN",
          "PACK_SIZE_UNKNOWN",
          "NEW_GATEWAY_REASON",
          "777777: NEW_LINE_CODE",
        ],
      },
    });
    expect(result.reasons.map(({ rule, detail }) => ({ rule, detail }))).toEqual([
      { rule: "Coffee 500 g: Blocked by a recall. A product on this order matches a food recall. It cannot be approved.", detail: "" },
      { rule: "Oat drink 1 L: order cut-off has passed for this delivery", detail: "" },
      { rule: "Oat drink 1 L: pack size unknown; check the pack", detail: "" },
      // A bare known code is a title and a detail, as CHECK_CODES are, so both have Finnish.
      { rule: "Order cut-off passed", detail: "The supplier's cut-off for this delivery date has passed." },
      { rule: "Stock not confirmed", detail: "The supplier does not report stock for some lines. They confirm it later." },
      { rule: "PACK_SIZE_UNKNOWN", detail: "" },
      { rule: "NEW_GATEWAY_REASON", detail: "" },
      // #1142: a code after a product id is still put in words, even an unknown one.
      { rule: "777777: New line code. The gateway flagged this. Check the order before you approve.", detail: "" },
    ]);
  });

  it("uses no supplier confirmations when blocks are missing", () => {
    expect(mapApproval(proposal).suppliersToConfirm).toEqual([]);
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
    expect(approval).toMatchObject({ requestedBy: null, createdAt: null, summary: "50 L" });
    expect(approval.reasons).toEqual([expect.objectContaining({ rule: "A person approves every order" })]);
  });

  it("maps the gateway's line names, Finnish names and brands onto the option lines (#1130)", () => {
    const named = { product_id: "462775", quantity: "51", unit: "ST", why: "x", unknown_stock: false,
      product_name: "Valio Eila milk 1 L", product_name_fi: "Valio Eila maito 1 l", brand: "Valio" };
    const approval = mapApproval({
      ...proposal,
      lines: [named],
      mandate: { verdict: "NEEDS_APPROVAL", reasons: ["Valio Eila milk 1 L (462775): ALLERGEN_RULE: the kitchen excludes AN"] },
      substitute_options: [{
        tier: "good", source: "confirmed", offer_id: "offer-2", expected_total: "10.00", currency: "EUR",
        lines: [named, { ...named, product_id: "463335", product_name: null, product_name_fi: null, brand: null }],
        why: "Confirmed stock only.", requires_chef_approval: true, stock_confirmed: true,
      }],
    });
    expect(approval.options?.[0]?.lines.map((line) => [line.productName, line.productNameFi, line.brand])).toEqual([
      ["Valio Eila milk 1 L", "Valio Eila maito 1 l", "Valio"],
      [null, null, null],
    ]);
    expect(approval.reasons[0].rule.startsWith("Valio Eila milk 1 L (462775): ")).toBe(true);
    expect(approval.reasons[0].rule).not.toContain("ALLERGEN_RULE");
  });

  it("explains why confirmed stock has a high certainty premium", () => {
    const withWarning = {
      ...proposal,
      mandate: { verdict: "NEEDS_APPROVAL", warnings: ["CERTAINTY_PREMIUM_HIGH"] },
    };
    expect(mapApproval(withWarning).reasons).toContainEqual({
      rule: "Confirmed stock costs more than your kitchen's allowed premium over the cheapest option, but it is needed to fill the order.",
      detail: "A warning only. It does not block the order.",
      warning: true,
    });
  });

  it("turns an unknown warning code into words, never the raw code (#1142)", () => {
    const withWarning = {
      ...proposal,
      mandate: { verdict: "NEEDS_APPROVAL", warnings: ["NEW_GATEWAY_WARNING"] },
    };
    expect(mapApproval(withWarning).reasons).toContainEqual({
      rule: "New gateway warning",
      detail: "A warning. It does not block the order.",
      warning: true,
    });
  });

  it("names an API token and the chef in words, not raw actor codes", () => {
    expect(askedBy("token:x", {})).toBe("an API client");
    expect(askedBy("token:demo", {})?.startsWith("token:")).toBe(false);
    expect(askedBy("chef", {})).toBe("the chef");
  });

  it("names Valio's selling agent for a supplier offer proposal", () => {
    const offer = { ...proposal, request: { ...proposal.request, text: "Offer from Valio Aimo: Flounder in place of Salmon" } };
    expect(mapApproval(offer).requestedBy).toBe("Valio's selling agent");
    expect(
      mapApproval(proposal, [{ kind: "proposal_created", proposal_id: "prop-1", actor: "supplier:sup-valio" }]).requestedBy,
    ).toBe("Valio's selling agent");
  });

  it("keeps a person's name and puts no raw code in a gateway reason", () => {
    const refused = {
      ...proposal,
      mandate: { verdict: "REFUSED", reasons: ["472710: ALLERGEN_RULE: the kitchen excludes AN"] },
    };
    const approval = mapApproval(refused, [{ kind: "proposal_created", proposal_id: "prop-1", actor: "chef@kitchen.example" }]);
    expect(approval.requestedBy).toBe("chef@kitchen.example");
    expect(approval.reasons[0].rule).toBe("472710: Excluded allergen: the kitchen excludes AN");
    const named = mapApproval({
      ...refused,
      lines: [{ ...proposal.lines[0], product_id: "472710", product_name: "Milk 1 L" }],
    });
    expect(named.reasons[0].rule).toBe("Milk 1 L: Excluded allergen: the kitchen excludes AN");
  });

  it("lists ALLERGEN_DATA_MISSING under what to check, from a line or the mandate", () => {
    const check = {
      rule: "Allergen data missing",
      detail: "The catalog has no allergen data for one or more products. Check the label.",
    };
    const onLine = { ...proposal, lines: [{ ...proposal.lines[0], reason_codes: ["ALLERGEN_DATA_MISSING"] }] };
    expect(mapApproval(onLine).reasons).toContainEqual(check);
    const onMandate = { ...proposal, mandate: { verdict: "NEEDS_APPROVAL", reason_codes: ["ALLERGEN_DATA_MISSING"] } };
    expect(mapApproval(onMandate).reasons).toEqual([check]);
    expect(mapApproval(proposal).reasons).not.toContainEqual(check);
  });

  it("uses null when the gateway has no approval id", () => {
    expect(mapApproval({ ...proposal, approval_id: null }).approvalRef).toBeNull();
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
  it("keeps the gateway's shortfall and unit for the partial-fill note", () => {
    expect(mapOrder(proposal, placedOrder).shortfall).toEqual({ amount: 10, unit: "L" });
    expect(mapOrder({ ...proposal, shortfall: "0" }, null).shortfall).toBeNull();
    expect(mapOrder({ ...proposal, shortfall: null }, null).shortfall).toBeNull();
  });

  it("carries the request text and the placed order's time, so repeated orders differ", () => {
    const order = mapOrder(proposal, placedOrder);
    expect(order.requestText).toBe("50 L oat drink by Friday");
    expect(order.createdAt).toBe("2026-11-14T10:05:00+00:00");
  });

  it("leaves the request text and time null when the gateway does not say them", () => {
    const blank = { ...proposal, request: { ...proposal.request, text: "  " } };
    expect(mapOrder(blank, null)).toMatchObject({ requestText: null, createdAt: null });
    const { created_at: _created, ...noTime } = placedOrder;
    expect(mapOrder(null, noTime).createdAt).toBeNull();
    expect(mapOrder(null, placedOrder).requestText).toBeNull();
  });

  it("maps the suppliers whose confirmation the placed order still needs", () => {
    const placed = { ...placedOrder, supplier_must_confirm: ["sup-bakery", "sup-fish"] };
    expect(mapOrder(proposal, placed).supplierMustConfirm).toEqual(["sup-bakery", "sup-fish"]);
  });

  it("uses no supplier confirmations when the field is absent or malformed", () => {
    expect(mapOrder(proposal, placedOrder).supplierMustConfirm).toEqual([]);
    expect(mapOrder(proposal, null).supplierMustConfirm).toEqual([]);
    for (const supplier_must_confirm of [null, "sup-bakery", 42, { id: "sup-bakery" }]) {
      expect(mapOrder(proposal, { ...placedOrder, supplier_must_confirm }).supplierMustConfirm).toEqual([]);
    }
  });

  it("reads a line's cut-off, lead time and reliability with their sources (#1453)", () => {
    const line = {
      ...proposal.lines[0],
      cutoff_at: "2026-11-19T10:00:00+02:00", cutoff_source: "demo",
      lead_time_days: 2, lead_time_source: "supplier_terms",
      delivery_reliability: 0.94, reliability_source: "valio",
    };
    const { offer } = mapOrder({ ...proposal, lines: [line] }, null).lines[0];
    expect(offer).toMatchObject({
      closingTime: "2026-11-19T10:00:00+02:00",
      cutoffSource: "demo",
      leadTimeDays: 2,
      leadTimeSource: "supplier_terms",
      deliveryReliability: 0.94,
      reliabilitySource: "valio",
    });
  });

  it("reads a proposal stored before #1453 (no delivery facts) as unknown", () => {
    const { offer } = mapOrder(proposal, null).lines[0];
    expect(offer).toMatchObject({
      closingTime: null,
      cutoffSource: null,
      leadTimeDays: null,
      leadTimeSource: null,
      deliveryReliability: null,
      reliabilitySource: null,
    });
  });

  it("maps a waiting proposal; what the gateway does not send stays unknown, never zero", () => {
    const order = mapOrder(proposal, null);
    expect(order).toMatchObject({
      id: "prop-1",
      status: "NEEDS_APPROVAL",
      urgency: "UNKNOWN",
      deliveryDate: "2026-11-20",
      totalExVat: 80,
      vat: 11.2,
      deliveryFee: null,
      totalInclVat: 91.2,
      mov: null,
    });
    expect(order.lines).toHaveLength(1);
    expect(order.lines[0]).toMatchObject({ quantity: 40, lineTotal: 80, why: "40 ST of oat drink = 40 L, confirmed in stock." });
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

  it("keeps the line's product name and the order's delivery fee", () => {
    const order = mapOrder(
      {
        ...proposal,
        delivery_fee: "4.50",
        lines: [{ ...proposal.lines[0], product_name: "Oat drink 1 L" }],
      },
      null,
    );
    expect(order.deliveryFee).toBe(4.5);
    expect(order.lines[0]!.product.names.en).toBe("Oat drink 1 L");
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

  it("decodes the signed receipt for display; an old order has none; a proposal has no receipt field", () => {
    const encode = (value: unknown) => btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const claims = { sub: "ord-1", expected_total: "91.20", approved_by: "Aino Ääkkönen", iat: 1_763_107_200 };
    // UTF-8 bytes, as the gateway signs them.
    const payload = btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(claims))))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const jws = `${encode({ alg: "EdDSA", kid: "k1" })}.${payload}.sig`;

    expect(mapOrder(null, { ...placedOrder, receipt: jws }).receipt).toEqual({
      jws,
      approvedBy: "Aino Ääkkönen",
      signedAt: new Date(1_763_107_200_000).toISOString(),
      total: 91.2,
      supplierOutcome: null,
      supplierNote: null,
    });
    expect(mapOrder(null, { ...placedOrder, receipt: null }).receipt).toBeNull();
    expect(mapOrder(null, placedOrder).receipt).toBeNull();
    expect(mapOrder(null, { ...placedOrder, receipt: "not-a-jws" }).receipt).toEqual({
      jws: "not-a-jws", approvedBy: null, signedAt: null, total: null, supplierOutcome: null, supplierNote: null,
    });
    expect(mapOrder(proposal, null).receipt).toBeUndefined();
  });

  it("says when the demo seed placed the order; every other order has no placedBy", () => {
    const seeded = mapOrder(null, { ...placedOrder, receipt: null, placed_by: "demo-seed" });
    expect(seeded.placedBy).toBe("demo-seed");
    expect(seeded.receipt).toBeNull();
    expect(mapOrder(null, { ...placedOrder, placed_by: null }).placedBy).toBeUndefined();
    expect(mapOrder(null, placedOrder).placedBy).toBeUndefined();
    expect(mapOrder(null, { ...placedOrder, placed_by: "someone-else" }).placedBy).toBeUndefined();
    expect(mapOrder(proposal, null).placedBy).toBeUndefined();
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
        reason: "1 product for Fri 20 Nov",
        details: 'product_ids: ["900001"]; requested_date: 2026-11-20',
        groupIds: ["run-1"],
      },
      {
        id: "ev-2",
        at: null,
        orderId: undefined,
        kind: "approval",
        actor: "agent",
        summary: "Buyer asked for approval: it failed",
        reason: "",
        details: "error: Rejected by buyer policy; reason_code: POLICY_VIOLATION",
        groupIds: ["run-1"],
      },
      {
        id: "ev-3",
        at: "2026-11-14T10:00:00+00:00",
        orderId: "prop-1",
        kind: "approval",
        actor: "agent",
        summary: "Approval requested",
        reason: "",
        details: "expected_total: 91.20",
        groupIds: ["prop-1", "offer-1"],
      },
      {
        id: "ev-4",
        at: "2026-11-14T10:05:00+00:00",
        orderId: "ord-1",
        kind: "order",
        actor: "chef",
        summary: "Order placed",
        reason: "",
        details: "expected_total: 91.20",
        groupIds: ["prop-1", "ord-1"],
      },
      {
        id: "ev-5",
        at: "2026-11-14T10:06:00+00:00",
        orderId: undefined,
        kind: "other",
        actor: "human",
        // An unknown snake_case kind reads as words, never as the raw code (mock jury, 14 Nov).
        summary: "Something new",
        reason: "",
        details: "No details recorded.",
        groupIds: [],
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
        summary: "Request refused by the gateway",
        reason: "",
        details: "status: 403; code: SCOPE_MISSING; method: POST; path: /kitchens/k-1/orders",
        groupIds: [],
      },
    ]);
    expect(mapAudit([{ ...refused, actor: "buyer-agent" }])[0].actor).toBe("agent");
  });

  it("names the signed-in account that took a step, and no one for the open demo or a token", () => {
    const placed = { seq: 12, event_id: "ev-12", kind: "order_placed", at: "2026-11-14T08:00:00+00:00", order_id: "ord-1" };
    expect(mapAudit([{ ...placed, actor: "approver@example.test" }])[0]).toMatchObject({
      actor: "human",
      actorName: "approver@example.test",
      summary: "Order placed",
    });
    for (const actor of ["demo-visitor", "approver", "buyer-agent", "token:a@b.c", "supplier:valio@x"]) {
      expect(mapAudit([{ ...placed, actor }])[0]).not.toHaveProperty("actorName");
    }
  });

  it("says a sign-in in plain words", () => {
    const step = mapAudit([{ seq: 1, event_id: "ev-1", kind: "signed_in", actor: "chef@example.test", at: null }])[0];
    expect(step).toMatchObject({ kind: "other", summary: "Signed in", actorName: "chef@example.test" });
  });

  it("says an order lookup in plain words in English and Finnish", () => {
    const [step] = mapAudit([{ event_id: "lookup", kind: "order_lookup", at: null }]);
    expect(step.summary).toBe("Order status checked");
    expect(translate("fi", step.summary)).toBe("Tilauksen tila tarkistettu");
  });

  it("gives known audit steps Finnish names", () => {
    const summaries: Record<string, [string, string]> = {
      stock_photo_read: ["Shelf photo read by Nemotron VL", "Hyllykuva luettu Nemotron VL:llä"],
      audit_demo_tamper: ["Tamper demo: a line was changed", "Muutosesimerkki: riviä muutettiin"],
      audit_demo_restore: ["Tamper demo: the line was restored", "Muutosesimerkki: rivi palautettiin"],
      option_chosen: ["A person chose an option", "Henkilö valitsi vaihtoehdon"],
      order_lookup: ["Order status checked", "Tilauksen tila tarkistettu"],
      order_resolved: ["A person resolved an unknown send", "Henkilö selvitti tuntemattoman lähetyksen"],
      recall_check: ["Recall check", "Takaisinvetotarkistus"],
      demo_inbox_cleared: ["Inbox cleared", "Postilaatikko tyhjennetty"],
      signed_in: ["Signed in", "Kirjauduttu sisään"],
      password_changed: ["Password changed", "Salasana vaihdettu"],
      kitchen_brief_read: ["Kitchen brief read", "Keittiön ohjeet luettu"],
      delivery_note_read: ["Delivery note read", "Lähetyslista luettu"],
      proposal_created: ["Proposal created", "Ehdotus luotu"],
      proposal_explanation_failed: ["No model sentence for a proposal", "Ehdotukselle ei ole mallin tekstiä"],
      approval_requested: ["Approval requested", "Hyväksyntää pyydetty"],
      decision_summary: ["Decision summary", "Päätöksen yhteenveto"],
      total_mismatch: ["The total moved before placing: nothing was sent", "Summa muuttui ennen lähetystä: mitään ei lähetetty"],
      order_placed: ["Order placed", "Tilaus tehty"],
      proposal_rejected: ["Proposal rejected", "Ehdotus hylätty"],
      refused: ["Request refused by the gateway", "Yhdyskäytävä hylkäsi pyynnön"],
      supplier_offer_received: ["Offer received from the supplier's selling agent", "Tarjous vastaanotettu toimittajan myyntiagentilta"],
      supplier_offer_accepted: ["Supplier offer accepted: a proposal was made from it", "Toimittajan tarjous hyväksytty: siitä tehtiin ehdotus"],
      supplier_offer_declined: ["Supplier offer declined", "Toimittajan tarjous hylätty"],
    };
    for (const [kind, [english, finnish]] of Object.entries(summaries)) {
      const [step] = mapAudit([{ event_id: kind, kind }]);
      expect(step.summary).toBe(english);
      expect(translate("fi", step.summary)).toBe(finnish);
    }

    const tools: Record<string, [string, string, string, string]> = {
      search_products: ["Buyer is searching the catalog", "Ostaja etsii tuoteluettelosta", "Buyer searched the catalog", "Ostaja etsi tuoteluettelosta"],
      get_offer: ["Buyer is asking for an offer", "Ostaja pyytää tarjousta", "Buyer got the offer", "Ostaja sai tarjouksen"],
      simulate_order: ["Buyer is simulating the order", "Ostaja simuloi tilausta", "Buyer simulated the order", "Ostaja simuloi tilauksen"],
      request_approval: ["Buyer is asking for approval", "Ostaja pyytää hyväksyntää", "Buyer asked for approval", "Ostaja pyysi hyväksyntää"],
      place_order: ["Buyer is placing the order", "Ostaja tekee tilausta", "Buyer placed the order", "Ostaja teki tilauksen"],
      get_order_status: ["Buyer is checking the order status", "Ostaja tarkistaa tilauksen tilan", "Buyer checked the order status", "Ostaja tarkisti tilauksen tilan"],
    };
    for (const [tool, [started, startedFi, done, doneFi]] of Object.entries(tools)) {
      const [start, finish] = mapAudit([
        { event_id: `${tool}-start`, type: "tool_call_started", tool, arguments: {} },
        { event_id: `${tool}-finish`, type: "tool_call_finished", tool, arguments: {}, result: {} },
      ]);
      expect([start.summary, translate("fi", start.summary)]).toEqual([started, startedFi]);
      expect([finish.summary, translate("fi", finish.summary)]).toEqual([done, doneFi]);
    }
  });

  it("gives an order its own steps and those of the proposal that placed it", () => {
    expect(mapAudit(auditEvents, "ord-1").map((event) => event.id)).toEqual(["ev-3", "ev-4"]);
    expect(mapAudit(auditEvents, "prop-1").map((event) => event.id)).toEqual(["ev-3", "ev-4"]);
    expect(mapAudit(auditEvents, "ord-none")).toEqual([]);
  });

  it("keeps every old raw reason in details and only readable words in reason", () => {
    const [tool] = mapAudit([
      {
        event_id: "tool",
        run_id: "run",
        type: "tool_call_started",
        tool: "get_offer",
        arguments: '{"product_ids":["1","2","3"],"requested_date":"2026-11-17","need_id":"need"}',
      },
    ]);
    const oldToolReason = 'product_ids: ["1","2","3"]; requested_date: 2026-11-17; need_id: need';
    expect(tool.reason).toBe("3 products for Tue 17 Nov");
    expect(tool.details).toBe(oldToolReason);
    expect(`${tool.reason}\n${tool.details}`).toContain("need_id: need");

    const [gateway] = mapAudit([
      {
        event_id: "gateway",
        kind: "decision_summary",
        summary: "Asked for milk",
        reason: "An additional explanation",
        expected_total: "12.30",
      },
    ]);
    expect(gateway.reason).toBe("Asked for milk");
    expect(gateway.details).toContain("reason: An additional explanation");
    expect(gateway.details).toContain("expected_total: 12.30");

    const [search] = mapAudit([
      { event_id: "search", type: "tool_call_finished", tool: "search_products", arguments: { query_present: true }, result: {} },
    ]);
    expect(search.reason).toBe("");
    expect(search.details).toBe("No details recorded.");
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
