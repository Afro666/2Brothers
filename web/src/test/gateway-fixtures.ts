/**
 * Gateway responses written by hand from docs/contract.md and gateway/service.py.
 * The product code, names and prices are invented: no supplier data.
 */

const line = {
  product_id: "900001",
  quantity: "40",
  unit: "ST",
  unit_price: "2.00",
  total: "80.00",
  why: "40 ST of oat drink = 40 L, confirmed in stock.",
  unknown_stock: false,
  reason_codes: ["PACK_SIZE_DERIVED"],
};

export const proposal = {
  proposal_id: "prop-1",
  status: "READY",
  request: {
    product_ids: ["900001"],
    quantity: "50",
    unit: "L",
    requested_date: "2026-11-20",
    text: "50 L oat drink by Friday",
  },
  substitute_options: [],
  offer_id: "offer-1",
  valid_until: "2026-11-14T10:15:00+00:00",
  approval_id: "appr-1",
  order_id: null as string | null,
  currency: "EUR",
  total_ex_vat: "80.00",
  vat: "11.20",
  delivery_fee: null as string | null,
  mov_gap: null as string | null,
  expected_total: "91.20",
  shortfall: "10",
  measure: "L",
  mandate: {
    verdict: "NEEDS_APPROVAL",
    reasons: ["10 L of the request cannot be covered for this date."],
    reason_codes: ["PARTIAL_STOCK"],
    warnings: ["OVER_BUDGET_WARNING"],
  },
  lines: [line],
  excluded: [],
  alternative: null,
  decision_summary: { asked: "", searched: "", chosen: [], left_out: [], totals: "", decide: [], text: "" },
};

/** `GET /orders/{id}`: lines come without `why`. */
export const placedOrder = {
  order_id: "ord-1",
  outcome: "CONFIRMED" as string | null,
  status: "SENT",
  expected_total: "91.20",
  lines: [{ ...line, why: undefined }],
  created_at: "2026-11-14T10:05:00+00:00",
};

export const auditEvents = [
  {
    seq: 1,
    event_id: "ev-1",
    run_id: "run-1",
    type: "tool_call_started",
    tool: "get_offer",
    arguments: { product_ids: ["900001"], requested_date: "2026-11-20" },
    result: {},
    at: null,
  },
  {
    seq: 2,
    event_id: "ev-2",
    run_id: "run-1",
    type: "tool_call_finished",
    tool: "request_approval",
    arguments: {},
    result: { error: "Rejected by buyer policy", reason_code: "POLICY_VIOLATION" },
    at: null,
  },
  {
    seq: 3,
    event_id: "ev-3",
    kind: "approval_requested",
    actor: "buyer-agent",
    proposal_id: "prop-1",
    offer_id: "offer-1",
    expected_total: "91.20",
    at: "2026-11-14T10:00:00+00:00",
  },
  {
    seq: 4,
    event_id: "ev-4",
    kind: "order_placed",
    actor: "chef",
    proposal_id: "prop-1",
    order_id: "ord-1",
    expected_total: "91.20",
    at: "2026-11-14T10:05:00+00:00",
  },
  { seq: 5, event_id: "ev-5", kind: "something_new", actor: "demo-visitor", at: "2026-11-14T10:06:00+00:00" },
];

export const addable = {
  proposal_id: "prop-1",
  rows: [
    {
      rank: 1,
      product_id: "900002",
      name: "Oat cream 1 L",
      on_hand: null,
      on_order: "0",
      suggested_qty: "12",
      unit: "ST",
      unit_price: "3.10",
      addable: true,
      timing: "DUE_NOW",
      days_of_stock: null,
      reason_codes: [],
      why: "Not counted; 12 ST covers the next delivery.",
    },
    {
      rank: 2,
      product_id: "900003",
      name: "Rye flour 2 kg",
      on_hand: "4",
      on_order: null,
      suggested_qty: null,
      unit: "ST",
      unit_price: null,
      addable: false,
      why: "No price.",
    },
  ],
  skipped: [],
};
