import { useRef, useState } from "react";
import { gatewayRequest } from "@/api/http";
import { mapMoney } from "@/api/map";
import { AppShell } from "@/components/purchasing/app-shell";
import { ChefRequestBox } from "@/components/purchasing/chef-request-box";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { formatEur } from "@/lib/format";
import type { ChefRequest } from "@/types";

interface Proposal {
  proposal_id: string;
  status: string;
  expected_total: string;
  total_ex_vat: string;
  buyer_model: string;
  lines: { product_id: string; quantity: string; unit: string; why: string; unknown_stock: boolean }[];
  substitute_options?: { tier: string; expected_total: string; why: string; stock_confirmed: boolean;
    allergen_data_known: boolean; requires_chef_approval: true; lines: Proposal['lines'] }[];
}

function proposal(value: unknown): Proposal {
  if (!value || typeof value !== "object") throw new Error("The Buyer returned an invalid proposal.");
  const row = value as Proposal;
  if (typeof row.proposal_id !== "string" || !row.proposal_id || row.status !== "READY" || !Array.isArray(row.lines) || !row.lines.length ||
      row.lines.some((line) => !line || typeof line.product_id !== "string" ||
        typeof line.quantity !== "string" || typeof line.unit !== "string" ||
        typeof line.why !== "string" || typeof line.unknown_stock !== "boolean")) {
    throw new Error("The Buyer did not return a ready proposal. Check the existing request before trying again.");
  }
  mapMoney(row.expected_total);
  mapMoney(row.total_ex_vat);
  if (row.substitute_options !== undefined) {
    if (!Array.isArray(row.substitute_options) || row.substitute_options.length > 3) throw new Error("Invalid substitute choices.");
    for (const option of row.substitute_options) {
      if (!option || !['good', 'better', 'best'].includes(option.tier) || typeof option.why !== 'string' ||
          option.requires_chef_approval !== true || !Array.isArray(option.lines)) throw new Error("Invalid substitute choice.");
      mapMoney(option.expected_total);
    }
  }
  return row;
}

/** Real purchasing request path; other demo screens keep their existing API. */
export function LiveBuyerRequests() {
  const keys = useRef(new Map<string, string>());
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<Proposal | null>(null);
  const [preferred, setPreferred] = useState<string | null>(null);

  async function submit(request: ChefRequest) {
    const identity = JSON.stringify([request.text.trim(), request.deliveryDate]);
    // Preserve the key after a timeout/error: a new key could duplicate a proposal.
    let key = keys.current.get(identity);
    if (!key) {
      // getRandomValues also works on the demo's plain-HTTP IP address.
      key = Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, "0")).join("");
      keys.current.set(identity, key);
    }
    setPending(true);
    setResult(null);
    setPreferred(null);
    try {
      const kitchen = import.meta.env.VITE_GATEWAY_KITCHEN_ID || "demo-kitchen";
      const response = await gatewayRequest("/api", `/v1/kitchens/${encodeURIComponent(kitchen)}/proposals`, {
        method: "POST", credentials: "same-origin",
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
          <p className="text-muted-foreground">Ask the Buyer for a proposal using live supplier prices and availability. A person approves before anything is placed.</p>
        </header>
        <Card><CardContent><ChefRequestBox onSubmit={submit} /></CardContent></Card>
        {pending ? <LoadingState label="Buyer is checking the catalog and preparing your proposal" /> : null}
        {result ? (
          <Card>
            <CardHeader><CardTitle>Proposal ready for human review</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm">{result.proposal_id}</p>
              <p className="font-semibold">{formatEur(mapMoney(result.total_ex_vat))} ex VAT · {formatEur(mapMoney(result.expected_total))} total</p>
              <ul className="space-y-3">{result.lines.map((line) => (
                <li key={line.product_id} className="rounded-md border p-3">
                  <p>{line.quantity} {line.unit} · {line.product_id}</p>
                  <p>{line.why}</p>
                  {line.unknown_stock ? <p className="text-warning">Waiting for supplier stock confirmation.</p> : null}
                </li>
              ))}</ul>
              <p>No order has been placed. This proposal and the Buyer’s steps are recorded for human review.</p>
              {result.substitute_options?.length ? (
                <section className="space-y-3" aria-label="Chef substitute choices">
                  <h2 className="font-semibold">Other baskets for the chef to consider</h2>
                  {result.substitute_options.map((option) => (
                    <div key={option.tier} className="space-y-2 rounded-md border p-3">
                      <p className="font-medium">{option.tier} · {formatEur(mapMoney(option.expected_total))}</p>
                      <p>{option.why}</p>
                      <p>{option.lines.map((line) => `${line.quantity} ${line.unit} of ${line.product_id}`).join('; ')}</p>
                      <Button variant="outline" aria-pressed={preferred === option.tier} onClick={() => setPreferred(option.tier)}>
                        Prefer {option.tier}
                      </Button>
                    </div>
                  ))}
                  {preferred ? <p role="status">Preferred: {preferred}. This preference has not changed or approved an order. Re-simulate the chosen basket before human approval.</p> : null}
                </section>
              ) : null}
            </CardContent>
          </Card>
        ) : null}
      </div>
    </AppShell>
  );
}
