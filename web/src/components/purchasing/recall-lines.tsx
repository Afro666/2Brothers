import { ArrowDown, ExternalLink, ShieldAlert } from "lucide-react";

import { formatDate, formatNumber } from "@/lib/format";
import { TONE_CLASSES } from "@/lib/tone";
import { cn } from "@/lib/utils";
import type { Order, RecallAlert, RecallMatch } from "@/types";

const BADGE = "rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap";

const MATCH_TEXT: Record<RecallMatch, string> = {
  exact: "Exact match: the notice's EAN is this product's.",
  possible: "Possible match: same brand and product word. Treat it as recalled until the lot is checked.",
  review: "Needs a person: the notice names no brand and no EAN.",
};

/**
 * Why the order cannot be approved because of a recall; null when it can. A blocked line
 * that is still on the order holds the approval: the total would include recalled goods.
 */
export function recallHold(alerts: RecallAlert[] | undefined, order: Order | undefined): string | null {
  const held = alerts?.find(
    (alert) =>
      alert.lineStatus === "BLOCKED_BY_RECALL" && order?.lines.some((line) => line.product.id === alert.productId),
  );
  return held
    ? `${held.productName ?? held.productId} is blocked by a recall. Approval is available once the Buyer replaces or removes the line.`
    : null;
}

/** The recalled lines of one order, each with its Ruokavirasto notice and the line that replaced it. */
export function RecallLines({ alerts }: { alerts: RecallAlert[] }) {
  if (alerts.length === 0) return null;
  return (
    <section className="space-y-3" aria-label="Recalls on this order">
      {alerts.map((alert) => (
        <RecallLine key={alert.eventId} alert={alert} />
      ))}
    </section>
  );
}

function RecallLine({ alert }: { alert: RecallAlert }) {
  const blocked = alert.lineStatus === "BLOCKED_BY_RECALL";
  const { recall } = alert;
  return (
    <article className="space-y-2">
      <div className={cn("space-y-2 rounded-md border px-3 py-2 text-sm", TONE_CLASSES[blocked ? "danger" : "warning"])}>
        <div className="flex flex-wrap items-center gap-2">
          <ShieldAlert aria-hidden className="size-4 shrink-0" />
          <span className="font-semibold">{blocked ? "Blocked by recall" : "Recall to check"}</span>
          <span className={cn(BADGE, "border-current")}>{alert.match}</span>
        </div>
        <div className="font-medium break-words text-foreground">
          {alert.productName ?? "Product name unknown"} <span className="text-muted-foreground">({alert.productId})</span>
        </div>
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-foreground">
          <dt className="text-muted-foreground">Notice</dt>
          <dd className="break-words">
            <span lang="fi">{recall.title ?? "untitled"}</span> · Ruokavirasto
          </dd>
          <dt className="text-muted-foreground">Date</dt>
          <dd>{recall.date ? `${formatDate(recall.date)} ${recall.date.slice(0, 4)}` : "unknown"}</dd>
          <dt className="text-muted-foreground">Lot</dt>
          <dd className="break-words">
            {recall.lot ?? <span className="text-warning">not stated: every pack is in doubt</span>}
          </dd>
          {recall.recalledProduct ? (
            <>
              <dt className="text-muted-foreground">Recalled</dt>
              <dd className="break-words" lang="fi">
                {recall.recalledProduct}
                {recall.packageSize ? `, ${recall.packageSize}` : ""}
              </dd>
            </>
          ) : null}
        </dl>
        <p className="text-foreground">{MATCH_TEXT[alert.match]}</p>
        <p className="text-foreground">{alert.nextStep}</p>
        <a
          href={recall.url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 font-medium underline underline-offset-2"
        >
          Open the notice on ruokavirasto.fi
          <ExternalLink aria-hidden className="size-3.5" />
          <span className="sr-only">(opens in a new tab)</span>
        </a>
      </div>
      {blocked ? <Replacement alert={alert} /> : null}
    </article>
  );
}

function Replacement({ alert }: { alert: RecallAlert }) {
  const line = alert.replacementLine;
  if (!line) {
    return (
      <div className={cn("rounded-md border px-3 py-2 text-sm", TONE_CLASSES.warning)}>
        <p className="font-medium">No replacement yet</p>
        <p className="text-foreground">The Buyer has not re-planned this line. Approval stays locked.</p>
        {alert.replacementIdeas.length > 0 ? (
          <p className="text-foreground">
            Ideas from other brands: {alert.replacementIdeas.map((idea) => idea.name ?? idea.productId).join("; ")}
          </p>
        ) : null}
      </div>
    );
  }
  return (
    <div className={cn("ml-3 space-y-1 rounded-md border px-3 py-2 text-sm", TONE_CLASSES.success)}>
      <div className="flex items-center gap-2 font-semibold">
        <ArrowDown aria-hidden className="size-4 shrink-0" />
        Replacement line
      </div>
      <div className="font-medium break-words text-foreground">
        {line.productName ?? "Product name unknown"} <span className="text-muted-foreground">({line.productId})</span>
      </div>
      <p className="text-foreground">
        {formatNumber(line.quantity)} {line.unit}, sized by the engine. It is in the total above; nothing is sent until you
        approve.
      </p>
    </div>
  );
}
