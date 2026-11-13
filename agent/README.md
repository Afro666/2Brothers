# Nemotron buyer (#22)

Install from the repository root: `python -m pip install -e .`. The CLI loads the
root `.env` without overwriting exported variables. `VERDA_INFERENCE_KEY` selects
the shared Verda Nemotron 3.5 Super VL endpoint. Never use cloud credentials or
the separate project inference key for this endpoint.

```powershell
python -m agent "1,000 L of lactose-free milk by Monday" --need-id milk-need-1 --date 2026-11-16 --mock
```

`--mock` uses **live Nemotron inference credits** with an isolated, deterministic
mock HTTP gateway; no real orders or database writes occur. Output labels this
mode explicitly. The mock covers only `milk-need-1` and product `462775`.
The expected result is `SENT_FOR_APPROVAL`, because only 51 L is confirmed.
The full 1,000 L need has not been fulfilled. This is not a live Valio quote.

For a live gateway, omit `--mock` and set `GATEWAY_BASE_URL`. The application must
first persist a trusted need and supply its ID and date. Gateway routes, stored
needs and durable `/audit/events` ingestion are external dependencies; see
`docs/contract.md` (#51), gateway #19 and catalog search #25. The agent does not
connect directly to MongoDB. Keep the gateway private until authenticated,
tenant-scoped deployment exists. No public server is started by this CLI.

The model selects tools and explains its choices. The buyer loop independently
checks catalog product IDs, trusted need/date, offer expiry, simulation, mandate,
exact totals and one attempt per mutation. It generates stable order keys and
never exposes approve, cancel, release or quantity-changing tools. The gateway
must enforce all checks again. Unknown or malformed responses stop the run.

Read-only policy recovery (#67): when the buyer rejects `search_products`,
`get_offer`, `simulate_order`, `get_order_status` or `get_audit_log` before
dispatch, it audits the attempt and returns a fixed `POLICY_REJECTED` tool error
to the model. The model may correct arguments within the existing step and
30-call limits. Rejected calls are never sent to the gateway. This does not
recover gateway failures, malformed tool responses, missing call IDs, or
unknown/malformed tool names. Mutation rejections and failures still stop immediately; audit failure
always stops dispatch, including during recovery.

Each tool attempt writes start and finish events through gateway audit ingestion.
Audit failure stops dispatch. A failure after a mutation explicitly requires human
reconciliation. The local `.local/traces/<run-id>.jsonl` file supplements durable
audit with readable structural events. It never proves a database write by itself;
mock audit is only in memory. Model and gateway errors are sanitized.

The final JSON has `status` (`ORDER_PLACED`, `SENT_FOR_APPROVAL`, `CANNOT_FULFIL`),
`reason`, `run_id`, relevant order/approval ID, and `reconciliation_required` on
ambiguous failures. These outcomes come from gateway evidence, never model claims.
The loop permits at most 12 model steps by default (maximum configurable 30) and
30 tool calls. Model reads retry 429/5xx/network failures up to twice; gateway
mutations are never automatically retried.

Offline checks: `python -m unittest discover -s agent/tests -v`.

## Submission notes

- Nemotron performs product discovery and selects the offer/simulation/approval
  sequence through the seven MCP tools. All quantities and prices come from the
  gateway and engine, not the model.
- Codex implemented #20's upstream adapter, #21's MCP integration and this loop
  using separate issue branches and Opus-reviewed PRs.
- Improvements to the agent are enforced at runtime: independent policy checks,
  bounded steps, exact simulated totals, stable mutation keys and audit-before-call.
- Offline tests cover unsafe attempted actions and incomplete transport outcomes;
  the live-model mock-gateway smoke test checks actual Nemotron tool selection.
- Real gateway integration and database-backed audit remain separate dependencies.

Verified live-model smoke test (2026-11-13): Nemotron selected `search_products`
→ `get_offer` → `simulate_order` → `request_approval` against the explicit mock
gateway. The final result was `SENT_FOR_APPROVAL`, with eight structural audit
events and a local JSONL trace. No live purchase or MongoDB write was performed.
