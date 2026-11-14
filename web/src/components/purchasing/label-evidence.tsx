import { gatewayRequest } from "@/api/http";
import { useAsync } from "@/lib/use-async";

export interface LabelCheck {
  product_id: string; producer: string | null; label: string;
  label_verified: true | "not_found" | "unknown";
  source_url: string | null; checked_at: string | null; scope: string; reason: string;
  synthetic?: boolean;
}

export function LabelEvidence({ check }: { check: LabelCheck }) {
  const verified = check.label_verified === true && check.scope === "producer" &&
    typeof check.source_url === "string" && /^https:\/\//.test(check.source_url) && !!check.checked_at;
  return <div className="space-y-1 rounded border p-3 text-sm">
    <p>{check.synthetic ? "Synthetic negative control" : `Product ${check.product_id}`} · {check.producer ?? "Legal producer unknown"}</p>
    <p className={verified ? "font-semibold text-green-700 dark:text-green-400" : "font-semibold"}>
      {verified ? "Producer registration verified" : check.label_verified === "not_found" ? "Producer not found" : "Verification unknown"}
    </p>
    <p>Hyvää Suomesta · producer scope · individual product certification unverified</p>
    <p>{check.reason} · checked {check.checked_at ?? "unknown"}</p>
    {check.source_url && /^https:\/\//.test(check.source_url) && <a className="underline" href={check.source_url} target="_blank" rel="noreferrer">Official producer register</a>}
  </div>;
}

export function LabelVerificationDemo() {
  const state = useAsync(async () => {
    const result = await gatewayRequest("/api", "/v1/kitchens/demo-kitchen/label-checks") as {
      checks: LabelCheck[]; negative_control: LabelCheck;
    };
    if (!Array.isArray(result?.checks) || !result.negative_control) throw new Error("Verification data unavailable");
    return result;
  }, []);
  return <section className="space-y-3" aria-label="Label verification">
    <h2 className="text-xl font-semibold">Source-backed label checks</h2>
    <p>Context.dev extracted the official producer register. These dated checks verify producer registration; they do not certify an individual SKU.</p>
    {state.status === "loading" && <p>Loading verification evidence…</p>}
    {state.status === "error" && <p role="alert">Verification unknown: {state.error.message}</p>}
    {state.status === "ready" && <>
      {state.data.checks.map(c => <LabelEvidence key={`${c.product_id}-${c.label}`} check={c} />)}
      <LabelEvidence check={state.data.negative_control} />
    </>}
  </section>;
}
