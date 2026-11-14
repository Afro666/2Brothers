import { useState } from "react";

import { useApi } from "@/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { formatDate, formatQuantity } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useRole } from "@/lib/role";
import { useSession } from "@/lib/session";
import type { LearnedAdjustment } from "@/types";

/** Only an approver switches a learned fact; the demo's Chef role is read-only, like a chef account. */
export function useCanSwitchLearned(): boolean {
  const { session } = useSession();
  const { role } = useRole();
  return session?.kind === "human" && session.canApprove && role === "buyer";
}

export function LearnedBadge({
  learned,
  checkedSentence,
  onChanged,
}: {
  learned: LearnedAdjustment;
  checkedSentence?: string | null;
  onChanged?: () => void | Promise<void>;
}) {
  const t = useT();
  const api = useApi();
  const canSwitch = useCanSwitchLearned();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [switchedOff, setSwitchedOff] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  async function useForecast() {
    if (!canSwitch || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.setLearnedFactActive(learned.factId, false, "human");
    } catch (caught) {
      setError(t("Could not use the forecast instead: {message}", { message: caught instanceof Error ? caught.message : String(caught) }));
      setBusy(false);
      return;
    }
    // The fact is off on the server now, so a failed plan refresh must not read as a failed switch.
    setSwitchedOff(true);
    setOpen(false);
    try {
      await onChanged?.();
    } catch (caught) {
      setRefreshError(t("Switched off. The plan could not refresh: {message}", { message: caught instanceof Error ? caught.message : String(caught) }));
    } finally {
      setBusy(false);
    }
  }

  if (switchedOff) {
    return refreshError ? <p role="alert" className="text-sm text-destructive">{refreshError}</p> : null;
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" size="sm" className="stamp min-h-11 whitespace-normal px-3 text-xs">
          {t("Learned from your changes")}
        </Button>
      </DialogTrigger>
      <DialogContent className="docket max-w-md">
        <DialogHeader>
          <DialogTitle>{t("Learned from your changes")}</DialogTitle>
          <DialogDescription>
            {t("The Buyer adjusted this quantity using changes people made in this kitchen.")}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div>
            <h3 className="label-caps text-xs text-muted-foreground">{t("Quantity change")}</h3>
            <p className="mt-1 text-lg font-semibold tabular-nums">
              {formatQuantity(learned.fromQty, learned.unit)} → {formatQuantity(learned.toQty, learned.unit)}
            </p>
          </div>
          {checkedSentence ? (
            <p className="text-sm">{checkedSentence}</p>
          ) : (
            <p className="text-sm">
              {t("{count} changes, last on {date}", {
                count: learned.evidence.rows,
                date: formatDate(learned.evidence.last),
              })}
            </p>
          )}
          {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
          {!canSwitch ? <p className="text-sm text-muted-foreground">{t("Only an approver can switch off learned facts.")}</p> : null}
        </DialogBody>
        {canSwitch ? (
          <DialogFooter>
            <Button type="button" className="min-h-11" disabled={busy} onClick={() => void useForecast()}>
              {busy ? t("Switching off…") : t("Use the forecast instead")}
            </Button>
          </DialogFooter>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
