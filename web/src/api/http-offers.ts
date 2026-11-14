import { type Json, object, rows, text } from "@/api/gateway-map";
import type { Api } from "@/api/types";
import { ApiError } from "@/api/types";
import type { SupplierOffer } from "@/types";

/** The gateway request of api/http.ts: a path under the base URL, the parsed JSON back. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

type OffersApi = Pick<Api, "listSupplierOffers" | "acceptSupplierOffer" | "declineSupplierOffer">;

const STATUSES = ["OPEN", "ACCEPTED", "DECLINED", "EXPIRED"] as const;

function optional(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

/** One offer in the contract's shape. An unknown status is an error, never shown as open. */
export function mapSupplierOffer(value: unknown): SupplierOffer {
  const row = object(value, "a supplier offer");
  const status = STATUSES.find((known) => known === row.status);
  if (!status) throw new ApiError("INVALID_RESPONSE", "The gateway sent a supplier offer with an unknown status.");
  return {
    id: text(row.offer_id, "an offer_id"),
    supplierId: text(row.supplier_id, "a supplier_id"),
    productId: text(row.product_id, "a product_id"),
    productName: optional(row.product_name),
    replacesProductId: text(row.replaces_product_id, "a replaces_product_id"),
    replacesProductName: optional(row.replaces_product_name),
    requestedDate: text(row.requested_date, "a requested_date"),
    quantity: text(row.quantity, "a quantity"),
    unit: text(row.unit, "a unit"),
    // The supplier's own words: kept as text, rendered as text.
    reason: typeof row.reason === "string" ? row.reason : "",
    madeBy: typeof row.made_by === "string" ? row.made_by : "",
    status,
    createdAt: optional(row.created_at),
    proposalId: optional(row.proposal_id),
  };
}

/**
 * Supplier offers against the real gateway (docs/contract.md, "Supplier offers"). `kitchen` is
 * `/v1/kitchens/{id}`. Accept and decline need no idempotency key: the gateway makes one
 * proposal per offer, whatever the number of clicks.
 */
export function createOffersHttp(call: GatewayCall, kitchen: string): OffersApi {
  const offerPath = (id: string) => `${kitchen}/supplier-offers/${encodeURIComponent(id)}`;
  const send = (path: string, body: Json, actor: string) =>
    call(path, { method: "POST", headers: { "X-User": actor }, body: JSON.stringify(body) });
  return {
    async listSupplierOffers() {
      return rows(await call(`${kitchen}/supplier-offers`), "offers").map(mapSupplierOffer);
    },
    async acceptSupplierOffer(offerId, actor) {
      const body = object(await send(`${offerPath(offerId)}/accept`, {}, actor), "the accept answer");
      return {
        offer: mapSupplierOffer(body.offer),
        proposalId: text(body.proposal_id, "a proposal_id"),
        proposalStatus: text(body.proposal_status, "a proposal_status"),
      };
    },
    async declineSupplierOffer(offerId, actor, reason) {
      return mapSupplierOffer(await send(`${offerPath(offerId)}/decline`, reason ? { reason } : {}, actor));
    },
  };
}
