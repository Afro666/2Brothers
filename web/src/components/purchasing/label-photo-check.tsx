import { Camera } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useApi } from "@/api";
import type { LabelPhotoRead, LabelPleaseCheck, LabelWord } from "@/api/types";
import { ApiError } from "@/api/types";
import { Button } from "@/components/ui/button";
import { EU_ALLERGENS } from "@/lib/allergens";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { downscalePhoto } from "@/lib/shelf-photo";
import type { Order } from "@/types";

/** The name people know; the gateway's `model` field is the id (`nemotron-3.5-super-vl`). */
const MODEL_NAME = "Nemotron 3.5 Super VL";

/** GS1 codes the label table maps to that are not one of the 14 EU groups. */
export const MORE_ALLERGENS: Record<string, string> = {
  ML: "Lactose", UW: "Wheat", NR: "Rye", GB: "Barley", GS: "Spelt", GK: "Kamut", GO: "Oats",
  SA: "Almond", SC: "Cashew", SH: "Hazelnut", SM: "Macadamia", SP: "Pecan", SR: "Brazil nut", ST: "Pistachio", SW: "Walnut",
};
const NAMES: Record<string, string> = { ...Object.fromEntries(EU_ALLERGENS.map((a) => [a.code, a.name])), ...MORE_ALLERGENS };

type Translate = ReturnType<typeof useT>;

const allergenName = (code: string, t: Translate) => (NAMES[code] ? t(NAMES[code]) : code);

/** The gateway's error codes in plain words (docs/contract.md, "Check a package's allergen label from a photo"). */
export function labelErrorText(problem: unknown, t: Translate): string {
  const code = problem instanceof ApiError ? problem.code : "";
  const status = problem instanceof ApiError ? problem.status : undefined;
  // api/http.ts reports every 429 as RATE_LIMITED; LABEL_PHOTO_BUSY is the gateway's own code.
  if (code === "LABEL_PHOTO_BUSY" || code === "RATE_LIMITED") return t("Another label is being read. Wait for it, then try again.");
  if (code === "VISION_NOT_CONFIGURED" || code === "VISION_UNAVAILABLE" || code === "VISION_TIMEOUT") {
    return t("The model is not answering right now. Read the label yourself, or try again later.");
  }
  if (code === "VISION_REPLY_INVALID" || code === "INVALID_RESPONSE") {
    return t("The model's answer could not be used. Try again, or read the label yourself.");
  }
  if (code === "IMAGE_TOO_LARGE") return t("The photo is too large. Take it again from a little further away.");
  if (code === "NOT_AN_IMAGE") return t("This file is not a photo. Choose a JPEG or PNG photo.");
  if (code === "ORDER_NOT_FOUND" || code === "PRODUCT_NOT_FOUND") {
    return t("The server does not know this order or product. Read the label yourself.");
  }
  if (code === "NOT_FOUND" || status === 404) return t("Reading a label photo is not switched on on this server yet. Read the label yourself.");
  const message = problem instanceof Error ? problem.message : String(problem);
  return t("The label was not read: {error} Read the label yourself.", { error: message });
}

const REASONS: Record<LabelPleaseCheck, string> = {
  NO_STATEMENT_READ: "Please check: we could not read an allergen statement. That does not mean there are no allergens. Read the label yourself.",
  WORD_UNKNOWN: "Please check: some words on the label are not in our allergen table. Read the label yourself.",
  PRODUCT_MISMATCH: "Please check: this may be another product than the one ordered.",
  PRODUCT_NOT_CONFIRMED: "Please check: we could not confirm that this label is the delivered product.",
};

/** The one plain sentence for the outcome. There is no green or "safe" outcome: a model can miss a word. */
export function outcomeText(read: LabelPhotoRead, t: Translate): string {
  const listed = (rows: LabelWord[]) => [...new Set(rows.map((row) => allergenName(row.code, t)))].join(", ");
  switch (read.outcome) {
    case "EXCLUDED_ALLERGEN":
      return t("The label lists {allergens}, which this kitchen excludes. Do not use it: a person must check.", {
        allergens: [...new Set(read.excludedHits.map((hit) => allergenName(hit.code, t)))].join(", "),
      });
    case "PLEASE_CHECK":
      return t(REASONS[read.pleaseCheck[0] ?? "NO_STATEMENT_READ"]);
    case "DIFFERS":
      return t("The label we read differs from the catalog. Read the label yourself and decide.");
    case "CATALOG_UNKNOWN": {
      const all = listed([...read.label.contains, ...read.label.mayContain]);
      return all
        ? t("The catalog has no allergen data for this product. The label says: {allergens}. Read the label yourself before use.", { allergens: all })
        : t("The catalog has no allergen data for this product. Read the label yourself before use.");
    }
    case "AGREES":
      return t("The label we read agrees with the catalog. Read the label yourself before use.");
  }
}

function WordList({ title, rows }: { title: string; rows: LabelWord[] }) {
  const t = useT();
  return (
    <p className="break-words">
      <span className="font-medium">{title}</span>{" "}
      {rows.length
        ? rows.map((row) => `“${row.word}” (${allergenName(row.code, t)})`).join(", ")
        : t("nothing read")}
    </p>
  );
}

function Outcome({ read }: { read: LabelPhotoRead }) {
  const t = useT();
  const warning = read.outcome === "EXCLUDED_ALLERGEN";
  const check = read.outcome === "PLEASE_CHECK" || read.outcome === "DIFFERS";
  const seconds = read.durationMs != null ? (read.durationMs / 1000).toFixed(1) : null;
  return (
    <div className="space-y-2 text-sm" data-testid="label-photo-result">
      {/* No green and no tick for AGREES: the person still reads the label. */}
      <p
        role={warning ? "alert" : "status"}
        className={warning ? "font-semibold text-destructive" : check ? "font-medium text-warning" : "font-medium"}
      >
        {outcomeText(read, t)}
      </p>
      {/* Every reason to check that the headline does not already say (an excluded hit can have them too). */}
      {(read.outcome === "PLEASE_CHECK" ? read.pleaseCheck.slice(1) : read.pleaseCheck).map((reason) => (
        <p key={reason} className="text-warning">{t(REASONS[reason])}</p>
      ))}
      <WordList title={t("Contains:")} rows={read.label.contains} />
      <WordList title={t("May contain:")} rows={read.label.mayContain} />
      {read.label.unknownWords.length ? (
        <p className="break-words">
          <span className="font-medium">{t("Not in our allergen table:")}</span> {read.label.unknownWords.map((w) => `“${w}”`).join(", ")}
        </p>
      ) : null}
      {read.differences.length ? (
        <ul className="list-disc space-y-0.5 pl-5">
          {read.differences.map((row, i) => <li key={`${row.code}-${i}`}>{row.text}</li>)}
        </ul>
      ) : null}
      <p className="text-muted-foreground">
        {seconds != null ? t("Read by {model} in {seconds} s.", { model: MODEL_NAME, seconds }) : t("Read by {model}.", { model: MODEL_NAME })}{" "}
        {t("The photo is not saved. It does not change the catalog, the order or the stock.")}
      </p>
    </div>
  );
}

/** "Photo of the label" for each line of a placed (delivered) order (#1175). Read-only. */
export function LabelPhotoCheck({ order }: { order: Order }) {
  const t = useT();
  const api = useApi();
  const { session, status } = useSession();
  const inputs = useRef<Record<string, HTMLInputElement | null>>({});
  const latest = useRef(0);
  const [reading, setReading] = useState<string | null>(null);
  const [result, setResult] = useState<{ productId: string; read: LabelPhotoRead } | null>(null);
  const [error, setError] = useState<{ productId: string; text: string } | null>(null);
  useEffect(() => () => { latest.current += 1; }, []);
  const allowed = status === "signed-in" && session?.kind === "human" && (session.role === "approver" || session.role === "chef");
  const lines = [...new Map(order.lines.map((line) => [line.product.id, line.product])).values()];
  if (!lines.length) return null;

  async function readPhoto(productId: string, file: File | undefined) {
    if (!file || reading || !allowed) return;
    const turn = ++latest.current;
    setReading(productId);
    setResult(null);
    setError(null);
    try {
      const read = await api.readLabelPhoto(order.id, productId, await downscalePhoto(file), session?.role === "chef" ? "chef" : "human");
      if (turn === latest.current) setResult({ productId, read });
    } catch (problem) {
      if (turn === latest.current) setError({ productId, text: labelErrorText(problem, t) });
    } finally {
      if (turn === latest.current) setReading(null);
    }
  }

  return (
    <section className="space-y-3 rounded-lg border bg-card p-4" aria-labelledby="label-photo-title">
      <div className="space-y-1">
        <h2 id="label-photo-title" className="text-base font-semibold">{t("Check an allergen label")}</h2>
        <p className="max-w-prose text-sm text-muted-foreground">
          {t("Take a photo of a delivered package's label. Nemotron reads the allergens and compares them with the catalog and your allergen rule. The photo does not change the catalog.")}
        </p>
      </div>
      {!allowed && status !== "loading" ? <p className="text-sm text-muted-foreground">{t("A chef or approver can check a label.")}</p> : null}
      <ul className="divide-y">
        {lines.map((product) => {
          const name = product.names.en;
          const label = t("Photo of the label: {product}", { product: name });
          return (
            <li key={product.id} className="space-y-2 py-3">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <p className="min-w-0 break-words text-sm font-medium">{name}</p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={!allowed || reading !== null}
                  aria-label={label}
                  onClick={() => inputs.current[product.id]?.click()}
                >
                  <Camera aria-hidden="true" />
                  {t("Photo of the label")}
                </Button>
                <input
                  ref={(node) => { inputs.current[product.id] = node; }}
                  type="file"
                  accept="image/*"
                  // On a phone this opens the back camera; a laptop shows the file dialog.
                  capture="environment"
                  className="sr-only"
                  tabIndex={-1}
                  aria-label={t("Choose a label photo for {product}", { product: name })}
                  disabled={!allowed || reading !== null}
                  onChange={(event) => {
                    const file = event.currentTarget.files?.[0];
                    event.currentTarget.value = ""; // the same photo can be chosen again
                    void readPhoto(product.id, file);
                  }}
                />
              </div>
              {reading === product.id ? <p role="status" className="text-sm">{t("Reading the label. This may take a few seconds.")}</p> : null}
              {error?.productId === product.id ? <p role="alert" className="text-sm text-destructive">{error.text}</p> : null}
              {result?.productId === product.id ? <Outcome read={result.read} /> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
