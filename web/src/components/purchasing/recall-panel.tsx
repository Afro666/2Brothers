import { RefreshCw, ShieldAlert } from "lucide-react";
import { useState } from "react";

import { ProductThumb } from "@/components/purchasing/product-thumb";
import { Button } from "@/components/ui/button";
import { formatDate, formatDateTime } from "@/lib/format";
import { useT, type TranslationVariables } from "@/lib/i18n";
import { TONE_CLASSES } from "@/lib/tone";
import { cn } from "@/lib/utils";
import type { RecallAlert, RecallCheck } from "@/types";

/**
 * What the inbox knows about recalls:
 * - `unavailable`: this gateway does not serve the recall routes yet.
 * - `unknown`: loading them failed, so nobody can say the open orders are clear.
 * - `ready`: the alerts that hit an open order (`affecting`), the active alerts no order holds
 *   (`unheld`: the product is in the kitchen's stock or recipes), and the last check (null: none ran).
 */
export type RecallStatus =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | { kind: "unknown"; message: string }
  | { kind: "ready"; affecting: number; lastCheck: RecallCheck | null; unheld?: RecallAlert[] };

function plural(count: number, t: (text: string, vars?: TranslationVariables) => string) {
  return count === 1
    ? t("1 recall affects your open order")
    : t("{count} recalls affect your open orders", { count });
}

/** Every sentence shape the monitor sends, with the text it becomes and the value to fill in. */
const RECALL_PATTERNS: [RegExp, string, string | null][] = [
  [/^in stock: (.+)$/, "In stock: {amount}", "amount"],
  [/^on the stock list: amount not counted$/, "On the stock list: amount not counted", null],
  [/^in recipes: (.+)$/, "In recipes: {names}", "names"],
  [/^on the open purchase proposal$/, "On the open purchase proposal", null],
  [/^Stop using it now\. Check your packs: only (.+) are recalled\.$/, "Stop using it now. Check your packs: only {lots} are recalled.", "lots"],
  [/^Stop using it now\. Check your packs\.$/, "Stop using it now. Check your packs.", null],
  [/^Do not use it until checked\. Check your packs: only (.+) are recalled\.$/, "Do not use it until checked. Check your packs: only {lots} are recalled.", "lots"],
  [/^Do not use it until checked\. Check your packs\.$/, "Do not use it until checked. Check your packs.", null],
  [/^Do not use it until checked\.$/, "Do not use it until checked.", null],
  [/^A person checks whether this notice is about your product\.$/, "A person checks whether this notice is about your product.", null],
];

export const RECALL_SENTENCES = RECALL_PATTERNS.map(([, template]) => template);

/**
 * The sentences the recall monitor sends for `where` and `next_step` (monitor/recalls.py),
 * through the dictionary. The lists of names, dates and lots inside stay as sent, and a
 * shape not listed here is shown as sent.
 */
export function recallSentence(text: string, t: (text: string, vars?: TranslationVariables) => string): string {
  for (const [pattern, template, name] of RECALL_PATTERNS) {
    const match = pattern.exec(text);
    if (match) return t(template, match[1] == null || name == null ? undefined : { [name]: match[1] });
  }
  return text;
}

/**
 * A recalled product the kitchen has (stock, recipes) that no open order holds. Nothing is
 * held, so there is no card for it below: the panel itself says what, where and what next.
 */
function UnheldRecall({ alert }: { alert: RecallAlert }) {
  const t = useT();
  const { recall } = alert;
  const product = alert.productName ?? alert.productId;
  const title = recall.title ?? t("Official recall notice");
  return (
    <li className="space-y-1 rounded-md border bg-background px-3 py-2 text-foreground">
      <p className="flex items-center gap-2 font-semibold">
        <ProductThumb en={alert.productName} brand={alert.match === "review" ? null : recall.brand} size="sm" />
        <span className="min-w-0 [overflow-wrap:anywhere]">
          {alert.match === "review"
            ? t("A recall notice may be about {product}.", { product })
            : t("{product} is recalled.", { product })}
        </span>
      </p>
      <p className="[overflow-wrap:anywhere]">
        {recall.date
          ? t("Food Authority notice, {date}:", { date: `${formatDate(recall.date)} ${recall.date.slice(0, 4)}` })
          : t("Food Authority notice:")}{" "}
        {recall.url && /^https:\/\//.test(recall.url) ? (
          <a className="font-medium underline" href={recall.url} target="_blank" rel="noreferrer">
            {title} <span className="sr-only">{t("(opens in a new tab)")}</span>
          </a>
        ) : (
          title
        )}
      </p>
      {alert.where.map((line) => (
        <p key={line} className="font-medium [overflow-wrap:anywhere]">
          {/* "in stock: ..." reads as a sentence start; a line nobody listed keeps the gateway's words. */}
          {recallSentence(line, t).replace(/^./, (first) => first.toUpperCase())}
        </p>
      ))}
      <p>
        {alert.match === "review"
          ? t("No open order holds it.")
          : t("No open order holds it. New orders leave it out.")}
      </p>
      {alert.nextStep ? (
        <p className="text-muted-foreground [overflow-wrap:anywhere]">{recallSentence(alert.nextStep, t)}</p>
      ) : null}
    </li>
  );
}

/**
 * The inbox banner and the "Check recalls now" button. A check runs the recall monitor
 * (Context.dev /v1/web/scrape on the Ruokavirasto list) and the inbox reloads with its
 * result. No recall is never claimed before a check has run.
 */
export function RecallPanel({
  status,
  onCheck,
}: {
  status: RecallStatus;
  /** Absent when the gateway cannot run a check. */
  onCheck?: () => Promise<void>;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status.kind === "loading") return null;
  if (status.kind === "unavailable") {
    return (
      <p className={cn("rounded-md border px-3 py-2 text-sm", TONE_CLASSES.neutral)}>
        {t("Recall check is not available on this server yet. Recalls are not checked here.")}
      </p>
    );
  }

  async function check() {
    if (!onCheck) return;
    setBusy(true);
    setError(null);
    try {
      await onCheck();
    } catch (e) {
      setError(t("Recall check failed: {message}. Recalls are unknown.", {
        message: e instanceof Error ? e.message : String(e),
      }));
    } finally {
      setBusy(false);
    }
  }

  const affecting = status.kind === "ready" ? status.affecting : null;
  const last = status.kind === "ready" ? status.lastCheck : null;
  const unheld = status.kind === "ready" ? (status.unheld ?? []) : [];
  let tone: keyof typeof TONE_CLASSES = "neutral";
  let headline: string;
  if (status.kind === "unknown") {
    tone = "warning";
    headline = t("Recalls unknown: {message}", { message: status.message });
  } else if (affecting && affecting > 0) {
    tone = "danger";
    headline = plural(affecting, t);
  } else if (unheld.length > 0) {
    // A review match only "may be about" the product and blocks nothing: no red banner for it alone.
    tone = unheld.every((alert) => alert.match === "review") ? "warning" : "danger";
    headline = unheld.length === 1
      ? t("1 recall matches a product in your kitchen")
      : t("{count} recalls match products in your kitchen", { count: unheld.length });
  } else if (last?.noticesUnread != null && last.noticesUnread > 0) {
    tone = "warning";
    headline = last.noticesUnread === 1
      ? t("1 new notice not read yet")
      : t("{count} new notices not read yet", { count: last.noticesUnread });
  } else if (last) {
    tone = "success";
    headline = t("No recall matches your open orders.");
  } else {
    headline = t("Recalls not checked yet.");
  }

  return (
    <section
      aria-label={t("Food recalls")}
      className={cn(
        "flex flex-col gap-3 rounded-lg border px-4 py-3 text-sm sm:flex-row sm:items-center sm:justify-between",
        TONE_CLASSES[tone],
      )}
    >
      <div className="min-w-0 space-y-1">
        <p role="status" className="flex items-center gap-2 font-semibold">
          <ShieldAlert aria-hidden className="size-4 shrink-0" />
          {headline}
        </p>
        {last ? (
          <p className="text-foreground">
            {t("Checked {count} Ruokavirasto notices, {date}.", {
              count: last.noticesScanned ?? t("an unknown number of"),
              date: formatDateTime(last.checkedAt),
            })}{" "}
            {last.source === "recording"
              ? `${t("From the recorded scrape of {date}, not a live one.", { date: formatDateTime(last.fetchedAt) })} ${
                  last.liveError == null
                    ? t("Shown from the recording.")
                    : last.liveError === "NO_KEY"
                      ? t("Context.dev key is not set on this server.")
                      : last.liveError === "TIMEOUT"
                        ? t("Context.dev was too slow.")
                        : t("Context.dev could not be read.")
                }`
              : t("Scraped live: {count} notices on the list.", {
                  count: last.noticesListed ?? t("an unknown number of"),
                })}
          </p>
        ) : (
          <p className="text-foreground">{t("Food Authority recalls, matched to your stock, your recipes and the lines on your open orders.")}</p>
        )}
        {unheld.length > 0 ? (
          <ul aria-label={t("Recalled products in your kitchen")} className="space-y-2 py-1">
            {unheld.map((alert) => (
              <UnheldRecall key={alert.eventId} alert={alert} />
            ))}
          </ul>
        ) : null}
        <p className="text-xs text-muted-foreground">
          {t("Powered by Context.dev")} <code>{last?.via.match(/\/v1\/web\/scrape/)?.[0] ?? "/v1/web/scrape"}</code>
        </p>
        {error ? (
          <p role="alert" className="text-danger">
            {error}
          </p>
        ) : null}
      </div>
      {onCheck ? (
        <Button type="button" variant="outline" className="shrink-0" disabled={busy} onClick={() => void check()}>
          <RefreshCw aria-hidden className={cn(busy && "animate-spin")} />
          {busy ? t("Checking recalls…") : t("Check recalls now")}
        </Button>
      ) : null}
    </section>
  );
}
