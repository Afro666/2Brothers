import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { mapAtlasFacts } from "@/api/http-atlas";

const URL = "/api/v1/kitchens/demo-kitchen/atlas";
// The example in docs/contract.md, "Atlas facts".
const answer = {
  mongodb_version: "8.0.37",
  data_mb: 215,
  products: 17548,
  vectors: [{ model: "voyage-4", dimensions: 1024, count: 17546 }],
  search_indexes: [
    { name: "products_search", type: "search", status: "READY", queryable: true },
    { name: "products_vector", type: "vectorSearch", status: "READY", queryable: true },
  ],
  time_series: [
    { collection: "covers", documents: 1780 },
    { collection: "orders_history", documents: 1050 },
  ],
  audit_entries: 1487,
  change_stream_collections: ["proposals", "approvals", "audit_log"],
};
const mapped = {
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

afterEach(() => vi.unstubAllGlobals());

describe("Atlas facts on the real gateway", () => {
  it("reads GET /atlas and maps the answer", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
      calls.push(`${init.method ?? "GET"} ${url}`);
      return new Response(JSON.stringify(answer), { status: 200 });
    });
    const api = createHttpApi("/api");
    expect(api.live!.has("getAtlasFacts")).toBe(true);
    await expect(api.getAtlasFacts()).resolves.toEqual(mapped);
    expect(calls).toEqual([`GET ${URL}`]);
  });

  it("keeps an unknown part unknown, never zero", () => {
    const unknown = {
      ...answer,
      mongodb_version: null,
      data_mb: null,
      products: null,
      vectors: null,
      search_indexes: null,
      time_series: null,
      audit_entries: null,
    };
    expect(mapAtlasFacts(unknown)).toEqual({
      ...mapped,
      mongodbVersion: null,
      dataMb: null,
      products: null,
      vectors: null,
      searchIndexes: null,
      timeSeries: null,
      auditEntries: null,
    });
  });

  it("keeps an empty list as read and empty", () => {
    expect(mapAtlasFacts({ ...answer, vectors: [], time_series: [] })).toMatchObject({
      vectors: [],
      timeSeries: [],
    });
  });

  it("keeps a missing status unknown", () => {
    const index = { name: "products_vector", type: "vectorSearch", status: null, queryable: null };
    expect(mapAtlasFacts({ ...answer, search_indexes: [index] }).searchIndexes).toEqual([index]);
  });

  it.each([
    ["a count as a string", { ...answer, products: "17548" }],
    ["a negative size", { ...answer, data_mb: -1 }],
    ["vectors that are not a list", { ...answer, vectors: { model: "voyage-4" } }],
    ["an index without a name", { ...answer, search_indexes: [{ type: "search" }] }],
  ])("refuses %s", (_, body) => {
    expect(() => mapAtlasFacts(body)).toThrow(/unexpected shape/);
  });
});
