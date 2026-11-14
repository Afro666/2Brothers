import type { AtlasFacts } from "@/api/types";

/**
 * Sample numbers for the mock API: the example in docs/contract.md, "Atlas facts". Against
 * the gateway they come from GET /atlas (api/http-atlas.ts).
 */
export function atlasFactsMock(): AtlasFacts {
  return {
    mongodbVersion: "8.0.37",
    dataMb: 215,
    products: 17548,
    vectors: [{ model: "voyage-4", dimensions: 1024, count: 17546 }],
    searchIndexes: [
      { name: "products_search", type: "search", status: "READY", queryable: true },
      { name: "products_vector", type: "vectorSearch", status: "READY", queryable: true },
    ],
    timeSeries: [
      { collection: "covers", documents: 1780 },
      { collection: "orders_history", documents: 1050 },
    ],
    auditEntries: 1487,
    changeStreamCollections: ["proposals", "approvals", "audit_log"],
  };
}
