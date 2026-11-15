import { useApi } from "@/api";
import type { AtlasFacts } from "@/api/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import comparison from "@/data/atlas-search-comparison.json";
import { formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useAsync } from "@/lib/use-async";

type T = ReturnType<typeof useT>;

/** What each Atlas index type is called on the page. */
export const ATLAS_INDEX_TYPES: Record<string, string> = {
  search: "Atlas Search",
  vectorSearch: "Atlas Vector Search",
};

/** The verdicts in data/atlas-search-comparison.json. */
export const ATLAS_VERDICTS: Record<string, string> = {
  better: "Better",
  equal: "Equal",
  slightly_worse: "Slightly worse",
};

export const ATLAS_LABELS = {
  vectors: "Product vectors",
  model: "Embedding model",
  products: "Products",
  size: "Database size",
  audit: "Audit log entries",
  version: "MongoDB version",
};

/** Plain names for the time-series collections; one the page does not know keeps its own name. */
export const ATLAS_SERIES_NAMES: Record<string, string> = {
  covers: "covers",
  deliveries: "deliveries",
  feedback: "feedback",
  forecasts: "forecasts",
  kitchen_stock: "stock counts",
  orders_history: "order history",
};

/** The day the store's search ranking changed, in the evening (#1646 and after): ISO dates compare as text. */
export const RANKING_CHANGED_ON = "2026-11-14";

/** True while the checked-in comparison is from before that change, so the page says so (#1953). */
export const measuredBeforeRankingChange = (measuredOn: string) => measuredOn <= RANKING_CHANGED_ON;

const number = (value: number | null, t: T) => (value === null ? t("unknown") : formatNumber(value));

function models(facts: AtlasFacts, t: T): string {
  if (facts.vectors === null) return t("unknown");
  if (facts.vectors.length === 0) return t("none yet");
  return facts.vectors
    .map((row) =>
      t("{model}, {dimensions} numbers per product", {
        model: row.model ?? t("unknown"),
        dimensions: number(row.dimensions, t),
      }),
    )
    .join("; ");
}

const vectorCount = (facts: AtlasFacts) =>
  facts.vectors === null ? null : facts.vectors.reduce((sum, row) => sum + row.count, 0);

/** The sentence under the counts says the same two numbers, or says that it does not know. */
function vectorSentence(facts: AtlasFacts | null, t: T): string {
  const vectors = facts ? vectorCount(facts) : null;
  const products = facts ? facts.products : null;
  // Each vector row counts products (store/atlas.py), so the sum is products with a vector. The
  // product count is an estimate: when it comes out below the vectors, the page does not guess.
  if (vectors === null || products === null || vectors > products) {
    return t("Product vectors come from MongoDB's own embedding API; how many products have one is unknown right now.");
  }
  return t("{vectors} of {products} products have a vector from MongoDB's own embedding API.", {
    vectors: formatNumber(vectors),
    products: formatNumber(products),
  });
}

function figures(facts: AtlasFacts, t: T): [string, string][] {
  const vectors = vectorCount(facts);
  return [
    [ATLAS_LABELS.vectors, number(vectors, t)],
    [ATLAS_LABELS.model, models(facts, t)],
    [ATLAS_LABELS.products, number(facts.products, t)],
    [ATLAS_LABELS.size, facts.dataMb === null ? t("unknown") : `${formatNumber(facts.dataMb)} MB`],
    [ATLAS_LABELS.audit, number(facts.auditEntries, t)],
    [ATLAS_LABELS.version, facts.mongodbVersion ?? t("unknown")],
  ];
}

function Live({ facts }: { facts: AtlasFacts }) {
  const t = useT();
  return (
    <>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
        {figures(facts, t).map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs text-muted-foreground">{t(label)}</dt>
            <dd className="font-semibold tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
      <div>
        <h3 id="atlas-indexes" className="font-medium">
          {t("Search indexes")}
        </h3>
        <ul aria-labelledby="atlas-indexes" className="list-disc pl-5">
          {facts.searchIndexes === null ? (
            <li>{t("unknown")}</li>
          ) : facts.searchIndexes.length === 0 ? (
            <li>{t("none yet")}</li>
          ) : (
            facts.searchIndexes.map((index) => (
              <li key={index.name}>
                <code>{index.name}</code>
                {`: ${t(ATLAS_INDEX_TYPES[index.type] ?? index.type)}, ${index.status ?? t("unknown")}`}
              </li>
            ))
          )}
        </ul>
      </div>
    </>
  );
}

function series(facts: AtlasFacts, t: T): string {
  if (facts.timeSeries === null) return t("unknown");
  // An empty collection is left out: it has nothing to show yet.
  const filled = facts.timeSeries.filter((row) => row.documents > 0);
  if (filled.length === 0) return t("none yet");
  return filled
    .map((row) => `${t(ATLAS_SERIES_NAMES[row.collection] ?? row.collection)} ${formatNumber(row.documents)}`)
    .join(" · ");
}

/**
 * What MongoDB Atlas holds and runs (#1383): live numbers from GET /atlas, and the measured
 * text-against-hybrid comparison from a checked-in file (data/atlas-search-comparison.json).
 */
export function AtlasCard() {
  const t = useT();
  const api = useApi();
  const facts = useAsync(() => api.getAtlasFacts());
  const live = facts.status === "ready" ? facts.data : null;
  const { totals } = comparison;
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2 id="about-atlas">{t("The data lives in MongoDB Atlas")}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {facts.status === "loading" && (
          <p role="status" className="text-muted-foreground">
            {t("Loading the counts…")}
          </p>
        )}
        {facts.status === "error" && (
          <p className="text-muted-foreground">{t("The live Atlas numbers are not available right now")}</p>
        )}
        {live && <Live facts={live} />}

        <div className="space-y-2">
          <h3 className="font-medium">{t("Search by words and by meaning")}</h3>
          <p>
            {vectorSentence(live, t)}{" "}
            {t("Hybrid search joins Atlas Search (words) and Atlas Vector Search (meaning) with $rankFusion.")}
          </p>
          <p>{t("The Buyer searches by words on stage; the Catalog page can search by meaning")}</p>
          <p>
            {t("Hybrid was better on {better} searches, equal on {equal} and slightly worse on {worse}.", {
              better: totals.better,
              equal: totals.equal,
              worse: totals.slightly_worse,
            })}
          </p>
          {measuredBeforeRankingChange(comparison.measured_on) && (
            <p className="text-muted-foreground">
              {t("Measured on the server on {date}, before the search ranking was changed on the evening of {changed}: the Catalog can show other results now.", {
                date: comparison.measured_on,
                changed: RANKING_CHANGED_ON,
              })}
            </p>
          )}
          <details>
            <summary className="cursor-pointer font-medium text-primary underline underline-offset-4">
              {t("Show the {count} searches", { count: comparison.queries.length })}
            </summary>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[36rem] text-left text-xs">
                <caption className="pb-1 text-left text-muted-foreground">
                  {t("The top 8 results for 10 searches, measured on the server on {date}.", {
                    date: comparison.measured_on,
                  })}
                </caption>
                <thead>
                  <tr className="border-b">
                    <th scope="col" className="py-1 pr-2">{t("Search")}</th>
                    <th scope="col" className="py-1 pr-2">{t("Words find")}</th>
                    <th scope="col" className="py-1 pr-2">{t("Hybrid finds")}</th>
                    <th scope="col" className="py-1">{t("Hybrid is")}</th>
                  </tr>
                </thead>
                <tbody>
                  {comparison.queries.map((row) => (
                    <tr key={row.query} className="border-b align-top last:border-0">
                      <th scope="row" className="py-1 pr-2 font-medium">{row.query}</th>
                      <td className="py-1 pr-2">{row.words}</td>
                      <td className="py-1 pr-2">{row.hybrid}</td>
                      <td className="py-1">{t(ATLAS_VERDICTS[row.verdict] ?? row.verdict)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </div>

        <div>
          <h3 id="atlas-features" className="font-medium">
            {t("Other Atlas features in use")}
          </h3>
          <ul aria-labelledby="atlas-features" className="list-disc space-y-1 pl-5">
            <li>{t("Atlas Search: one index over the English, Finnish and Swedish product names.")}</li>
            <li>
              {t("Time-series collections: {list}.", { list: live ? series(live, t) : t("unknown") })}
              {" "}
              {t("The weekly drift check is one aggregation over them.")}
            </li>
            <li>
              {t("Hash-chained audit log: each line stores the hash of the line before, so a changed line shows.")}
            </li>
            <li>{t("Decimal128 prices: money never rounds as a float.")}</li>
            <li>
              {t("Change streams: {list}", {
                list: live ? live.changeStreamCollections.join(", ") : t("unknown"),
              })}
            </li>
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}
