import type { ModelTrace, ModelTraceStep } from "@/types";

const count = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : undefined;

function step(value: unknown): ModelTraceStep | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (typeof row.tool !== "string" || (row.by !== "model" && row.by !== "code")) return null;
  const out: ModelTraceStep = { by: row.by, attempt: count(row.attempt) ?? 1, tool: row.tool };
  if (typeof row.query === "string" && row.query) out.query = row.query;
  const products = count(row.products);
  if (products !== undefined) out.products = products;
  const rows = count(row.count);
  if (rows !== undefined) out.count = rows;
  if (typeof row.code === "string" && /^[A-Z][A-Z0-9_]*$/.test(row.code)) out.code = row.code;
  return out;
}

/**
 * The gateway's `model_trace` (docs/contract.md, "What the model did"). The panel is an extra:
 * a missing or odd trace is null, so the card shows no panel and never breaks.
 */
export function mapModelTrace(value: unknown): ModelTrace | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  if (row.made_by !== "model" && row.made_by !== "rule") return null;
  if (row.reader !== "buyer" && row.reader !== "parser" && row.reader !== "seller") return null;
  const seconds = typeof row.seconds === "number" && Number.isFinite(row.seconds) && row.seconds >= 0 ? row.seconds : 0;
  return {
    madeBy: row.made_by,
    reader: row.reader,
    model: typeof row.model === "string" && row.model ? row.model : null,
    thinking: typeof row.thinking === "boolean" ? row.thinking : null,
    calls: count(row.calls) ?? 0,
    seconds,
    attempts: count(row.attempts) ?? 0,
    truncated: row.truncated === true,
    steps: Array.isArray(row.steps)
      ? row.steps.map(step).filter((item): item is ModelTraceStep => item !== null)
      : [],
  };
}
