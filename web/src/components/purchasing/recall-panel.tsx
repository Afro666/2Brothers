import { RefreshCw, ShieldAlert } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";
import { TONE_CLASSES } from "@/lib/tone";
import { cn } from "@/lib/utils";
import type { RecallCheck } from "@/types";

/**
 * What the inbox knows about recalls:
 * - `unavailable`: this gateway does not serve the recall routes yet.
 * - `unknown`: loading them failed, so nobody can say the open orders are clear.
 * - `ready`: the alerts that hit an open order (`affecting`), and the last check (null: none ran).
 */
export type RecallStatus =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | { kind: "unknown"; message: string }
  | { kind: "ready"; affecting: number; lastCheck: RecallCheck | null };

function plural(count: number) {
  return count === 1 ? "1 recall affects your open order" : `${count} recalls affect your open orders`;
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status.kind === "loading") return null;
  if (status.kind === "unavailable") {
    return (
      <p className={cn("rounded-md border px-3 py-2 text-sm", TONE_CLASSES.neutral)}>
        Recall check is not available on this server yet. Recalls are not checked here.
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
      setError(`Recall check failed: ${e instanceof Error ? e.message : String(e)}. Recalls are unknown.`);
    } finally {
      setBusy(false);
    }
  }

  const affecting = status.kind === "ready" ? status.affecting : null;
  const last = status.kind === "ready" ? status.lastCheck : null;
  let tone: keyof typeof TONE_CLASSES = "neutral";
  let headline: string;
  if (status.kind === "unknown") {
    tone = "warning";
    headline = `Recalls unknown: ${status.message}`;
  } else if (affecting && affecting > 0) {
    tone = "danger";
    headline = plural(affecting);
  } else if (last) {
    tone = "success";
    headline = "No recall matches your open orders.";
  } else {
    headline = "Recalls not checked yet.";
  }

  return (
    <section
      aria-label="Food recalls"
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
            Checked {last.noticesScanned ?? "an unknown number of"} Ruokavirasto notices, {formatDateTime(last.checkedAt)}.{" "}
            {last.source === "recording"
              ? `From the recorded scrape of ${formatDateTime(last.fetchedAt)}, not a live one.`
              : "Scraped live."}
          </p>
        ) : (
          <p className="text-foreground">Food Authority recalls, matched to the lines on your open orders.</p>
        )}
        {last ? (
          <p className="text-xs text-muted-foreground">
            Powered by Context.dev <code>{last.via}</code>
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-danger">
            {error}
          </p>
        ) : null}
      </div>
      {onCheck ? (
        <Button type="button" variant="outline" className="shrink-0" disabled={busy} onClick={() => void check()}>
          <RefreshCw aria-hidden className={cn(busy && "animate-spin")} />
          {busy ? "Checking recalls…" : "Check recalls now"}
        </Button>
      ) : null}
    </section>
  );
}
