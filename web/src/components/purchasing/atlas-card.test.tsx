import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { atlasFactsMock } from "@/api/mock-atlas";
import type { AtlasFacts } from "@/api/types";
import { ApiError } from "@/api/types";
import { measuredBeforeRankingChange } from "@/components/purchasing/atlas-card";
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
    // The sentence under the counts repeats the same two numbers (#1838).
    expect(view.getByText(/17,546 of 17,548 products have a vector from MongoDB's own embedding API\./)).toBeInTheDocument();
    expect(view.queryByText(/Every product has a vector/)).not.toBeInTheDocument();
  });

  it("shows the measured comparison from the checked-in file", async () => {
    renderApp("/about", withAtlas(async () => atlasFactsMock()));
    const view = await card();
    const table = view.getByRole("table");
    // Folded behind "Show the 10 searches": closed until the reader opens it (#1838).
    const fold = table.closest("details")!;
    expect(fold).not.toHaveAttribute("open");
    expect(within(fold).getByText("Show the 10 searches").tagName).toBe("SUMMARY");
    expect(view.getByText(/^Measured on the server on 2026-11-14, before the search ranking was changed/)).toBeInTheDocument();
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

  it("says the comparison predates the ranking change only while it does", () => {
    // The checked-in file is still the 2026-11-14 one: the render test above sees the sentence.
    expect(measuredBeforeRankingChange(comparison.measured_on)).toBe(true);
    expect(measuredBeforeRankingChange("2026-11-13")).toBe(true);
    expect(measuredBeforeRankingChange("2026-11-15")).toBe(false);
  });

  it("lists the other Atlas features with their live counts", async () => {
    renderApp("/about", withAtlas(async () => atlasFactsMock()));
    const view = await card();
    const features = view.getByRole("list", { name: "Other Atlas features in use" });
    expect(features).toHaveTextContent("Atlas Search");
    expect(features).toHaveTextContent(
      "Time-series collections: covers 1,780 · order history 1,050. The weekly drift check is one aggregation over them.",
    );
    expect(features).toHaveTextContent("Hash-chained audit log");
    expect(features).toHaveTextContent("Decimal128");
    expect(features).toHaveTextContent("Change streams: proposals, approvals, audit_log");
  });

  it("leaves an empty time-series collection out and gives the others plain names", async () => {
    renderApp(
      "/about",
      withAtlas(async () => ({
        ...atlasFactsMock(),
        timeSeries: [
          { collection: "kitchen_stock", documents: 32218 },
          { collection: "feedback", documents: 0 },
          { collection: "new_one", documents: 3 },
        ],
      })),
    );
    const features = (await card()).getByRole("list", { name: "Other Atlas features in use" });
    await within(features).findByText(/stock counts 32,218 · new_one 3\./);
    expect(features).not.toHaveTextContent("feedback");
    expect(features).not.toHaveTextContent("kitchen_stock");
  });

  it("shows the search fold in Finnish with a note that the rows are English", async () => {
    localStorage.setItem("purchasing-language", "fi");
    renderApp("/about", withAtlas(async () => atlasFactsMock()));
    const summary = await screen.findByText("Näytä 10 hakua (haut ja tulokset englanniksi, kuten ne mitattiin)");
    const fold = summary.closest("details")!;
    expect(fold).not.toHaveAttribute("open");
    expect(within(fold).getByRole("table")).toBeInTheDocument();
    expect(await screen.findByText(/17\s546 tuotteella 17\s548 tuotteesta on vektori/)).toBeInTheDocument();
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
    expect(view.getByText(/how many products have one is unknown right now/)).toBeInTheDocument();
    expect(view.queryByText(/products have a vector/)).not.toBeInTheDocument();
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
    // More vectors than the (estimated) product count: the sentence does not guess.
    expect(screen.getByText(/how many products have one is unknown right now/)).toBeInTheDocument();
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
