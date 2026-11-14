import { useApi } from "@/api";
import type { ModelUsage } from "@/api/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
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

function figures(usage: ModelUsage): [string, string][] {
  return [
    ["Runs counted", formatNumber(counted(usage))],
    ["Model calls", formatNumber(usage.modelCalls)],
    ["Prompt tokens", formatNumber(usage.promptTokens)],
    ["Completion tokens", formatNumber(usage.completionTokens)],
    ["Model seconds", formatNumber(Math.round(usage.modelSeconds * 10) / 10)],
  ];
}

/** How much the Buyer agent used its model, from GET /model-usage. No numbers when there are none. */
export function ModelUsageCard() {
  const api = useApi();
  const usage = useAsync(() => api.getModelUsage());
  const empty =
    usage.status === "error" ||
    (usage.status === "ready" && nothingCounted(usage.data));
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2 id="about-model">
            The Buyer agent runs on Nemotron 3.5 Super VL
          </h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {usage.status === "loading" && (
          <p role="status" className="text-muted-foreground">
            Loading the counts…
          </p>
        )}
        {empty && <p>No runs counted yet</p>}
        {usage.status === "ready" && !empty && (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-5">
            {figures(usage.data).map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="text-lg font-semibold tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
        )}
        <p className="text-muted-foreground">
          Counted by the gateway from each run; a run from before the meter has
          no count.
        </p>
      </CardContent>
    </Card>
  );
}
