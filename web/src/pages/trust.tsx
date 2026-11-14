import { CircleCheck, CircleX, Info } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ApiError, useApi } from "@/api";
import { KITCHEN_ID } from "@/api/audit-chain";
import type { AuditChainCheck } from "@/api/types";
import { AppShell } from "@/components/purchasing/app-shell";
import { ACTOR_LABEL } from "@/components/purchasing/audit-timeline";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { formatTime } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useAsync } from "@/lib/use-async";
import { LabelVerificationDemo } from "@/components/purchasing/label-evidence";

/** The gateway's refusals of the tamper demo, in plain words. */
export const DEMO_ERRORS: Record<string, string> = {
  DEMO_ONLY: "The tamper demo only runs on the demo kitchen.",
  ALREADY_TAMPERED: "One line is already changed. Restore it first.",
  NOTHING_TO_TAMPER: "The audit log has no line to change yet.",
};

function plain(error: unknown, t: ReturnType<typeof useT>): string {
  if (error instanceof ApiError && DEMO_ERRORS[error.code]) return t(DEMO_ERRORS[error.code]);
  return error instanceof Error ? error.message : t("Something went wrong.");
}

const short = (hash: string) => hash.slice(0, 8);

export const ELSEWHERE = "The break is in another kitchen's entry (the demo), not in yours";

/** The chain is one for all kitchens. A break with no kitchen named counts as this kitchen's. */
const isElsewhere = (check: AuditChainCheck) =>
  !check.ok && check.brokenKitchenId != null && check.brokenKitchenId !== KITCHEN_ID;

export function TrustPage() {
  const t = useT();
  const api = useApi();
  const rows = useAsync(() => api.listAuditChain(5));
  const [check, setCheck] = useState<AuditChainCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const live = api.live?.has("verifyAuditChain") === true;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      toast.error(plain(error, t));
    } finally {
      setBusy(false);
    }
  }

  const verify = () =>
    run(async () => {
      const result = await api.verifyAuditChain();
      setCheck(result);
      if (result.ok) toast.success(t("Chain OK: {count} lines checked", { count: result.length }));
      else if (isElsewhere(result)) toast.warning(t(ELSEWHERE));
      else toast.error(t("Chain broken at line {line}", { line: String(result.brokenAt) }));
    });

  // A changed line makes the last result stale, so it is cleared until the next verify.
  const tamper = () =>
    run(async () => {
      const { seq } = await api.tamperAuditRow();
      setCheck(null);
      rows.reload();
      toast.warning(t("Line {line} was changed in the data. Verify the chain to see the break.", { line: seq }));
    });

  const restore = () =>
    run(async () => {
      const { seq, restored } = await api.restoreAuditRow();
      setCheck(null);
      rows.reload();
      if (restored) toast.success(t("Line {line} was restored. Verify the chain again.", { line: String(seq) }));
      else toast.info(t("Nothing was tampered, so nothing was restored."));
    });

  return (
    <AppShell activeId="trust">
      <div className="mx-auto max-w-3xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">{t("Tamper check")}</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t("Every audit line carries the hash of the line before it. Changing any line breaks every hash after it.")}
          </p>
          <Badge variant="outline">
            {live ? t("Audit log stored in MongoDB Atlas") : t("Sample data")}
          </Badge>
        </header>

        <Card>
          <CardContent className="space-y-4">
            <Button onClick={verify} disabled={busy}>
              {t("Verify audit chain")}
            </Button>
            <div role="status" className="text-sm">
              {check === null ? (
                <p className="text-muted-foreground">{t("Not checked yet.")}</p>
              ) : (
                <div className="flex items-start gap-2">
                  {check.ok ? (
                    <CircleCheck className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden />
                  ) : isElsewhere(check) ? (
                    <Info className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden />
                  ) : (
                    <CircleX className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
                  )}
                  <div className="tabular-nums">
                    <p className="font-medium">
                      {check.ok
                        ? t("Chain OK: {count} lines checked", { count: check.length })
                        : isElsewhere(check)
                          ? t(ELSEWHERE)
                          : t("Chain broken at line {line}: {count} lines before it are intact", {
                              line: String(check.brokenAt),
                              count: check.length,
                            })}
                    </p>
                    <p className="text-muted-foreground">
                      {isElsewhere(check)
                        ? t("It is line {line} of the shared log. ", { line: String(check.brokenAt) })
                        : null}
                      {t("{count} of the lines are this kitchen's. Checked at {time}.", {
                        count: check.kitchenEntries,
                        time: formatTime(check.checkedAt),
                      })}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        <section aria-labelledby="trust-lines" className="space-y-3">
          <h2 id="trust-lines" className="text-lg font-semibold">
            {t("Newest audit lines")}
          </h2>
          {rows.status === "loading" ? <LoadingState label={t("Loading audit lines")} /> : null}
          {rows.status === "error" ? <ErrorState message={rows.error.message} onRetry={rows.reload} /> : null}
          {rows.status === "ready" && rows.data.length === 0 ? (
            <EmptyState title={t("No audit lines yet")}>{t("Recorded events will appear here.")}</EmptyState>
          ) : null}
          {rows.status === "ready" && rows.data.length > 0 ? (
            <Card>
              <CardContent>
                <ol className="divide-y">
                  {rows.data.map((row) => {
                    const broken = check?.brokenAt != null && row.seq >= check.brokenAt;
                    return (
                      <li key={row.seq} className="space-y-1 py-3 first:pt-0 last:pb-0">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                          <span className="font-medium text-foreground tabular-nums">
                            {t("Line {line}", { line: row.seq })}
                          </span>
                          <span>
                            {ACTOR_LABEL[row.event.actor] ? t(ACTOR_LABEL[row.event.actor]) : row.event.actor}
                          </span>
                          {broken ? (
                            <Badge variant="destructive">
                              {row.seq === check.brokenAt ? t("Broken here") : t("After the break")}
                            </Badge>
                          ) : null}
                        </div>
                        <p className="text-sm break-words">{row.event.summary}</p>
                        <p className="font-mono text-xs text-muted-foreground">
                          {t("hash {hash} · previous {previous}", {
                            hash: short(row.hash),
                            previous: short(row.prevHash),
                          })}
                        </p>
                      </li>
                    );
                  })}
                </ol>
              </CardContent>
            </Card>
          ) : null}
        </section>

        <section aria-labelledby="trust-demo" className="space-y-3 rounded-xl border border-dashed p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id="trust-demo" className="text-lg font-semibold">
              {t("Tamper test")}
            </h2>
            <Badge variant="secondary">{t("Demo only")}</Badge>
          </div>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t(
              "Changes the newest line straight in the data, the way someone with database access could, and leaves its hash alone. Verify the chain afterwards, then restore the line.",
            )}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button variant="destructive" onClick={tamper} disabled={busy}>
              {t("Tamper with one line")}
            </Button>
            <Button variant="outline" onClick={restore} disabled={busy}>
              {t("Restore")}
            </Button>
          </div>
        </section>

        {import.meta.env.VITE_LIVE_BUYER === "true" && <LabelVerificationDemo />}
      </div>
    </AppShell>
  );
}
