import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { mapSupplierOffer } from "@/api/http-offers";
import { mapAudit } from "@/api/gateway-map";

const K = "/api/v1/kitchens/demo-kitchen";
type Handler = (body: Record<string, unknown>) => unknown;

/** A fake gateway: `"POST /path"` -> the JSON it answers. Returns the calls it received. */
function gateway(routes: Record<string, Handler>) {
  const calls: { route: string; body: Record<string, unknown>; user: string | undefined }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    const route = `${init.method ?? "GET"} ${url}`;
    const body = init.body ? JSON.parse(init.body as string) : {};
    calls.push({ route, body, user: (init.headers as Record<string, string> | undefined)?.["X-User"] });
    const answer = routes[route]
      ? routes[route](body)
      : new Response(JSON.stringify({ error: { code: "NO_ROUTE", message: route } }), { status: 404 });
    return answer instanceof Response ? answer : new Response(JSON.stringify(answer));
  });
  return calls;
}

/** The contract's example (docs/contract.md, "Supplier offers"). */
const OFFER = {
  offer_id: "5f0c",
  supplier_id: "sup-valio",
  kitchen_id: "demo-kitchen",
  product_id: "400123",
  product_name: "Lactose free milk drink 1 L",
  replaces_product_id: "400555",
  replaces_product_name: "Lactose free semi-skimmed milk 1 L",
  requested_date: "2026-11-17",
  quantity: "42",
  unit: "L",
  reason: "Same fat level and pack size; in stock for Monday.",
  made_by: "nemotron-3.5-super-vl",
  status: "OPEN",
  created_at: "2026-11-14T05:10:00+00:00",
  proposal_id: null,
  decided_by: null,
  decided_at: null,
};

afterEach(() => vi.unstubAllGlobals());

describe("Supplier offers on the real gateway", () => {
  it("marks the three methods as live, so the live site never shows the sample offer", () => {
    gateway({});
    const live = createHttpApi("/api").live!;
    for (const name of ["listSupplierOffers", "acceptSupplierOffer", "declineSupplierOffer"] as const) {
      expect(live.has(name)).toBe(true);
    }
  });

  it("lists the kitchen's offers in the contract's shape", async () => {
    const calls = gateway({ [`GET ${K}/supplier-offers`]: () => ({ offers: [OFFER] }) });
    expect(await createHttpApi("/api").listSupplierOffers()).toEqual([
      {
        id: "5f0c",
        supplierId: "sup-valio",
        productId: "400123",
        productName: "Lactose free milk drink 1 L",
        replacesProductId: "400555",
        replacesProductName: "Lactose free semi-skimmed milk 1 L",
        requestedDate: "2026-11-17",
        quantity: "42",
        unit: "L",
        reason: "Same fat level and pack size; in stock for Monday.",
        madeBy: "nemotron-3.5-super-vl",
        status: "OPEN",
        createdAt: "2026-11-14T05:10:00+00:00",
        proposalId: null,
        allergenDataKnown: false,
      },
    ]);
    expect(calls.map((call) => call.route)).toEqual([`GET ${K}/supplier-offers`]);
  });

  it("fails when the gateway does not serve the route, instead of answering from the mock", async () => {
    gateway({});
    await expect(createHttpApi("/api").listSupplierOffers()).rejects.toMatchObject({ code: "NO_ROUTE" });
  });

  it("accepts with an empty body and maps the proposal it became", async () => {
    const calls = gateway({
      [`POST ${K}/supplier-offers/5f0c/accept`]: () => ({
        offer: { ...OFFER, status: "ACCEPTED", proposal_id: "9a1b" },
        proposal_id: "9a1b",
        proposal_status: "READY",
      }),
    });
    const accepted = await createHttpApi("/api").acceptSupplierOffer("5f0c", "human");
    expect(accepted).toMatchObject({ proposalId: "9a1b", proposalStatus: "READY" });
    expect(accepted.offer).toMatchObject({ status: "ACCEPTED", proposalId: "9a1b" });
    expect(calls).toEqual([{ route: `POST ${K}/supplier-offers/5f0c/accept`, body: {}, user: "human" }]);
  });

  it("declines, with the reason only when there is one", async () => {
    const calls = gateway({ [`POST ${K}/supplier-offers/5f0c/decline`]: () => ({ ...OFFER, status: "DECLINED" }) });
    const api = createHttpApi("/api");
    expect((await api.declineSupplierOffer("5f0c", "chef")).status).toBe("DECLINED");
    await api.declineSupplierOffer("5f0c", "chef", "we changed the menu");
    expect(calls.map((call) => call.body)).toEqual([{}, { reason: "we changed the menu" }]);
  });

  it("escapes the offer id in the path", async () => {
    const calls = gateway({});
    await createHttpApi("/api")
      .declineSupplierOffer("a/b", "human")
      .catch(() => undefined);
    expect(calls[0].route).toBe(`POST ${K}/supplier-offers/a%2Fb/decline`);
  });

  it("refuses an offer with an unknown status; missing names stay null", () => {
    expect(() => mapSupplierOffer({ ...OFFER, status: "PAID" })).toThrow(/unknown status/);
    expect(mapSupplierOffer({ ...OFFER, product_name: null }).productName).toBeNull();
  });

  it("reads allergen data as known only when the gateway says true", () => {
    expect(mapSupplierOffer({ ...OFFER, allergen_data_known: true }).allergenDataKnown).toBe(true);
    expect(mapSupplierOffer({ ...OFFER, allergen_data_known: false }).allergenDataKnown).toBe(false);
    expect(mapSupplierOffer({ ...OFFER, allergen_data_known: "yes" }).allergenDataKnown).toBe(false);
  });
});

describe("audit labels for supplier offers", () => {
  const at = "2026-11-14T05:10:00+00:00";

  it("labels the three steps; the supplier's agent is Valio, the person is a person", () => {
    const events = mapAudit([
      {
        event_id: "e1",
        kind: "supplier_offer_received",
        actor: "supplier:sup-valio",
        at,
        offer_id: "5f0c",
        product_id: "400123",
        quantity: "42",
        unit: "L",
        made_by: "nemotron-3.5-super-vl",
      },
      { event_id: "e2", kind: "supplier_offer_accepted", actor: "demo-visitor", at, offer_id: "5f0c", proposal_id: "9a1b" },
      { event_id: "e3", kind: "supplier_offer_declined", actor: "demo-visitor", at, offer_id: "5f0d", reason: "no need" },
    ]);
    expect(events.map((event) => [event.kind, event.actor, event.summary])).toEqual([
      ["offer", "valio", "Offer received from the supplier's selling agent"],
      ["offer", "human", "Supplier offer accepted: a proposal was made from it"],
      ["offer", "human", "Supplier offer declined"],
    ]);
    expect(events[0].reason).toBe("product_id: 400123; quantity: 42; unit: L; made_by: nemotron-3.5-super-vl");
    expect(events[1].orderId).toBe("9a1b");
    expect(events[2].reason).toBe("no need");
  });
});
