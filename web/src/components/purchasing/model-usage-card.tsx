import { useApi } from "@/api";
import type { ModelUsage } from "@/api/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useAsync } from "@/lib/use-async";

/** Runs that carry a count. Zero when nothing was counted, whatever the other fields say. */
const counted = (usage: ModelUsage) =>
  Math.max(0, usage.runs - usage.runsWithoutUsage);

const nothingCounted = (usage: ModelUsage) =>
  counted(usage) === 0 &&
  usage.modelCalls === 0 &&
  usage.promptTokens === 0 &&
  usage.completionTokens === 0 &&
  usage.modelSeconds === 0;

export const MODEL_USAGE_LABELS = {
  runsCounted: "Runs counted",
  modelCalls: "Model calls",
  promptTokens: "Prompt tokens",
  completionTokens: "Completion tokens",
  modelSeconds: "Model seconds",
};

function figures(usage: ModelUsage): [string, string][] {
  return [
    [MODEL_USAGE_LABELS.runsCounted, formatNumber(counted(usage))],
    [MODEL_USAGE_LABELS.modelCalls, formatNumber(usage.modelCalls)],
    [MODEL_USAGE_LABELS.promptTokens, formatNumber(usage.promptTokens)],
    [MODEL_USAGE_LABELS.completionTokens, formatNumber(usage.completionTokens)],
    [MODEL_USAGE_LABELS.modelSeconds, formatNumber(Math.round(usage.modelSeconds * 10) / 10)],
  ];
}

/** How much the Buyer agent used its model, from GET /model-usage. No numbers when there are none. */
export function ModelUsageCard() {
  const t = useT();
  const api = useApi();
  const usage = useAsync(() => api.getModelUsage());
  const empty = usage.status === "ready" && nothingCounted(usage.data);
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2 id="about-model">
            {t("The Buyer agent runs on Nemotron 3.5 Super VL")}
          </h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {usage.status === "loading" && (
          <p role="status" className="text-muted-foreground">
            {t("Loading the counts…")}
          </p>
        )}
        {usage.status === "error" && (
          <p className="text-muted-foreground">
            {t("The counts are not available right now")}
          </p>
        )}
        {empty && <p>{t("No runs counted yet")}</p>}
        {usage.status === "ready" && !empty && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-5">
            {figures(usage.data).map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-muted-foreground">{t(label)}</dt>
                <dd className="text-lg font-semibold tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
        )}
        <p className="text-muted-foreground">
          {t("Counted by the gateway from each run; a run from before the meter has no count.")}
        </p>
      </CardContent>
    </Card>
  );
}
