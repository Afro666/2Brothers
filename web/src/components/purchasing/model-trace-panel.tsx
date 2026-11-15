import { formatNumber } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { ModelTrace, ModelTraceStep } from "@/types";
import type { ProposalExplanation } from "@/api/types";
import { isNemotron, NemotronMark } from "@/components/nemotron-mark";
import { explanationModelName } from "@/components/purchasing/proposal-explanation";

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
      // A reused pick (agent/service.py, store/buyer_picks.py): the model's earlier pick, not a rule.
      if (step.code === "CACHED_PICK") return t("Reused Nemotron’s pick for the same request from a few minutes ago");
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

/** Seconds as the panel prints them: one decimal, in the viewer's number format. */
const tenths = (seconds: number): string => formatNumber(Math.round(seconds * 10) / 10);

/**
 * `calls` and `seconds` are the Buyer run's plus the explanation call's (#1867): the trace
 * counts the run only, and the explanation is one more model call the gateway times itself.
 */
function headline(trace: ModelTrace, calls: number, seconds: number, t: T): string {
  const vars = { calls, seconds: tenths(seconds) };
  if (calls === 0 && trace.steps.some((step) => step.tool === "pick" && step.code === "CACHED_PICK"))
    return t("0 model calls (pick reused)");
  if (trace.thinking === true)
    return calls === 1
      ? t("1 model call, {seconds} s, thinking on", vars)
      : t("{calls} model calls, {seconds} s, thinking on", vars);
  if (trace.thinking === false)
    return calls === 1
      ? t("1 model call, {seconds} s, thinking off", vars)
      : t("{calls} model calls, {seconds} s, thinking off", vars);
  return calls === 1 ? t("1 model call, {seconds} s", vars) : t("{calls} model calls, {seconds} s", vars);
}

/** The explanation on the card as a model call: its model and its time, null when there is no text. */
function written(explanation: ProposalExplanation | null | undefined): { model: string; seconds: number | null } | null {
  if (!explanation?.text) return null;
  const ms = explanation.durationMs;
  return { model: explanation.model, seconds: ms != null && ms >= 0 ? ms / 1000 : null };
}

/**
 * One visible line on the card (#1867): who made the proposal, from the trace fields. A judge
 * who never unfolds the panel still reads the model's name. No trace, no line.
 */
export function ModelTraceLine({ trace }: { trace: ModelTrace | null | undefined }) {
  const t = useT();
  if (!trace) return null;
  const model = trace.madeBy === "model" ? trace.model : null;
  const vars = { model: model ? explanationModelName(model) : "", calls: trace.calls, seconds: tenths(trace.seconds) };
  return (
    <p data-slot="card-made-by" className="font-mono text-xs leading-4 font-[450] text-muted-foreground">
      <NemotronMark when={isNemotron(model)} />
      {trace.madeBy === "rule"
        ? t("Made by the gateway’s rules, no model call")
        : !model
          ? t("Picked by a model")
          : trace.calls === 1
            ? t("Picked by {model} · 1 call · {seconds} s", vars)
            : t("Picked by {model} · {calls} calls · {seconds} s", vars)}
    </p>
  );
}

/**
 * "What Nemotron did" (#1197, docs/contract.md "What the model did"): one folded line on a
 * Buyer proposal or a supplier offer, the steps when unfolded, and who set the numbers.
 * No trace, no panel. `explanation` is the checked text the same card shows: one more model
 * call, counted and listed here with its own time (#1867).
 */
export function ModelTracePanel({
  trace,
  explanation,
  defaultOpen = false,
}: {
  trace: ModelTrace | null | undefined;
  explanation?: ProposalExplanation | null;
  /** Open at first: on a card that waits for a decision, the model's steps are part of what the person checks (#2015). */
  defaultOpen?: boolean;
}) {
  const t = useT();
  if (!trace) return null;
  const text = written(explanation);
  const engine = (
    <p className="text-xs text-muted-foreground">{t("Quantities and prices: the engine. Approval: you.")}</p>
  );
  if (trace.madeBy === "rule") {
    return (
      <section className="space-y-1 text-sm" aria-label={t("What Nemotron did")}>
        {text ? (
          <>
            <p>
              {trace.reader === "parser"
                ? t("The gateway’s request parser made the proposal: no model picked the products.")
                : t("Picked by rule: no model picked the products.")}
            </p>
            <p>
              <NemotronMark when={isNemotron(text.model)} />
              {text.seconds == null
                ? t("{model} wrote the explanation on this card: 1 model call.", {
                    model: explanationModelName(text.model),
                  })
                : t("{model} wrote the explanation on this card: 1 model call, {seconds} s.", {
                    model: explanationModelName(text.model),
                    seconds: tenths(text.seconds),
                  })}
            </p>
          </>
        ) : (
          <p>
            {trace.reader === "parser"
              ? t("The gateway’s request parser answered. No model ran.")
              : t("Picked by rule. No model ran.")}
          </p>
        )}
        {engine}
      </section>
    );
  }
  const calls = trace.calls + (text ? 1 : 0);
  const seconds = trace.seconds + (text?.seconds ?? 0);
  return (
    <details className="text-sm" aria-label={t("What Nemotron did")} open={defaultOpen || undefined}>
      <summary className="cursor-pointer">
        <NemotronMark />
        <span className="font-medium">{t("What Nemotron did")}</span>{" "}
        <span className="font-mono text-[13px] tabular-nums text-muted-foreground">{headline(trace, calls, seconds, t)}</span>
      </summary>
      <div className="mt-2 space-y-2 break-words">
        {trace.attempts > 1 ? (
          <p>{t("The first run stopped without a proposal and was started once more.")}</p>
        ) : null}
        {trace.steps.length || text ? (
          <ol className="list-decimal space-y-1 pl-5">
            {trace.steps.map((step, index) => (
              <li key={index}>
                <span className="text-muted-foreground">{step.by === "model" ? t("Model:") : t("Code:")}</span>{" "}
                {stepText(step, t)}
              </li>
            ))}
            {text ? (
              <li>
                <span className="text-muted-foreground">{t("Model:")}</span>{" "}
                {text.seconds == null
                  ? t("Wrote the explanation on this card from the checked decision record")
                  : t("Wrote the explanation on this card from the checked decision record: {seconds} s", {
                      seconds: tenths(text.seconds),
                    })}
              </li>
            ) : null}
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
