import { useEffect, useState } from "react";

import { useApi } from "@/api";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { useCanSwitchLearned } from "@/components/purchasing/learned-badge";
import { SampleData } from "@/components/purchasing/sample-data";
import { Button } from "@/components/ui/button";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useAsync } from "@/lib/use-async";
import { SettingsSection } from "@/pages/settings/section";
import type { LearnedFact } from "@/types";

function factText(fact: LearnedFact, t: (key: string, values?: Record<string, string | number>) => string): string {
  switch (fact.kind) {
    case "CORRECTION_RATIO":
      return t("Quantity correction: {ratio} × the forecast", { ratio: formatNumber(fact.value) });
    case "DECLINED_PRODUCT":
      return t("Kept out of proposals after repeated removals");
    case "SUPPLIER_LATE":
      return fact.value === 1
        ? t("Supplier delivery timing: {days} day late on average", { days: formatNumber(fact.value) })
        : t("Supplier delivery timing: {days} days late on average", { days: formatNumber(fact.value) });
    case "SUPPLIER_SHORT":
      return t("Supplier fill rate: {rate}", { rate: formatPercent(fact.value) });
  }
}

export function LearnedSection() {
  const t = useT();
  const api = useApi();
  const canSwitch = useCanSwitchLearned();
  const state = useAsync(() => api.listLearnedFacts(), [api]);
  const [facts, setFacts] = useState<LearnedFact[] | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);
  const [error, setError] = useState<{ id: string; message: string } | null>(null);

  useEffect(() => {
    if (state.status === "ready") setFacts(structuredClone(state.data));
  }, [state.status, state.status === "ready" ? state.data : null]);

  async function switchOff(fact: LearnedFact) {
    if (!canSwitch || !fact.active || switching) return;
    setSwitching(fact.id);
    setError(null);
    try {
      const updated = await api.setLearnedFactActive(fact.id, false, "human");
      setFacts((current) => current?.map((row) => row.id === updated.id ? updated : row) ?? null);
    } catch (caught) {
      setError({
        id: fact.id,
        message: t("Could not switch off this learned fact: {message}", {
          message: caught instanceof Error ? caught.message : String(caught),
        }),
      });
    } finally {
      setSwitching(null);
    }
  }

  return (
    <SettingsSection
      title="What the tool learned"
      description="See the evidence behind learned changes and switch off facts you no longer want used."
    >
      <SampleData of="listLearnedFacts" />
      {state.status === "loading" ? <LoadingState label={t("Loading learned facts")} /> : null}
      {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
      {state.status === "ready" && facts?.length === 0 ? (
        <EmptyState title={t("Nothing learned yet: the tool learns from the reasons you give when you change an order.")} />
      ) : null}
      {state.status === "ready" && facts && facts.length > 0 ? (
        <div className="space-y-4">
          {!canSwitch ? <p className="text-sm text-muted-foreground">{t("Read only: only an approver can switch off learned facts.")}</p> : null}
          <ul className="max-w-3xl space-y-4" aria-label={t("Learned facts")}>
          {facts.map((fact) => (
            <li key={fact.id} className="docket space-y-4 rounded-lg border p-4 sm:p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <h3 className="break-words font-semibold">{fact.name}</h3>
                  <p className="text-sm">{factText(fact, t)}</p>
                  {fact.kind === "CORRECTION_RATIO" && fact.applicable === false ? (
                    <p className="text-sm text-muted-foreground">{t("Not applied: this ratio is outside the range the tool trusts.")}</p>
                  ) : null}
                </div>
                <span className="stamp text-xs">{fact.active ? t("On") : t("Off")}</span>
              </div>
              <dl className="space-y-2 text-sm text-muted-foreground">
                <div>
                  <dt className="label-caps inline text-xs">{t("Evidence")}</dt>
                  <dd className="mt-0.5">
                    {t("{count} recorded events from {from} to {to}. Last on {last}.", {
                      count: fact.evidence.rows,
                      from: formatDate(fact.evidence.from),
                      to: formatDate(fact.evidence.to),
                      last: `${formatDate(fact.evidence.last)} ${fact.evidence.last.slice(0, 4)}`,
                    })}
                  </dd>
                </div>
                <div>
                  <dt className="label-caps inline text-xs">{t("Started")}</dt>
                  <dd className="mt-0.5">{formatDate(fact.since)} {fact.since.slice(0, 4)}</dd>
                </div>
              </dl>
              {error?.id === fact.id ? <p role="alert" className="text-sm text-destructive">{error.message}</p> : null}
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  variant="outline"
                  role="switch"
                  aria-checked={fact.active}
                  aria-label={t("Use learned fact for {name}", { name: fact.name })}
                  className="min-h-11 min-w-20"
                  disabled={!canSwitch || !fact.active || switching !== null}
                  onClick={() => void switchOff(fact)}
                >
                  {switching === fact.id ? t("Switching off…") : fact.active ? t("On") : t("Off")}
                </Button>
                {canSwitch && !fact.active ? (
                  <span className="text-sm text-muted-foreground">{t("Switched off. It comes back when the tool learns it again.")}</span>
                ) : null}
              </div>
            </li>
          ))}
          </ul>
        </div>
      ) : null}
    </SettingsSection>
  );
}
