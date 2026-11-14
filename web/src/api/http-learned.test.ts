import { describe, expect, it, vi } from "vitest";

import { createLearnedHttp, mapLearnedFact } from "@/api/http-learned";

const FACT = {
  id: "lf_01JYK8M4N3M4K7W8N0E4Q2F6C5",
  kind: "CORRECTION_RATIO",
  product_id: "462775",
  supplier_id: null,
  name: "Washed potato 10 kg",
  value: 0.5,
  raw_value: 0.5,
  applicable: true,
  evidence: { rows: 4, from: "2026-09-21", to: "2026-11-09", last: "2026-11-09" },
  since: "2026-11-14",
  active: true,
};

const MAPPED = {
  id: FACT.id,
  kind: "CORRECTION_RATIO",
  productId: "462775",
  supplierId: null,
  name: FACT.name,
  value: 0.5,
  rawValue: 0.5,
  applicable: true,
  evidence: FACT.evidence,
  since: FACT.since,
  active: true,
  meanDaysLate: undefined,
  onTimeRate: undefined,
  deliveries: undefined,
  meanLeadTime: undefined,
  sigmaLeadTime: undefined,
};

describe("learned facts gateway boundary", () => {
  it("lists and maps one kitchen's learned facts", async () => {
    const call = vi.fn(async () => ({ facts: [FACT] }));
    const api = createLearnedHttp(call, "/v1/kitchens/k-1");

    expect(await api.listLearnedFacts()).toEqual([MAPPED]);
    expect(call).toHaveBeenCalledWith("/v1/kitchens/k-1/learned");
  });

  it("switches a fact off with PUT and maps its returned state", async () => {
    const call = vi.fn(async () => ({ fact: { ...FACT, active: false } }));
    const api = createLearnedHttp(call, "/v1/kitchens/k-1");

    const result = await api.setLearnedFactActive(FACT.id, false, "human");

    expect(result.active).toBe(false);
    expect(call).toHaveBeenCalledWith(`/v1/kitchens/k-1/learned/${FACT.id}`, {
      method: "PUT",
      headers: { "X-User": "human" },
      body: JSON.stringify({ active: false }),
    });
  });

  it("escapes fact ids in the contract route", async () => {
    const call = vi.fn(async () => ({ fact: FACT }));
    const api = createLearnedHttp(call, "/v1/kitchens/k-1");
    await api.setLearnedFactActive("lf/a b", false, "human");
    expect(call).toHaveBeenCalledWith(
      "/v1/kitchens/k-1/learned/lf%2Fa%20b",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ active: false }) }),
    );
  });

  it("does not turn non-finite or non-numeric values into zero", () => {
    expect(() => mapLearnedFact({ ...FACT, value: "0.5" })).toThrow("value");
    expect(() => mapLearnedFact({ ...FACT, value: Number.POSITIVE_INFINITY })).toThrow("value");
    expect(mapLearnedFact({ ...FACT, raw_value: undefined }).rawValue).toBeUndefined();
  });

  it("keeps nullable supplier lead times unknown", () => {
    const fact = mapLearnedFact({
      ...FACT,
      kind: "SUPPLIER_LATE",
      product_id: null,
      supplier_id: "SUP-BAKERY",
      mean_lead_time: null,
      sigma_lead_time: null,
    });
    expect(fact.meanLeadTime).toBeNull();
    expect(fact.sigmaLeadTime).toBeNull();
  });
});
