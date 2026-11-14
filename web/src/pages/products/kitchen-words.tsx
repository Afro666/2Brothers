import { useEffect, useId, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/api";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useAsync } from "@/lib/use-async";
import type { Product } from "@/types";

/** How long the search waits after typing before it calls the catalog search. */
export const WORD_SEARCH_DEBOUNCE_MS = 250;
/** The first few of a long catalog result, so the row stays short. */
const MAX_RESULTS = 8;

type Found = { query: string; status: "loading" | "ready" | "error"; products: Product[]; error: string };

/** A small catalog search under one word: choosing a product links the word to it. */
function LinkSearch({
  phrase,
  busy,
  onChoose,
  onCancel,
}: {
  phrase: string;
  busy: boolean;
  onChoose: (product: Product) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const api = useApi();
  const inputId = useId();
  const [query, setQuery] = useState("");
  // Results carry the text they answer, so a list for old text never shows under new text.
  const [found, setFound] = useState<Found | null>(null);
  const trimmed = query.trim();

  useEffect(() => {
    if (trimmed.length < 2) {
      setFound(null);
      return;
    }
    let active = true;
    setFound({ query: trimmed, status: "loading", products: [], error: "" });
    const timer = window.setTimeout(() => {
      api
        .searchProducts(trimmed)
        .then((products) => {
          if (active) setFound({ query: trimmed, status: "ready", products: products.slice(0, MAX_RESULTS), error: "" });
        })
        .catch((cause: unknown) => {
          if (active) {
            setFound({
              query: trimmed,
              status: "error",
              products: [],
              error: cause instanceof Error ? cause.message : String(cause),
            });
          }
        });
    }, WORD_SEARCH_DEBOUNCE_MS);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [trimmed, api]);

  const shown = found && found.query === trimmed ? found : null;
  return (
    <div className="space-y-2 rounded-md border p-3">
      <label htmlFor={inputId} className="block text-sm font-medium">
        {t("Find a product for “{phrase}”", { phrase })}
      </label>
      <Input
        id={inputId}
        type="search"
        autoFocus
        autoComplete="off"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <div role="status" aria-live="polite" className="text-sm text-muted-foreground">
        {trimmed.length < 2 ? t("Type at least 2 letters.") : null}
        {shown?.status === "loading" ? t("Searching…") : null}
        {shown?.status === "error" ? shown.error : null}
        {shown?.status === "ready" && shown.products.length === 0 ? t("No product found.") : null}
      </div>
      {shown?.status === "ready" && shown.products.length > 0 ? (
        <ul className="space-y-1">
          {shown.products.map((product) => (
            <li key={product.id}>
              <Button
                type="button"
                variant="outline"
                className="h-auto w-full justify-start py-2 text-left whitespace-normal"
                disabled={busy}
                onClick={() => onChoose(product)}
              >
                <span className="min-w-0 break-words">
                  {product.names.en}
                  {product.vendorName ? <span className="text-muted-foreground"> · {product.vendorName}</span> : null}
                </span>
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={onCancel}>
        {t("Cancel")}
      </Button>
    </div>
  );
}

/**
 * The words of requests that matched no product, and the kitchen's own names for products.
 * Linking a word to a product makes the next request that uses it go to that product.
 */
export function KitchenWords() {
  const t = useT();
  const api = useApi();
  const words = useAsync(() => api.getKitchenWords(), [api]);
  const [linking, setLinking] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function change(action: () => Promise<void>, done: string) {
    setBusy(true);
    setError("");
    try {
      await action();
      setLinking(null);
      toast.success(done);
      words.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  const row = "flex flex-wrap items-center justify-between gap-x-4 gap-y-2";
  return (
    <div className="space-y-6 border-t pt-6">
      {words.status === "loading" ? <LoadingState label={t("Loading the kitchen's words")} /> : null}
      {words.status === "error" ? <ErrorState message={words.error.message} onRetry={words.reload} /> : null}
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {words.status === "ready" ? (
        <>
          <section className="space-y-3" aria-labelledby="unknown-words-heading">
            <div>
              <h2 id="unknown-words-heading" className="text-lg font-semibold">
                {t("Words we did not know")}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("Words from requests that matched no product.")}
              </p>
            </div>
            {words.data.unknownItems.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("Nothing asked for that we did not find.")}</p>
            ) : (
              <ul className="divide-y rounded-lg border">
                {words.data.unknownItems.map((item) => (
                  <li key={item.phrase} className="space-y-3 p-3">
                    <div className={row}>
                      <p className="min-w-0 break-words">
                        <span className="font-medium">{item.phrase}</span>{" "}
                        <span className="text-sm tabular-nums text-muted-foreground">
                          {item.times === 1
                            ? t("asked 1 time")
                            : t("asked {count} times", { count: formatNumber(item.times) })}
                        </span>
                      </p>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          aria-label={t("Link “{phrase}” to a product", { phrase: item.phrase })}
                          aria-expanded={linking === item.phrase}
                          disabled={busy}
                          onClick={() => setLinking(linking === item.phrase ? null : item.phrase)}
                        >
                          {t("Link to a product")}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={t("Forget “{phrase}”", { phrase: item.phrase })}
                          disabled={busy}
                          onClick={() =>
                            void change(() => api.forgetWord(item.phrase), t("“{phrase}” forgotten", { phrase: item.phrase }))
                          }
                        >
                          {t("Forget")}
                        </Button>
                      </div>
                    </div>
                    {linking === item.phrase ? (
                      <LinkSearch
                        phrase={item.phrase}
                        busy={busy}
                        onCancel={() => setLinking(null)}
                        onChoose={(product) =>
                          void change(
                            () => api.linkWord(item.phrase, product.id),
                            t("“{phrase}” now goes to {product}", { phrase: item.phrase, product: product.names.en }),
                          )
                        }
                      />
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="space-y-3" aria-labelledby="own-names-heading">
            <h2 id="own-names-heading" className="text-lg font-semibold">
              {t("Your own names for products")}
            </h2>
            {words.data.aliases.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t("No own names yet. Link a word above, and a request that uses it goes to that product.")}
              </p>
            ) : (
              <ul className="divide-y rounded-lg border">
                {words.data.aliases.map((alias) => (
                  <li key={alias.phrase} className={`${row} p-3`}>
                    <p className="min-w-0 break-words">
                      <span className="font-medium">{alias.phrase}</span>
                      <span aria-hidden="true"> → </span>
                      <span className="sr-only">{t("goes to")}</span>
                      {alias.productName}{" "}
                      <span className="text-sm tabular-nums text-muted-foreground">
                        {alias.uses === 1 ? t("used 1 time") : t("used {count} times", { count: formatNumber(alias.uses) })}
                      </span>
                    </p>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={t("Remove the name “{phrase}”", { phrase: alias.phrase })}
                      disabled={busy}
                      onClick={() =>
                        void change(() => api.forgetWord(alias.phrase), t("“{phrase}” removed", { phrase: alias.phrase }))
                      }
                    >
                      {t("Remove")}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
