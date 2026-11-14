import { useId, useState } from "react";
import { gatewayRequest } from "@/api/http";
import { mapMoney } from "@/api/map";
import { AppShell } from "@/components/purchasing/app-shell";
import { Button } from "@/components/ui/button";
import { formatEur } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import { LabelEvidence, type LabelCheck } from "@/components/purchasing/label-evidence";

const path = "/v1/kitchens/demo-kitchen/proposals";
interface RecallAlert {
  event_id?: string;
  product_id: string;
  match: string;
  status?: "active" | "dismissed";
  dismiss_reason?: string;
  recall: { url: string; lot?: string; title?: string };
}

function RecallNotice({ alert, reload }: { alert: RecallAlert; reload: () => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const reasonId = useId();
  async function dismiss() {
    if (!alert.event_id || reason.trim().length < 10 || reason.trim().length > 500) return;
    setBusy(true);
    setError(undefined);
    try {
      const result = await gatewayRequest("/api", `/v1/kitchens/demo-kitchen/recalls/${encodeURIComponent(alert.event_id)}/dismiss`, {
        method: "POST", body: JSON.stringify({ reason: reason.trim() }),
      }) as { status?: string };
      if (result.status !== "dismissed") throw new Error("Dismissal was not confirmed. Refresh before trying again.");
      setOpen(false);
      reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Dismissal could not be confirmed."); }
    finally { setBusy(false); }
  }
  return <div className="space-y-2 rounded border p-3">
    <p className="text-destructive">
      {alert.status === "dismissed" ? "Recall dismissed for future quotes" : alert.match === "review" ? "Recall warning — check the product" : "BLOCKED_BY_RECALL"}: {alert.product_id} · {alert.recall.title} · {alert.recall.lot ?? "Check affected packs"}
      {/^https:\/\//.test(alert.recall.url) && <> · <a className="underline" href={alert.recall.url} target="_blank" rel="noreferrer">Official recall notice</a></>}
    </p>
    {alert.status === "dismissed" ? <p>{alert.dismiss_reason} · An already held basket stays blocked; close it and request a fresh basket.</p> : alert.event_id && <Button variant="outline" disabled={busy} onClick={() => setOpen(true)}>Dismiss recall after checking packs</Button>}
    {open && <div role="dialog" aria-label="Confirm recall dismissal" className="space-y-3">
      <p>Check the official notice and affected packs first. This dismisses this notice for future quotes only. Other recalls still apply, and this does not approve or release the held basket.</p>
      <label htmlFor={reasonId}>Pack-check reason</label>
      <textarea id={reasonId} className="block w-full rounded border p-2" maxLength={500} value={reason} onChange={e => setReason(e.target.value)} />
      <p>Record 10–500 characters explaining why this kitchen is not affected or how the affected packs were resolved.</p>
      <Button disabled={busy || reason.trim().length < 10} onClick={() => void dismiss()}>I checked the packs — dismiss recall</Button>
      <Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>Cancel dismissal</Button>
    </div>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
interface Proposal {
  proposal_id: string;
  offer_id: string;
  status: string;
  valid_until: string;
  expected_total: string;
  total_ex_vat: string;
  order_id?: string;
  label_checks?: LabelCheck[];
  replacement_proposal_id?: string;
  recall_replan_error?: string;
  product_evidence?: { product_id: string; source_url: string; checked_at: string; via: string;
    pack: string | null; origin: string | null; allergens: string | null }[];
  recall_alerts?: RecallAlert[];
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
  const [confirm, setConfirm] = useState<"approve" | "reject" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [placed, setPlaced] = useState<{ id: string; total: string }>();
  const [rejected, setRejected] = useState(false);
  const unknown = row.lines.some(l => l.unknown_stock);
  const expired = Date.parse(row.valid_until) <= Date.now();
  const pending = row.status === "READY" && !placed && !rejected;
  const rejectable = ["READY", "BLOCKED_BY_RECALL"].includes(row.status) && !placed && !rejected;
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
        } : { reason: "Rejected by chef in the approval inbox", idempotency_key: `web-reject-${row.proposal_id}` }),
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
      setConfirm(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The decision could not be confirmed.");
    } finally { setBusy(false); }
  }
  return <article id={`proposal-${row.proposal_id}`} className="docket space-y-4 rounded-sm border bg-card p-4 text-card-foreground sm:p-5" aria-label={`Proposal ${row.proposal_id}`}>
    <h2 className="text-[19px] leading-[25px] font-[650]">Proposal {row.proposal_id}</h2>
    {typeof row.decision_summary?.text === "string" && <p className="max-w-[68ch] text-[15px] leading-[22px] whitespace-pre-line">{row.decision_summary.text}</p>}
    <ul className="divide-y">{row.lines.map(l => <li key={l.product_id} className="py-2 font-mono text-[13px]">{l.quantity} {l.unit} · {l.product_id} · {l.why}</li>)}</ul>
    {row.label_checks?.map(c => <LabelEvidence key={`${c.product_id}-${c.label}`} check={c} />)}
    {row.recall_alerts?.map((alert, index) => <RecallNotice key={alert.event_id ?? index} alert={alert} reload={reload} />)}
    {row.replacement_proposal_id && <p><a className="underline" href={`#proposal-${row.replacement_proposal_id}`}>Review replacement proposal {row.replacement_proposal_id}</a>. A fresh human approval is required.</p>}
    {row.recall_replan_error && <p>No complete safe replacement is available ({row.recall_replan_error}). The original remains blocked.</p>}
    {row.product_evidence?.map(e => <div key={e.product_id} className="rounded border p-3 text-sm">
      <p>Manufacturer evidence for {e.product_id} · checked {e.checked_at} · {e.via}</p>
      <p>Page pack: {e.pack ?? <span className="unknown-value">unknown</span>} · Bean/ingredient origins: {e.origin ?? <span className="unknown-value">unknown</span>} · Allergen statement: {e.allergens ?? <><span className="unknown-value">unknown</span> — use trusted catalog data</>}</p>
      <p>Informational page claims; the catalog and engine still control allergens and quantities.</p>
      {/^https:\/\//.test(e.source_url) && <a className="underline" href={e.source_url} target="_blank" rel="noreferrer">Manufacturer source</a>}
    </div>)}
    <p className="text-xl font-bold">{formatEur(mapMoney(row.total_ex_vat))} ex VAT · {formatEur(mapMoney(row.expected_total))} including VAT and delivery</p>
    {unknown && <p><span className="unknown-value">Waiting for supplier stock confirmation. Approval is unavailable.</span></p>}
    {expired && pending && <p>This offer has expired. You can review it here: the gateway rechecks price and stock before recording an order. Any change requires a fresh confirmation.</p>}
    {placed ? <p role="status" className="stamp-mark border-success text-sm font-medium text-success">Order recorded: {placed.id} · {formatEur(mapMoney(placed.total))}. Recorded in our gateway; not submitted to Valio.</p> :
      row.status === "APPROVED" ? <p className="stamp-mark border-success text-sm font-medium text-success">Order recorded: {row.order_id ?? "reload to reconcile"}. Recorded in our gateway; not submitted to Valio.</p> :
      !pending ? <p>{rejected ? "REJECTED" : row.status}</p> : null}
    {error && <div role="alert">{error} Check the current proposal before repeating a decision. <Button onClick={reload}>Reload proposals</Button></div>}
    {rejectable && <div className="flex flex-wrap gap-3">
      {pending && <Button className="w-full sm:w-auto" disabled={busy || unknown || !row.lines.length} onClick={() => setConfirm("approve")}>Approve {formatEur(mapMoney(row.expected_total))}</Button>}
      <Button className="w-full sm:w-auto" variant="outline" disabled={busy} onClick={() => setConfirm("reject")}>Reject proposal</Button>
    </div>}
    {confirm === "approve" && pending && <div role="dialog" aria-label="Confirm approval" className="space-y-3 rounded border p-4">
      <p>Confirm this exact basket for {formatEur(mapMoney(row.expected_total))}? The gateway checks price and stock again.</p>
      <Button disabled={busy || unknown} onClick={() => void decide(true)}>Confirm and record order</Button>
      <Button variant="outline" disabled={busy} onClick={() => setConfirm(null)}>Cancel</Button>
    </div>}
    {confirm === "reject" && rejectable && <div role="dialog" aria-label="Confirm rejection" className="space-y-3 rounded border p-4">
      <p>Close this proposal? Its recall notices continue blocking future quotes until a person checks and dismisses them.</p>
      <Button disabled={busy} onClick={() => void decide(false)}>Confirm rejection</Button>
      <Button variant="outline" disabled={busy} onClick={() => setConfirm(null)}>Cancel rejection</Button>
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
    <h1 className="text-[28px] leading-8 font-bold tracking-[-0.015em]">To approve</h1>
    <p className="max-w-[68ch] text-[15px] leading-[22px]">Live demo proposals. A person confirms the exact basket and total before an order is recorded.</p>
    <Button variant="outline" onClick={proposals.reload}>Refresh proposals</Button>
    {proposals.status === "loading" && <p>Loading proposals…</p>}
    {proposals.status === "error" && <p role="alert">{proposals.error.message}</p>}
    {proposals.status === "ready" && (proposals.data.length ? proposals.data.map(row =>
      <ProposalCard key={`${row.proposal_id}-${row.offer_id}-${row.status}`} row={row} reload={proposals.reload} />) : <p>No proposals yet. Ask the Buyer on Requests.</p>)}
  </main></AppShell>;
}
