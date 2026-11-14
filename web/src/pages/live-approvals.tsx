import { useState } from "react";
import { gatewayRequest } from "@/api/http";
import { mapMoney } from "@/api/map";
import { AppShell } from "@/components/purchasing/app-shell";
import { Button } from "@/components/ui/button";
import { formatEur } from "@/lib/format";
import { useAsync } from "@/lib/use-async";

const path = "/v1/kitchens/demo-kitchen/proposals";
interface Proposal {
  proposal_id: string;
  offer_id: string;
  status: string;
  valid_until: string;
  expected_total: string;
  total_ex_vat: string;
  order_id?: string;
  replacement_proposal_id?: string;
  recall_replan_error?: string;
  recall_alerts?: { product_id: string; match: string; recall: { url: string; lot?: string; title?: string } }[];
  decision_summary?: { text?: string };
  lines: { product_id: string; quantity: string; unit: string; why: string; unknown_stock: boolean }[];
}
function parse(value: unknown): Proposal {
  const row = value as Proposal;
  if (!row || typeof row.proposal_id !== "string" || typeof row.offer_id !== "string" ||
      !["READY", "APPROVING", "COMMITTING", "BLOCKED_BY_RECALL", "APPROVED", "REJECTED", "REFUSED"].includes(row.status) ||
      !Number.isFinite(Date.parse(row.valid_until)) || !Array.isArray(row.lines) ||
      row.lines.some(l => !l || typeof l.product_id !== "string" || typeof l.unknown_stock !== "boolean" ||
        typeof l.quantity !== "string" || typeof l.unit !== "string" || typeof l.why !== "string"))
    throw new Error("Invalid proposal from the gateway. Reload before deciding.");
  mapMoney(row.expected_total);
  mapMoney(row.total_ex_vat);
  return row;
}

function ProposalCard({ row, reload }: { row: Proposal; reload: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [placed, setPlaced] = useState<{ id: string; total: string }>();
  const [rejected, setRejected] = useState(false);
  const unknown = row.lines.some(l => l.unknown_stock);
  const expired = Date.parse(row.valid_until) <= Date.now();
  const pending = row.status === "READY" && !placed && !rejected;
  async function decide(approve: boolean) {
    setBusy(true);
    setError(undefined);
    try {
      const result = await gatewayRequest("/api", `${path}/${encodeURIComponent(row.proposal_id)}/${approve ? "approve" : "reject"}`, {
        method: "POST",
        body: JSON.stringify(approve ? {
          // Stable across retries and tabs; a changed offer gets a new decision key.
          idempotency_key: `web-approve-${row.proposal_id}-${row.offer_id}`,
          expected_total: row.expected_total,
        } : { reason: "Rejected by chef in the approval inbox" }),
      }) as { order_id?: string; expected_total?: string; status?: string };
      if (approve) {
        if (typeof result.order_id !== "string" || typeof result.expected_total !== "string")
          throw new Error("Order confirmation was incomplete. Reload to reconcile before trying again.");
        mapMoney(result.expected_total);
        setPlaced({ id: result.order_id, total: result.expected_total });
      } else {
        if (result.status !== "REJECTED") throw new Error("Rejection was not confirmed. Reload to reconcile.");
        setRejected(true);
      }
      setConfirm(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The decision could not be confirmed.");
    } finally { setBusy(false); }
  }
  return <article id={`proposal-${row.proposal_id}`} className="space-y-3 rounded-xl border p-5" aria-label={`Proposal ${row.proposal_id}`}>
    <h2 className="font-semibold">Proposal {row.proposal_id}</h2>
    {typeof row.decision_summary?.text === "string" && <p className="whitespace-pre-line">{row.decision_summary.text}</p>}
    <ul>{row.lines.map(l => <li key={l.product_id}>{l.quantity} {l.unit} · {l.product_id} · {l.why}</li>)}</ul>
    {row.recall_alerts?.map((alert, index) => <p key={index} className="text-destructive">
      {alert.match === "review" ? "Recall warning — check the product" : "BLOCKED_BY_RECALL"}: {alert.product_id} · {alert.recall.title} · {alert.recall.lot ?? "Check affected packs"}
      {/^https:\/\//.test(alert.recall.url) && <> · <a className="underline" href={alert.recall.url} target="_blank" rel="noreferrer">Official recall notice</a></>}
    </p>)}
    {row.replacement_proposal_id && <p><a className="underline" href={`#proposal-${row.replacement_proposal_id}`}>Review replacement proposal {row.replacement_proposal_id}</a>. A fresh human approval is required.</p>}
    {row.recall_replan_error && <p>No complete safe replacement is available ({row.recall_replan_error}). The original remains blocked.</p>}
    <p>{formatEur(mapMoney(row.total_ex_vat))} ex VAT · {formatEur(mapMoney(row.expected_total))} including VAT and delivery</p>
    {unknown && <p>Waiting for supplier stock confirmation. Approval is unavailable.</p>}
    {expired && pending && <p>This offer has expired. Ask the Buyer for a fresh proposal.</p>}
    {placed ? <p role="status">Order recorded: {placed.id} · {formatEur(mapMoney(placed.total))}. Recorded in our gateway; not submitted to Valio.</p> :
      row.status === "APPROVED" ? <p>Order recorded: {row.order_id ?? "reload to reconcile"}. Recorded in our gateway; not submitted to Valio.</p> :
      !pending ? <p>{rejected ? "REJECTED" : row.status}</p> : null}
    {error && <div role="alert">{error} Check the current proposal before repeating a decision. <Button onClick={reload}>Reload proposals</Button></div>}
    {pending && <div className="flex flex-wrap gap-3">
      <Button disabled={busy || unknown || expired || !row.lines.length} onClick={() => setConfirm(true)}>Approve {formatEur(mapMoney(row.expected_total))}</Button>
      <Button variant="outline" disabled={busy} onClick={() => void decide(false)}>Reject proposal</Button>
    </div>}
    {confirm && pending && <div role="dialog" aria-label="Confirm approval" className="space-y-3 rounded border p-4">
      <p>Confirm this exact basket for {formatEur(mapMoney(row.expected_total))}? The gateway checks price and stock again.</p>
      <Button disabled={busy || unknown || expired} onClick={() => void decide(true)}>Confirm and record order</Button>
      <Button variant="outline" disabled={busy} onClick={() => setConfirm(false)}>Cancel</Button>
    </div>}
  </article>;
}

export function LiveApprovalsPage() {
  const proposals = useAsync(async () => {
    const result = await gatewayRequest("/api", path) as { proposals?: unknown[] };
    if (!Array.isArray(result?.proposals)) throw new Error("Invalid proposal list.");
    return result.proposals.map(parse);
  }, []);
  return <AppShell activeId="approvals"><main className="mx-auto max-w-5xl space-y-5">
    <h1 className="text-2xl font-semibold">Approvals</h1>
    <p>Live demo proposals. A person confirms the exact basket and total before an order is recorded.</p>
    <Button variant="outline" onClick={proposals.reload}>Refresh proposals</Button>
    {proposals.status === "loading" && <p>Loading proposals…</p>}
    {proposals.status === "error" && <p role="alert">{proposals.error.message}</p>}
    {proposals.status === "ready" && (proposals.data.length ? proposals.data.map(row =>
      <ProposalCard key={`${row.proposal_id}-${row.offer_id}-${row.status}`} row={row} reload={proposals.reload} />) : <p>No proposals yet. Ask the Buyer on Requests.</p>)}
  </main></AppShell>;
}
