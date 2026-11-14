import type { Order, OrderReceipt } from "@/types";

function base64url(value: unknown): string {
  return btoa(JSON.stringify(value)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * A sample receipt shaped like the gateway's (docs/contract.md "Signed order receipt").
 * The signature part is a placeholder: the mock has no key, and the browser never verifies.
 */
export function sampleReceipt(order: Order, approvedBy: string, signedAt: string): OrderReceipt {
  const claims = {
    iss: "trusted-kitchen-buyer",
    type: "order_receipt",
    sub: order.id,
    kitchen_id: "demo-kitchen",
    offer_id: "OFR-MILK-1042",
    offer_hash: "9b1f0c4e2a7d4f55b8a0d6c3e1f2a4b6c8d0e2f4a6b8c0d2e4f6a8b0c2d4e6f8",
    currency: "EUR",
    expected_total: order.totalInclVat.toFixed(2),
    lines: order.lines.map((line) => ({
      product_id: line.product.id,
      quantity: String(line.quantity),
      unit: line.product.salesUnit,
    })),
    approved_by: approvedBy,
    iat: Math.floor(Date.parse(signedAt) / 1000),
    supplier_outcome: "NOT_SENT",
    supplier_note: "Valio's API has no order endpoint: the gateway recorded the order and sent nothing.",
    supplier_must_confirm: [],
  };
  const jws = `${base64url({ alg: "EdDSA", kid: "demo-key-1" })}.${base64url(claims)}.c2FtcGxlLXNpZ25hdHVyZS1ub3QtdmFsaWQ`;
  return { jws, approvedBy, signedAt: new Date(claims.iat * 1000).toISOString(), total: order.totalInclVat };
}
