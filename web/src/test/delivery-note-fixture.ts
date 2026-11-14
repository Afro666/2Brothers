export const DELIVERY_NOTE = {
  model: "nemotron-3.5-super-vl", duration_ms: 5120, saved: false, order_id: "ORD-1042",
  note: { order_ref: "ORD-DEMO-0001", delivery_date: "2026-11-16" }, complete: false,
  lines: [{ product_id: "462775", status: "SHORT", ordered: "51", received: "36", missing: "15", base_unit: "ST",
    lots: [{ lot: "L2611A", best_before: "unknown", quantity: "3", unit: "KI" }] }],
  not_ordered: [{ product_id: "462921", status: "SUBSTITUTE", replaces: "462775", quantity: "2", unit: "KI",
    received: "10", base_unit: "ST", lot: "L2611B", best_before: "2026-11-28", needs_approval: true }],
};
