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

function proposal(value: unknown): Proposal {
  if (!value || typeof value !== "object") throw new Error("The Buyer returned an invalid proposal.");
  const row = value as Proposal;
  if (
    typeof row.proposal_id !== "string" ||
    !row.proposal_id ||
    row.status !== "READY" ||
    !Array.isArray(row.lines) ||
    !row.lines.length ||
    row.lines.some(
      (line) =>
        !line ||
        typeof line.product_id !== "string" ||
        typeof line.quantity !== "string" ||
        typeof line.unit !== "string" ||
        typeof line.why !== "string" ||
        typeof line.unknown_stock !== "boolean",
    )
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
        !Array.isArray(option.lines)
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
        <h2 className="font-semibold">Why this basket</h2>
        <p className="text-sm break-words whitespace-pre-line">{text(summary?.text) ?? "unknown"}</p>
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
        <h2 className="font-semibold">What the guards said</h2>
        <p className="text-sm">
          Verdict:{" "}
          {verdict === "NEEDS_APPROVAL" ? (
            <Badge variant="secondary">Needs a person’s approval</Badge>
          ) : verdict === "REFUSED" ? (
            <Badge variant="destructive">Refused</Badge>
          ) : (
            "unknown"
          )}
        </p>
        {reasons?.length ? (
          <ul className="list-disc space-y-1 pl-5 text-sm break-words">
            {reasons.map((reason, index) => (
              <li key={index}>{reason}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm">{reasons ? "No reasons given." : "Reasons: unknown"}</p>
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
          <h1 className="text-2xl font-semibold">Requests</h1>
          <p className="text-muted-foreground">
            Ask the Buyer for a proposal using live supplier prices and availability. A person approves before anything
            is placed.
          </p>
        </header>
        <Card>
          <CardContent>
            <ChefRequestBox onSubmit={submit} />
          </CardContent>
        </Card>
        {pending ? <LoadingState label="Buyer is checking the catalog and preparing your proposal" /> : null}
        {result ? (
          <Card>
            <CardHeader>
              <CardTitle>Proposal ready for human review</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-muted-foreground">{proposedBy(result)}</p>
              <p className="text-sm break-all">{result.proposal_id}</p>
              <p className="font-semibold">
                {formatEur(mapMoney(result.total_ex_vat))} ex VAT · {formatEur(mapMoney(result.expected_total))} total
              </p>
              <Decision row={result} />
              <ul className="space-y-3">
                {result.lines.map((line) => (
                  <li key={line.product_id} className="rounded-md border p-3">
                    <p>
                      {line.quantity} {line.unit} · {product(line.product_id)}
                    </p>
                    <p>{line.why}</p>
                    {line.unknown_stock ? (
                      <p className="text-warning">Waiting for supplier stock confirmation.</p>
                    ) : null}
                  </li>
                ))}
              </ul>
              <p>No order has been placed. This proposal and the Buyer’s steps are recorded for human review.</p>
              <a className="underline" href="/approvals">Open live approval inbox</a>
              {result.substitute_options?.length ? (
                <section className="space-y-3" aria-label="Chef substitute choices">
                  <h2 className="font-semibold">Other baskets for the chef to consider</h2>
                  {result.substitute_options.map((option) => (
                    <div key={option.tier} className="space-y-2 rounded-md border p-3">
                      <p className="font-medium">
                        {option.tier} · {formatEur(mapMoney(option.expected_total))}
                      </p>
                      <p>{option.why}</p>
                      <p>
                        {option.lines
                          .map((line) => `${line.quantity} ${line.unit} of ${product(line.product_id)}`)
                          .join("; ")}
                      </p>
                      <Button
                        variant="outline"
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
