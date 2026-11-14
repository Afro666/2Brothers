import { useRef, useState } from "react";
import { gatewayRequest } from "@/api/http";
import { mapMoney } from "@/api/map";
import { AppShell } from "@/components/purchasing/app-shell";
import { ChefRequestBox } from "@/components/purchasing/chef-request-box";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { formatEur } from "@/lib/format";
import type { ChefRequest } from "@/types";

interface Proposal {
  proposal_id: string;
  status: string;
  expected_total: string;
  total_ex_vat: string;
  buyer_model?: string;
  request?: { made_by?: string };
  decision_summary?: { asked?: string; searched?: string; chosen?: string[]; text?: string };
  mandate?: { verdict?: string; reasons?: string[] };
  lines: { product_id: string; quantity: string; unit: string; why: string; unknown_stock: boolean }[];
  substitute_options?: {
    tier: string;
    expected_total: string;
    why: string;
    stock_confirmed: boolean;
    allergen_data_known: boolean;
    requires_chef_approval: true;
    lines: Proposal["lines"];
  }[];
}

const validLine = (line: Proposal["lines"][number]) =>
  Boolean(line) &&
  typeof line.product_id === "string" &&
  typeof line.quantity === "string" &&
  typeof line.unit === "string" &&
  typeof line.why === "string" &&
  typeof line.unknown_stock === "boolean";

function proposal(value: unknown): Proposal {
  if (!value || typeof value !== "object") throw new Error("The Buyer returned an invalid proposal.");
  const row = value as Proposal;
  if (
    typeof row.proposal_id !== "string" ||
    !row.proposal_id ||
    row.status !== "READY" ||
    !Array.isArray(row.lines) ||
    !row.lines.length ||
    !row.lines.every(validLine)
  ) {
    throw new Error("The Buyer did not return a ready proposal. Check the existing request before trying again.");
  }
  mapMoney(row.expected_total);
  mapMoney(row.total_ex_vat);
  if (row.substitute_options !== undefined) {
    if (!Array.isArray(row.substitute_options) || row.substitute_options.length > 3)
      throw new Error("Invalid substitute choices.");
    for (const option of row.substitute_options) {
      if (
        !option ||
        !["good", "better", "best"].includes(option.tier) ||
        typeof option.why !== "string" ||
        option.requires_chef_approval !== true ||
        typeof option.stock_confirmed !== "boolean" ||
        typeof option.allergen_data_known !== "boolean" ||
        !Array.isArray(option.lines) ||
        !option.lines.every(validLine)
      )
        throw new Error("Invalid substitute choice.");
      mapMoney(option.expected_total);
    }
  }
  return row;
}

// decision_summary and mandate are optional and not validated: read them defensively,
// so a missing or odd value shows "unknown" and never breaks the card.
const text = (value: unknown) => (typeof value === "string" && value.trim() ? value : undefined);
const texts = (value: unknown) =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : undefined;

// shortcut: lines carry no name field, so names are read from the gateway's "chosen" sentences
// ("<qty> <unit> of <id> <name>, EUR ..."); use a line name when the contract adds one.
function productNames(row: Proposal) {
  const names = new Map<string, string>();
  for (const sentence of texts(row.decision_summary?.chosen) ?? []) {
    const match = /^\S+ \S+ of ([^\s,]+) (.+?), EUR /.exec(sentence);
    if (match) names.set(match[1], match[2]);
  }
  return names;
}

function proposedBy(row: Proposal) {
  const model = text(row.buyer_model);
  if (model)
    return `Proposed by the Buyer agent (${model === "nemotron-3.5-super-vl" ? "Nemotron 3.5 Super VL" : model})`;
  // The gateway marks a proposal made by its fallback parser: do not credit the Buyer for it.
  if (row.request?.made_by === "parser") return "Proposed by the gateway’s request parser, not the Buyer model";
  return "Proposed by the Buyer agent";
}

function Decision({ row }: { row: Proposal }) {
  const summary = row.decision_summary;
  const chosen = texts(summary?.chosen);
  const steps = [
    ["What was asked", text(summary?.asked)],
    ["What was searched", text(summary?.searched)],
  ].filter((step): step is [string, string] => Boolean(step[1]));
  const verdict = row.mandate?.verdict;
  const reasons = texts(row.mandate?.reasons);
  return (
    <>
      <section className="space-y-2" aria-label="Why this basket">
        <h2 className="label-caps">Why this basket</h2>
        <p className="max-w-[68ch] text-[15px] leading-[22px] break-words whitespace-pre-line">
          {text(summary?.text) ?? <span className="unknown-value">unknown</span>}
        </p>
        {text(summary?.text) ? (
          <p className="text-xs text-muted-foreground">
            Built by the gateway from the stored request and figures. No model writes this text.
          </p>
        ) : null}
        {steps.length || chosen?.length ? (
          <details className="text-sm">
            <summary className="cursor-pointer font-medium">Step by step</summary>
            <dl className="mt-2 space-y-2 break-words">
              {steps.map(([label, value]) => (
                <div key={label}>
                  <dt className="font-medium">{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
              {chosen?.length ? (
                <div>
                  <dt className="font-medium">What was chosen</dt>
                  {chosen.map((item, index) => (
                    <dd key={index}>{item}</dd>
                  ))}
                </div>
              ) : null}
            </dl>
          </details>
        ) : null}
      </section>
      <section className="space-y-2" aria-label="What the guards said">
        <h2 className="label-caps">What the guards said</h2>
        <p className="text-sm">
          Verdict:{" "}
          {verdict === "NEEDS_APPROVAL" ? (
            <Badge variant="secondary" className="stamp rounded-sm border-2 border-warning bg-transparent text-warning">Needs a person’s approval</Badge>
          ) : verdict === "REFUSED" ? (
            <Badge variant="destructive" className="stamp rounded-sm border-2 border-danger bg-transparent text-danger">Refused</Badge>
          ) : (
            <span className="unknown-value">unknown</span>
          )}
        </p>
        {reasons?.length ? (
          <ul className="list-disc space-y-1 pl-5 text-sm break-words">
            {reasons.map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm">{reasons ? "No reasons given." : <>Reasons: <span className="unknown-value">unknown</span></>}</p>
        )}
      </section>
    </>
  );
}

/** Real purchasing request path; other demo screens keep their existing API. */
export function LiveBuyerRequests() {
  const keys = useRef(new Map<string, string>());
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<Proposal | null>(null);
  const [preferred, setPreferred] = useState<string | null>(null);
  const names = result ? productNames(result) : new Map<string, string>();
  const product = (id: string) => (names.has(id) ? `${names.get(id)} (${id})` : id);

  async function submit(request: ChefRequest) {
    const identity = JSON.stringify([request.text.trim(), request.deliveryDate]);
    // Preserve the key after a timeout/error: a new key could duplicate a proposal.
    let key = keys.current.get(identity);
    if (!key) {
      // getRandomValues also works on the demo's plain-HTTP IP address.
      key = Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, "0")).join(
        "",
      );
      keys.current.set(identity, key);
    }
    setPending(true);
    setResult(null);
    setPreferred(null);
    try {
      const kitchen = import.meta.env.VITE_GATEWAY_KITCHEN_ID || "demo-kitchen";
      const response = await gatewayRequest("/api", `/v1/kitchens/${encodeURIComponent(kitchen)}/proposals`, {
        method: "POST",
        credentials: "same-origin",
        body: JSON.stringify({ text: request.text.trim(), requested_date: request.deliveryDate, idempotency_key: key }),
      });
      setResult(proposal(response));
    } finally {
      setPending(false);
    }
  }

  return (
    <AppShell activeId="requests">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-[28px] leading-8 font-bold tracking-[-0.015em]">Request an order</h1>
          <p className="max-w-[68ch] text-[15px] leading-[22px] text-muted-foreground">
            Ask the Buyer for a proposal using live supplier prices and availability. A person approves before anything
            is placed.
          </p>
        </header>
        <Card>
          <CardContent>
            <ChefRequestBox onSubmit={submit} />
          </CardContent>
        </Card>
        {pending ? (
          <div className="space-y-3">
            <div className="print-bar" aria-hidden="true" />
            <LoadingState label="Buyer is checking the catalog and preparing your proposal" />
          </div>
        ) : null}
        {result ? (
          <Card className="docket gap-4 p-4 sm:p-5">
            <CardHeader className="px-0">
              <CardTitle className="label-caps leading-4">Proposal ready for human review</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 px-0">
              <p className="font-mono text-xs leading-4 text-muted-foreground">{proposedBy(result)}</p>
              <p className="break-all font-mono text-[11px] text-muted-foreground">{result.proposal_id}</p>
              <p className="text-xl font-bold">
                {formatEur(mapMoney(result.total_ex_vat))} ex VAT · {formatEur(mapMoney(result.expected_total))} total
              </p>
              <Decision row={result} />
              <ul>
                {result.lines.map((line) => (
                  <li key={line.product_id} className="border-t py-2 first:border-t-0">
                    <p className="font-mono text-[13px]">
                      {line.quantity} {line.unit} · {product(line.product_id)}
                    </p>
                    <p className="max-w-[68ch] text-sm">{line.why}</p>
                    {line.unknown_stock ? (
                      <p><span className="unknown-value">Waiting for supplier stock confirmation.</span></p>
                    ) : null}
                  </li>
                ))}
              </ul>
              <p className="border-t border-dashed border-input pt-3 text-sm">No order has been placed. This proposal and the Buyer’s steps are recorded for human review.</p>
              <a className="inline-block font-medium text-foreground underline decoration-border underline-offset-4 hover:decoration-foreground" href="/approvals">Open live approval inbox</a>
              {result.substitute_options?.length ? (
                <section aria-label="Chef substitute choices">
                  <h2 className="label-caps">Other baskets for the chef to consider</h2>
                  {result.substitute_options.map((option) => (
                    <div key={option.tier} className="space-y-2 border-t py-3 first:border-t-0">
                      <p className="flex flex-wrap items-baseline gap-x-3">
                        <span className="stamp">{option.tier}</span>
                        {" · "}
                        <span className="font-stamp text-xl">{formatEur(mapMoney(option.expected_total))}</span>
                      </p>
                      <p className="max-w-[68ch] text-sm">{option.why}</p>
                      <p className="font-mono text-[13px]">
                        {option.lines
                          .map((line) => `${line.quantity} ${line.unit} of ${product(line.product_id)}`)
                          .join("; ")}
                      </p>
                      {option.stock_confirmed ? null : <p><span className="unknown-value">Stock not confirmed</span></p>}
                      {option.allergen_data_known ? null : <p><span className="unknown-value">Allergen data unknown</span></p>}
                      <Button
                        variant="outline"
                        className="w-full aria-pressed:border-primary aria-pressed:bg-accent sm:w-auto"
                        aria-pressed={preferred === option.tier}
                        onClick={() => setPreferred(option.tier)}
                      >
                        Prefer {option.tier}
                      </Button>
                    </div>
                  ))}
                  {preferred ? (
                    <p role="status">
                      Preferred: {preferred}. This preference has not changed or approved an order. Re-simulate the
                      chosen basket before human approval.
                    </p>
                  ) : null}
                </section>
              ) : null}
            </CardContent>
          </Card>
        ) : null}
      </div>
    </AppShell>
  );
}
