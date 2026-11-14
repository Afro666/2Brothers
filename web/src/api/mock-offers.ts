import type { Api } from "@/api/types";
import { ApiError } from "@/api/types";
import type { SupplierOffer } from "@/types";

type OffersApi = Pick<Api, "listSupplierOffers" | "acceptSupplierOffer" | "declineSupplierOffer">;

/** Sample data: one open offer, in the shape the gateway answers (docs/contract.md, "Supplier offers"). */
export const sampleSupplierOffer: SupplierOffer = {
  id: "OFFER-DEMO-1",
  supplierId: "valio",
  productId: "462535",
  productName: "Valio Eila lactose-free milk drink 1 L",
  replacesProductId: "462775",
  replacesProductName: "Arla lactose-free milk 1 L",
  requestedDate: "2026-11-16",
  quantity: "42",
  unit: "L",
  reason: "Same pack size and lactose free. It is in stock for Monday.",
  madeBy: "nemotron-3.5-super-vl",
  status: "OPEN",
  createdAt: "2026-11-14T05:10:00+00:00",
  proposalId: null,
};

/**
 * shortcut: accepting answers a proposal id but adds no card to the mock inbox (the mock's
 * approvals are fixed sample orders). The real gateway makes the proposal.
 */
export function createOffersMock(): OffersApi {
  const offers = new Map<string, SupplierOffer>([[sampleSupplierOffer.id, structuredClone(sampleSupplierOffer)]]);
  const open = (offerId: string): SupplierOffer => {
    const offer = offers.get(offerId);
    if (!offer) throw new ApiError("OFFER_NOT_FOUND", "No such offer.", {}, 404);
    return offer;
  };
  return {
    async listSupplierOffers() {
      return [...offers.values()].sort((a, b) => Number(b.status === "OPEN") - Number(a.status === "OPEN"));
    },
    async acceptSupplierOffer(offerId) {
      const offer = open(offerId);
      if (offer.status !== "OPEN" && offer.status !== "ACCEPTED") {
        throw new ApiError("OFFER_NOT_OPEN", `This offer is ${offer.status.toLowerCase()}.`, {}, 409);
      }
      const accepted: SupplierOffer = { ...offer, status: "ACCEPTED", proposalId: `PROP-${offer.id}` };
      offers.set(offerId, accepted);
      return { offer: accepted, proposalId: accepted.proposalId!, proposalStatus: "READY" };
    },
    async declineSupplierOffer(offerId) {
      const offer = open(offerId);
      if (offer.status !== "OPEN" && offer.status !== "DECLINED") {
        throw new ApiError("OFFER_NOT_OPEN", `This offer is ${offer.status.toLowerCase()}.`, {}, 409);
      }
      const declined: SupplierOffer = { ...offer, status: "DECLINED" };
      offers.set(offerId, declined);
      return declined;
    },
  };
}
