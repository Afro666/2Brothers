export const DELIVERY_NOTE = {
  model: "nemotron-3.5-super-vl", duration_ms: 5120, saved: false, order_id: "ORD-1042",
  note: { order_ref: "ORD-DEMO-0001", delivery_date: "2026-11-16" }, complete: false,
  lines: [{ product_id: "462775", status: "SHORT", ordered: "51", received: "36", missing: "15", base_unit: "ST",
    order_quantity: "51", order_unit: "ST", missing_order_qty: "15", unit_price: "1.10", claim_eur: "16.50",
    lots: [{ lot: "L2611A", best_before: "unknown", quantity: "3", unit: "KI" }] }],
  not_ordered: [{ product_id: "462921", status: "SUBSTITUTE", replaces: "462775", quantity: "2", unit: "KI",
    received: "10", base_unit: "ST", lot: "L2611B", best_before: "2026-11-28", needs_approval: true }],
  claim: { currency: "EUR", total_eur: "16.50", lines: 1, quantity: "15", unit: "ST", not_valued: 0, supplier_name: "Valio Aimo" },
};

/** The delivery beat (#1198): the demo order DEMO-1198 and the prepared note photo. */
export const DEMO_DELIVERY_NOTE = {
  model: "nemotron-3.5-super-vl", duration_ms: 3100, saved: false, order_id: "ORD-1042",
  note: { order_ref: "DEMO-1198", delivery_date: "2026-11-16" }, complete: false,
  lines: [
    { product_id: "463982", status: "SHORT", ordered: "3", received: "1", missing: "2", base_unit: "KI",
      order_quantity: "3", order_unit: "KI", missing_order_qty: "2", unit_price: "31.01", claim_eur: "62.02", lots: [] },
    { product_id: "460838", status: "MISSING", ordered: "1", received: "0", missing: "1", base_unit: "KI",
      order_quantity: "1", order_unit: "KI", missing_order_qty: "1", unit_price: "29.06", claim_eur: "29.06", lots: [] },
    { product_id: "463335", status: "RECEIVED", ordered: "40", received: "40", missing: "0", base_unit: "ST",
      order_quantity: "40", order_unit: "ST", missing_order_qty: "0", unit_price: "1.40", claim_eur: "0.00", lots: [] },
  ],
  not_ordered: [],
  claim: { currency: "EUR", total_eur: "91.08", lines: 2, quantity: "3", unit: "KI", not_valued: 0, supplier_name: "Valio Aimo" },
};
