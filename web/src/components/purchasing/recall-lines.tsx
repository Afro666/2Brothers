import { ArrowDown, ExternalLink, ShieldAlert } from "lucide-react";

import { formatDate, formatEur, formatNumber } from "@/lib/format";
import { translate, useT, type TranslationVariables } from "@/lib/i18n";
import { TONE_CLASSES } from "@/lib/tone";
import { cn } from "@/lib/utils";
import type { Order, RecallAlert, RecallMatch } from "@/types";

const BADGE = "rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap";

export const MATCH_TEXT: Record<RecallMatch, string> = {
  exact: "Exact match: the notice's EAN is this product's.",
  possible: "Possible match: same brand and product word. Treat it as recalled until the lot is checked.",
  review: "Needs a person: the notice names no brand and no EAN.",
};

export const REPLAN_ERROR_TEXT: Record<string, string> = {
  KITCHEN_POLICY_UNKNOWN: "The kitchen's allergen policy is unknown, so a safe replacement could not be planned.",
  NO_SAFE_REPLACEMENT: "No safe replacement was found.",
  REPLACEMENT_SHORTFALL: "A replacement could not cover the full quantity.",
  REPLACEMENT_UNAVAILABLE: "The replacement is unavailable.",
};

type Translate = (text: string, vars?: TranslationVariables) => string;

/**
 * Why the order cannot be approved because of a recall; null when it can. A blocked line
 * that is still on the order holds the approval: the total would include recalled goods.
 */
export function recallHold(
  alerts: RecallAlert[] | undefined,
  order: Order | undefined,
  t: Translate = (text, vars) => translate("en", text, vars),
): string | null {
  const held = alerts?.find(
    (alert) =>
      alert.lineStatus === "BLOCKED_BY_RECALL" && order?.lines.some((line) => line.product.id === alert.productId),
  );
  return held
    ? t(
        held.replacement
          ? "{product} is blocked by a recall. This order cannot be approved. Reject it and approve the replacement order instead."
          : "{product} is blocked by a recall. This order cannot be approved. No replacement is proposed yet. You can reject this order.",
        { product: held.productName ?? held.productId },
      )
    : null;
}

/** The recalled lines of one order, each with its notice and separate replacement proposal. */
export function RecallLines({ alerts }: { alerts: RecallAlert[] }) {
  const t = useT();
  if (alerts.length === 0) return null;
  return (
    <section className="space-y-3" aria-label={t("Recalls on this order")}>
      {alerts.map((alert) => (
        <RecallLine key={`${alert.eventId}-${alert.orderId ?? "no-order"}`} alert={alert} />
      ))}
    </section>
  );
}

function RecallLine({ alert }: { alert: RecallAlert }) {
  const t = useT();
  const blocked = alert.lineStatus === "BLOCKED_BY_RECALL";
  const { recall } = alert;
  return (
    <article className="space-y-2">
      <div className={cn("space-y-2 rounded-md border px-3 py-2 text-sm", TONE_CLASSES[blocked ? "danger" : "warning"])}>
        <div className="flex flex-wrap items-center gap-2">
          <ShieldAlert aria-hidden className="size-4 shrink-0" />
          <span className="font-semibold">{blocked ? t("Blocked by recall") : t("Recall to check")}</span>
          <span className={cn(BADGE, "border-current")}>{alert.match}</span>
        </div>
        <div className="font-medium break-words text-foreground">
          {alert.productName ?? t("Product name unknown")} <span className="text-muted-foreground">({alert.productId})</span>
        </div>
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-foreground">
          <dt className="text-muted-foreground">{t("Notice")}</dt>
          <dd className="break-words">
            <span lang="fi">{recall.title ?? t("untitled")}</span> · Ruokavirasto
          </dd>
          <dt className="text-muted-foreground">{t("Date")}</dt>
          <dd>{recall.date ? `${formatDate(recall.date)} ${recall.date.slice(0, 4)}` : t("unknown")}</dd>
          <dt className="text-muted-foreground">{t("Lot")}</dt>
          <dd className="break-words">
            {recall.lot ?? <span className="text-warning">{t("not stated: every pack is in doubt")}</span>}
          </dd>
          {recall.recalledProduct ? (
            <>
              <dt className="text-muted-foreground">{t("Recalled")}</dt>
              <dd className="break-words" lang="fi">
                {recall.recalledProduct}
                {recall.packageSize ? `, ${recall.packageSize}` : ""}
              </dd>
            </>
          ) : null}
        </dl>
        <p className="text-foreground">{t(MATCH_TEXT[alert.match])}</p>
        <p className="text-foreground">{alert.nextStep}</p>
        {alert.status === "dismissed" ? (
          <p className="text-foreground">
            {t("Dismissed by {name}: {reason}", {
              name: alert.dismissedBy ?? t("unknown"),
              reason: alert.dismissReason ?? t("no reason recorded"),
            })}
          </p>
        ) : null}
        {recall.url ? (
          <a
            href={recall.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-medium underline underline-offset-2"
          >
            {t("Open the notice ({host})", { host: new URL(recall.url).hostname })}
            <ExternalLink aria-hidden className="size-3.5" />
            <span className="sr-only">{t("(opens in a new tab)")}</span>
          </a>
        ) : (
          <span>{t("source unknown")}</span>
        )}
      </div>
      {blocked ? <Replacement alert={alert} /> : null}
    </article>
  );
}

function Replacement({ alert }: { alert: RecallAlert }) {
  const t = useT();
  const replacement = alert.replacement;
  if (!replacement) {
    const reason = alert.replanError
      ? (REPLAN_ERROR_TEXT[alert.replanError] ?? "The replacement order could not be prepared.")
      : null;
    return (
      <div
        className={cn("rounded-md border px-3 py-2 text-sm", TONE_CLASSES[alert.replanError ? "warning" : "neutral"])}
      >
        <p className="font-medium">
          {alert.replanError ? t("The replacement order could not be made.") : t("No replacement order has been proposed.")}
        </p>
        <p className="text-foreground">{reason ? `${t(reason)} ` : ""}{t("Approval of the held order stays locked.")}</p>
        {alert.replacementIdeas.length > 0 ? (
          <p className="text-foreground">
            {t("Ideas from other brands: {ideas}", {
              ideas: alert.replacementIdeas.map((idea) => idea.name ?? idea.productId).join("; "),
            })}
          </p>
        ) : null}
      </div>
    );
  }
  return (
    <div className={cn("ml-3 space-y-1 rounded-md border px-3 py-2 text-sm", TONE_CLASSES.success)}>
      <div className="flex items-center gap-2 font-semibold">
        <ArrowDown aria-hidden className="size-4 shrink-0" />
        {t("Replacement order")}
      </div>
      <ul className="space-y-1 text-foreground">
        {replacement.lines.map((line) => (
          <li key={line.productId} className="break-words">
            {formatNumber(line.quantity)} {line.unit} · {line.productName ?? t("Product name unknown")}{" "}
            <span className="text-muted-foreground">({line.productId})</span>
          </li>
        ))}
      </ul>
      <p className="text-foreground">
        {t("Separate order total:")} <strong>{t("{amount} incl VAT", { amount: formatEur(replacement.expectedTotal) })}</strong>.{" "}
        {t("Nothing is sent until a person approves that order.")}
      </p>
      <a
        className="inline-flex font-medium break-all underline underline-offset-2"
        href={`#proposal-${replacement.orderId}`}
        onClick={() => document.getElementById(`proposal-${replacement.orderId}`)?.focus()}
      >
        {t("Review replacement order {id}", { id: replacement.orderId })}
      </a>
    </div>
  );
}
