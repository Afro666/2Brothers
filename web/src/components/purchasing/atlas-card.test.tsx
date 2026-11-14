import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { atlasFactsMock } from "@/api/mock-atlas";
import type { AtlasFacts } from "@/api/types";
import { ApiError } from "@/api/types";
import comparison from "@/data/atlas-search-comparison.json";
import { renderApp } from "@/test/render";

const TITLE = "The data lives in MongoDB Atlas";
const SEARCH_NOTE = "The Buyer searches by words on stage; the Catalog page can search by meaning";

const withAtlas = (getAtlasFacts: () => Promise<AtlasFacts>) =>
  Object.assign(createMockApi(), { getAtlasFacts });

async function card() {
  const heading = await screen.findByRole("heading", { level: 2, name: TITLE });
  return within(heading.closest("section")!);
}

async function figures(view: Awaited<ReturnType<typeof card>>) {
  return Object.fromEntries(
    (await view.findAllByRole("term")).map((term) => [
      term.textContent,
      term.nextElementSibling?.textContent,
    ]),
  );
}

describe("the Atlas card on the About page", () => {
  beforeEach(() => localStorage.clear());

  it("shows the live vectors, the indexes and the size", async () => {
    renderApp("/about", withAtlas(async () => atlasFactsMock()));
    const view = await card();
    expect(await figures(view)).toMatchObject({
      "Product vectors": "17,546",
      "Embedding model": "voyage-4, 1,024 numbers per product",
      Products: "17,548",
      "Database size": "215 MB",
      "Audit log entries": "1,487",
      "MongoDB version": "8.0.37",
    });
    const indexes = view.getByRole("list", { name: "Search indexes" });
    expect(within(indexes).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "products_search: Atlas Search, READY",
      "products_vector: Atlas Vector Search, READY",
    ]);
    expect(view.getByText(SEARCH_NOTE)).toBeInTheDocument();
    expect(view.getByText(/\$rankFusion/)).toBeInTheDocument();
  });

  it("shows the measured comparison from the checked-in file", async () => {
    renderApp("/about", withAtlas(async () => atlasFactsMock()));
    const view = await card();
    const table = view.getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(10);
    expect(rows[0]).toHaveTextContent("lactose-free milk");
    expect(rows[0]).toHaveTextContent("Better");
    expect(rows[9]).toHaveTextContent("kermaa");
    expect(rows[9]).toHaveTextContent("Slightly worse");
    expect(view.getByText("Hybrid was better on 6 searches, equal on 2 and slightly worse on 2.")).toBeInTheDocument();
    const verdicts = comparison.queries.map((row) => row.verdict);
    expect(verdicts.filter((v) => v === "better")).toHaveLength(comparison.totals.better);
    expect(verdicts.filter((v) => v === "equal")).toHaveLength(comparison.totals.equal);
    expect(verdicts.filter((v) => v === "slightly_worse")).toHaveLength(comparison.totals.slightly_worse);
  });

  it("lists the other Atlas features with their live counts", async () => {
    renderApp("/about", withAtlas(async () => atlasFactsMock()));
    const view = await card();
    const features = view.getByRole("list", { name: "Other Atlas features in use" });
    expect(features).toHaveTextContent("Atlas Search");
    expect(features).toHaveTextContent("Time-series collections: covers (1,780), orders_history (1,050)");
    expect(features).toHaveTextContent("Hash-chained audit log");
    expect(features).toHaveTextContent("Decimal128");
    expect(features).toHaveTextContent("Change streams: proposals, approvals, audit_log");
  });

  it("shows unknown for a part that could not be read, never zero", async () => {
    renderApp(
      "/about",
      withAtlas(async () => ({
        ...atlasFactsMock(),
        dataMb: null,
        products: null,
        vectors: null,
        searchIndexes: null,
        timeSeries: null,
        auditEntries: null,
        mongodbVersion: null,
      })),
    );
    const view = await card();
    const shown = await figures(view);
    expect(shown["Product vectors"]).toBe("unknown");
    expect(shown["Database size"]).toBe("unknown");
    expect(shown["Audit log entries"]).toBe("unknown");
    expect(Object.values(shown)).not.toContain("0");
    expect(view.getByRole("list", { name: "Search indexes" })).toHaveTextContent("unknown");
    expect(view.getByRole("table")).toBeInTheDocument();     // the measured table still shows
  });

  it("shows both models while the vectors are being replaced", async () => {
    renderApp(
      "/about",
      withAtlas(async () => ({
        ...atlasFactsMock(),
        vectors: [
          { model: "voyage-4", dimensions: 1024, count: 17546 },
          { model: "nemotron-embed", dimensions: 2048, count: 120 },
        ],
      })),
    );
    const shown = await figures(await card());
    expect(shown["Product vectors"]).toBe("17,666");
    expect(shown["Embedding model"]).toBe(
      "voyage-4, 1,024 numbers per product; nemotron-embed, 2,048 numbers per product",
    );
  });

  it("keeps the page when the call fails", async () => {
    renderApp(
      "/about",
      withAtlas(async () => {
        throw new ApiError("GATEWAY_UNREACHABLE", "The gateway did not answer.");
      }),
    );
    const view = await card();
    expect(await view.findByText("The live Atlas numbers are not available right now")).toBeInTheDocument();
    expect(view.queryByText("The gateway did not answer.")).not.toBeInTheDocument();
    expect(view.getByRole("table")).toBeInTheDocument();
  });
});
