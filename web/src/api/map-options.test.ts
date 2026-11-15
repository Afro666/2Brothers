import { describe, expect, it } from "vitest";

import { mapProposalOptions } from "@/api/map-options";

/** Hand-written from docs/contract.md ("Chef substitute choices"); not Valio data. */
function option(overrides: Record<string, unknown> = {}) {
  return {
    tier: "good",
    source: "original",
    offer_id: "offer-a",
    expected_total: "148.76",
    currency: "EUR",
    lines: [{ product_id: "P1", quantity: "51", unit: "ST", why: "51 confirmed.", unknown_stock: false }],
    why: "Requested product, confirmed portion only.",
    requires_chef_approval: true,
    stock_confirmed: true,
    allergen_data_known: true,
    ...overrides,
  };
}

function line(overrides: Record<string, unknown> = {}) {
  return { product_id: "P1", quantity: "51", unit: "ST", why: "x", unknown_stock: false, ...overrides };
}

describe("mapProposalOptions", () => {
  it("reads the line's own names and brand (#1130), over the names map; empty is unknown", () => {
    const [mapped] = mapProposalOptions(
      [
        option({
          lines: [
            line({ product_name: "Arla milk 1 L", product_name_fi: "Arla maito 1 l", brand: "Arla" }),
            line({ product_id: "P2", product_name: null, product_name_fi: "", brand: "  " }),
            line({ product_id: "P3" }),
          ],
        }),
      ],
      undefined,
      new Map([["P1", "Old name"], ["P3", "From the map"]]),
    );
    expect(mapped.lines.map((row) => [row.productId, row.productName, row.productNameFi, row.brand])).toEqual([
      ["P1", "Arla milk 1 L", "Arla maito 1 l", "Arla"],
      ["P2", null, null, null],
      ["P3", "From the map", null, null],
    ]);
  });

  it("maps a contract option and leaves what the gateway does not send unknown", () => {
    expect(mapProposalOptions([option()], "offer-a")).toEqual([
      {
        id: "offer-a",
        tier: "good",
        source: "original",
        kind: "FULL",
        lines: [{ productId: "P1", productName: null, productNameFi: null, brand: null, quantity: 51, unit: "ST", unitPrice: null }],
        totalInclVat: 148.76,
        totalExVat: null,
        stockConfirmed: true,
        cutoffPassed: null,
        cutoffAt: null,
        cutoffSource: null,
        leadTimeDays: null,
        leadTimeSource: null,
        deliveryReliability: null,
        reliabilitySource: null,
        co2KgPerKg: null,
        labels: null,
        tradeOff: "Requested product, confirmed portion only.",
        recommended: false,
        held: null,
        chosen: true,
      },
    ]);
  });

  it("adds the gateway's line totals to the option's ex VAT total; unknown when one line has none (#1970)", () => {
    const [known] = mapProposalOptions([
      option({ lines: [line({ total: "1849.70" }), line({ product_id: "P2", total: "471.12" })] }),
    ]);
    expect(known.totalExVat).toBe(2320.82);
    const [unknown] = mapProposalOptions([option({ lines: [line({ total: "1849.70" }), line({ product_id: "P2" })] })]);
    expect(unknown.totalExVat).toBeNull();
  });

  it("reads the per-line extras: price, cut-off, reliability, carbon, labels, partial stock", () => {
    const [mapped] = mapProposalOptions(
      [
        option({
          recommended: true,
          lines: [
            line({
              unit_price: "2.57",
              cutoff_passed: false,
              reliability: 0.97,
              carbon_kg_co2e_per_kg: 1.3,
              labels: ["EU_ORGANIC_FARMING", "GOODS_FROM_FINLAND_BLUE_SWAN", "SOMETHING_NEW"],
              reason_codes: ["PARTIAL_STOCK"],
            }),
            line({
              product_id: "P2",
              unit_price: "2.05",
              cutoff_passed: false,
              reliability: 0.9,
              carbon_kg_co2e_per_kg: 1.1,
              labels: ["GOODS_FROM_FINLAND_BLUE_SWAN"],
            }),
          ],
        }),
      ],
      "another-offer",
      new Map([["P2", "Oat drink 1 L"]]),
    );
    expect(mapped).toMatchObject({
      kind: "PARTIAL",
      cutoffPassed: false,
      deliveryReliability: 0.9,
      co2KgPerKg: { min: 1.1, max: 1.3 },
      labels: ["GOODS_FROM_FINLAND_BLUE_SWAN"],
      recommended: true,
      chosen: false,
    });
    expect(mapped.lines.map((row) => [row.productName, row.unitPrice])).toEqual([
      [null, 2.57],
      ["Oat drink 1 L", 2.05],
    ]);
  });

  it("keeps a value unknown when one line does not state it; reliability is the weakest line that states one (#1453)", () => {
    const [mapped] = mapProposalOptions([
      option({
        lines: [
          line({ reliability: 0.97, carbon_kg_co2e_per_kg: 1.3, labels: ["EU_ORGANIC_FARMING"], cutoff_passed: false }),
          line({ product_id: "P2" }),
        ],
      }),
    ]);
    expect(mapped).toMatchObject({ co2KgPerKg: null, labels: null, cutoffPassed: null });
    // An older proposal's `reliability` is Valio's own figure.
    expect(mapped).toMatchObject({ deliveryReliability: 0.97, reliabilitySource: "valio" });
  });

  it("reads the delivery facts (#1453): earliest cut-off, longest lead time, weakest reliability, with sources", () => {
    const [mapped] = mapProposalOptions([
      option({
        lines: [
          line({
            cutoff_at: "2026-11-15T17:00:00+02:00", cutoff_source: "valio",
            lead_time_days: 1, lead_time_source: "supplier_terms",
            delivery_reliability: 0.97, reliability_source: "valio",
            reliability: 0.5,
          }),
          line({
            product_id: "P2",
            cutoff_at: "2026-11-14T10:00:00+02:00", cutoff_source: "demo",
            lead_time_days: 3, lead_time_source: "demo",
            delivery_reliability: 0.88, reliability_source: "demo",
          }),
          line({ product_id: "P3" }),
        ],
      }),
    ]);
    expect(mapped).toMatchObject({
      cutoffAt: "2026-11-14T10:00:00+02:00",
      cutoffSource: "demo",
      leadTimeDays: 3,
      leadTimeSource: "demo",
      // `delivery_reliability` wins over the old `reliability`; the line without one is skipped.
      deliveryReliability: 0.88,
      reliabilitySource: "demo",
    });
  });

  it("reads unknown or malformed delivery facts as null, never zero", () => {
    const [mapped] = mapProposalOptions([
      option({
        lines: [line({ cutoff_at: "soon", cutoff_source: "demo", lead_time_days: -1, delivery_reliability: 3, reliability_source: "elsewhere" })],
      }),
    ]);
    expect(mapped).toMatchObject({
      cutoffAt: null, cutoffSource: null, leadTimeDays: null, leadTimeSource: null, deliveryReliability: null, reliabilitySource: null,
    });
  });

  it("keeps a confirmed option distinct and maps its held remainder", () => {
    const [mapped] = mapProposalOptions([
      option({ source: "confirmed", recommended: true, held: { quantity: "949", unit: "L" } }),
    ]);
    expect(mapped).toMatchObject({
      source: "confirmed",
      recommended: true,
      held: { quantity: 949, unit: "L" },
    });
  });

  it("never invents a held quantity when the API does not send it", () => {
    expect(() => mapProposalOptions([option({ held: { unit: "L" } })])).toThrow(/held\.quantity/);
  });

  it("never reports confirmed stock when a line's stock is unknown or missing", () => {
    const lines = [line(), line({ product_id: "P2", unknown_stock: true })];
    expect(mapProposalOptions([option({ lines })])[0].stockConfirmed).toBe(false);
    expect(mapProposalOptions([option({ lines: [line({ unknown_stock: undefined })] })])[0].stockConfirmed).toBe(false);
    expect(mapProposalOptions([option({ stock_confirmed: false })])[0].stockConfirmed).toBe(false);
  });

  it("reports a missed cut-off when any line misses it", () => {
    const lines = [line({ cutoff_passed: false }), line({ product_id: "P2", cutoff_passed: true })];
    expect(mapProposalOptions([option({ lines })])[0].cutoffPassed).toBe(true);
  });

  it("returns no options when the proposal has none", () => {
    expect(mapProposalOptions(undefined)).toEqual([]);
    expect(mapProposalOptions([])).toEqual([]);
  });

  it.each([
    ["a number for money", [option({ expected_total: 148.76 })]],
    ["an unknown tier", [option({ tier: "premium" })]],
    ["another currency", [option({ currency: "SEK" })]],
    ["a choice that does not need the chef", [option({ requires_chef_approval: false })]],
    ["no lines", [option({ lines: [] })]],
    ["no sentence", [option({ why: "" })]],
    ["a line without a product", [option({ lines: [line({ product_id: undefined })] })]],
    ["an object instead of an array", option()],
  ])("rejects %s", (_name, value) => {
    expect(() => mapProposalOptions(value)).toThrow(/substitute_options|must be a decimal string/);
  });
});
