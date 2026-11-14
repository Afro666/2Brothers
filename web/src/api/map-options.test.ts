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
  it("maps a contract option and leaves what the gateway does not send unknown", () => {
    expect(mapProposalOptions([option()], "offer-a")).toEqual([
      {
        id: "offer-a",
        tier: "good",
        kind: "FULL",
        lines: [{ productId: "P1", productName: null, quantity: 51, unit: "ST", unitPrice: null }],
        totalInclVat: 148.76,
        stockConfirmed: true,
        cutoffPassed: null,
        cutoffAt: null,
        deliveryReliability: null,
        co2KgPerKg: null,
        labels: null,
        tradeOff: "Requested product, confirmed portion only.",
        recommended: false,
        chosen: true,
      },
    ]);
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

  it("keeps a value unknown when one line does not state it", () => {
    const [mapped] = mapProposalOptions([
      option({
        lines: [
          line({ reliability: 0.97, carbon_kg_co2e_per_kg: 1.3, labels: ["EU_ORGANIC_FARMING"], cutoff_passed: false }),
          line({ product_id: "P2" }),
        ],
      }),
    ]);
    expect(mapped).toMatchObject({ deliveryReliability: null, co2KgPerKg: null, labels: null, cutoffPassed: null });
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
