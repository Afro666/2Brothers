import { object, text } from "@/api/gateway-map";
import type { AtlasFacts, AtlasSearchIndex, AtlasVectors, Api } from "@/api/types";
import { ApiError } from "@/api/types";

/** The gateway request of api/http.ts: a path under the base URL, the parsed JSON back. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

function invalid(what: string): never {
  throw new ApiError("INVALID_RESPONSE", `The gateway sent ${what} in an unexpected shape.`);
}

function count(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) invalid(what);
  return value;
}

/** null is unknown and stays null; anything else must have the right shape. */
function maybe<T>(value: unknown, read: (value: unknown) => T): T | null {
  return value === null || value === undefined ? null : read(value);
}

function list<T>(value: unknown, what: string, read: (row: Record<string, unknown>) => T): T[] {
  if (!Array.isArray(value)) invalid(what);
  return value.map((row) => read(object(row, what)));
}

const optionalText = (value: unknown, what: string) => maybe(value, (v) => text(v, what));

function vectors(row: Record<string, unknown>): AtlasVectors {
  return {
    model: optionalText(row.model, "the embedding model"),
    dimensions: maybe(row.dimensions, (v) => count(v, "the vector size")),
    count: count(row.count, "the vector count"),
  };
}

function searchIndex(row: Record<string, unknown>): AtlasSearchIndex {
  const queryable = row.queryable;
  if (queryable !== null && queryable !== undefined && typeof queryable !== "boolean") {
    invalid("the index state");
  }
  return {
    name: text(row.name, "the index name"),
    type: text(row.type, "the index type"),
    status: optionalText(row.status, "the index status"),
    queryable: typeof queryable === "boolean" ? queryable : null,
  };
}

/** `GET /atlas` -> the Atlas card on the About page. Contract: docs/contract.md, "Atlas facts". */
export function mapAtlasFacts(body: unknown): AtlasFacts {
  const row = object(body, "the Atlas facts");
  const names = row.change_stream_collections;
  return {
    mongodbVersion: optionalText(row.mongodb_version, "the MongoDB version"),
    dataMb: maybe(row.data_mb, (v) => count(v, "the database size")),
    products: maybe(row.products, (v) => count(v, "the product count")),
    vectors: maybe(row.vectors, (v) => list(v, "the vectors", vectors)),
    searchIndexes: maybe(row.search_indexes, (v) => list(v, "the search indexes", searchIndex)),
    timeSeries: maybe(row.time_series, (v) =>
      list(v, "the time-series collections", (series) => ({
        collection: text(series.collection, "a collection name"),
        documents: count(series.documents, "a document count"),
      })),
    ),
    auditEntries: maybe(row.audit_entries, (v) => count(v, "the audit log length")),
    changeStreamCollections: Array.isArray(names)
      ? names.map((name) => text(name, "a watched collection"))
      : invalid("the watched collections"),
  };
}

/** Atlas facts against the real gateway (gateway/atlas_routes.py). `kitchen` is `/v1/kitchens/{id}`. */
export function createAtlasHttp(call: GatewayCall, kitchen: string): Pick<Api, "getAtlasFacts"> {
  return {
    async getAtlasFacts() {
      return mapAtlasFacts(await call(`${kitchen}/atlas`));
    },
  };
}
