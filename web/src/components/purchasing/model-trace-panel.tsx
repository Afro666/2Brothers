import { formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { ModelTrace, ModelTraceStep } from "@/types";
import { NemotronMark } from "@/components/nemotron-mark";

type T = ReturnType<typeof useT>;

const POLICY_CODES = new Set([
  "SCHEMA_INVALID",
  "MALFORMED_JSON",
  "NEED_MISMATCH",
  "DATE_MISMATCH",
  "UNKNOWN_ID",
  "OFFER_INVALID",
  "RUN_MISMATCH",
  "TOOL_NOT_ALLOWED",
  "HUMAN_APPROVAL_REQUIRED",
  "POLICY_VIOLATION",
]);

function verdict(code: string | undefined, t: T): string {
  if (code === "NEEDS_APPROVAL") return t("needs a person’s approval");
  if (code === "REFUSED") return t("refused");
  return code ?? t("unknown");
}

/** What one step did, in words; numbers and codes come from the trace, never model text. */
function action(step: ModelTraceStep, t: T): string {
  const count = step.count ?? 0;
  switch (step.tool) {
    case "search_products":
      if (step.count === undefined) return t("Searched the catalog");
      return step.query
        ? t("Searched the catalog for “{query}”: {count} products", { query: step.query, count })
        : t("Searched the catalog: {count} products", { count });
    case "get_offer":
      if (step.count === undefined) return t("Asked the engine for an offer");
      return t("Asked the engine for an offer on {products} products: {count} lines", {
        products: step.products ?? 0,
        count,
      });
    case "simulate_order":
      return step.code && !POLICY_CODES.has(step.code) && step.code !== "TOOL_FAILED"
        ? t("Checked the offer against the guards: {verdict}", { verdict: verdict(step.code, t) })
        : t("Checked the offer against the guards");
    case "request_approval":
      return t("Sent the offer to you for approval");
    case "place_order":
      return t("Placed the approved order");
    case "get_order_status":
      return t("Read the order status");
    case "get_audit_log":
      return t("Read the activity log");
    case "shortlist":
      return t("Built a shortlist of {count} products from the catalog", { count });
    case "pick":
      return step.by === "model" ? t("Picked one product from the shortlist") : t("The rule picked the first product");
    default:
      return t("Made a call the policy could not read");
  }
}

function stepText(step: ModelTraceStep, t: T): string {
  const what = action(step, t);
  if (step.code && POLICY_CODES.has(step.code))
    return t("{action} — refused by the policy ({code})", { action: what, code: step.code });
  if (step.code === "TOOL_FAILED") return t("{action} — the tool failed", { action: what });
  if (step.code === "MEANING_FALLBACK" && step.tool === "search_products")
    return t("{action} — found by meaning (Atlas Vector Search) after the word search found nothing", {
      action: what,
    });
  return what;
}

function headline(trace: ModelTrace, t: T): string {
  const seconds = formatNumber(Math.round(trace.seconds * 10) / 10);
  const vars = { calls: trace.calls, seconds };
  if (trace.thinking === true)
    return trace.calls === 1
      ? t("1 model call, {seconds} s, thinking on", vars)
      : t("{calls} model calls, {seconds} s, thinking on", vars);
  if (trace.thinking === false)
    return trace.calls === 1
      ? t("1 model call, {seconds} s, thinking off", vars)
      : t("{calls} model calls, {seconds} s, thinking off", vars);
  return trace.calls === 1 ? t("1 model call, {seconds} s", vars) : t("{calls} model calls, {seconds} s", vars);
}

/**
 * "What Nemotron did" (#1197, docs/contract.md "What the model did"): one folded line on a
 * Buyer proposal or a supplier offer, the steps when unfolded, and who set the numbers.
 * No trace, no panel.
 */
export function ModelTracePanel({ trace }: { trace: ModelTrace | null | undefined }) {
  const t = useT();
  if (!trace) return null;
  const engine = (
    <p className="text-xs text-muted-foreground">{t("Quantities and prices: the engine. Approval: you.")}</p>
  );
  if (trace.madeBy === "rule") {
    return (
      <section className="space-y-1 text-sm" aria-label={t("What Nemotron did")}>
        <p>
          {trace.reader === "parser"
            ? t("The gateway’s request parser answered. No model ran.")
            : t("Picked by rule. No model ran.")}
        </p>
        {engine}
      </section>
    );
  }
  return (
    <details className="text-sm" aria-label={t("What Nemotron did")}>
      <summary className="cursor-pointer">
        <NemotronMark />
        <span className="font-medium">{t("What Nemotron did")}</span>{" "}
        <span className="font-mono text-[13px] tabular-nums text-muted-foreground">{headline(trace, t)}</span>
      </summary>
      <div className="mt-2 space-y-2 break-words">
        {trace.attempts > 1 ? (
          <p>{t("The first run stopped without a proposal and was started once more.")}</p>
        ) : null}
        {trace.steps.length ? (
          <ol className="list-decimal space-y-1 pl-5">
            {trace.steps.map((step, index) => (
              <li key={index}>
                <span className="text-muted-foreground">{step.by === "model" ? t("Model:") : t("Code:")}</span>{" "}
                {stepText(step, t)}
              </li>
            ))}
          </ol>
        ) : (
          <p>{t("No tool steps were recorded.")}</p>
        )}
        {trace.truncated ? <p className="text-muted-foreground">{t("Later steps were cut.")}</p> : null}
        {engine}
      </div>
    </details>
  );
}
