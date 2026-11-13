# Nemotron buyer (#22)

## Internal worker (#279)

`two-brothers-buyer-worker` serves an internal `/run` endpoint on port 8001.
The gateway's existing `POST /v1/kitchens/{k}/proposals` hands free-text bodies
(`text`, optional `requested_date`, `idempotency_key`) to it when `product_ids`
is absent. Structured engine requests retain their existing path.

The worker accepts only the server's agent token and configured
`GATEWAY_KITCHEN_ID`; it is not published to the browser. It creates a stored
need through the gateway, runs Nemotron through the seven existing MCP tools,
and returns the READY proposal plus `buyer_run_id` and `buyer_model`. Every model
tool step is audited. No orders are placed and no human credential is supplied.

For now a request must contain exactly one explicit positive quantity in L, KG
or PCS. An explicit requested date is preferred; a single named weekday can be
resolved to the next occurrence in Helsinki. Ambiguous quantities, missing dates
or unsupported units return a details-needed error instead of invented amounts.
This parser only establishes the trusted need; the gateway engine sizes lines.

The `buyer` Compose service uses the gateway image with the worker entrypoint.
Server configuration needs `VERDA_INFERENCE_KEY`, `MONGODB_URI`,
`GATEWAY_AGENT_TOKEN`, `GATEWAY_KITCHEN_ID` and `GATEWAY_BASE_URL`.
The gateway uses `BUYER_WORKER_URL=http://buyer:8001`. The worker receives neither
the human token nor the Valio API key. Keys stay in the server `.env`.

Jobs are deduplicated durably through `store.agent_runs` by kitchen and request
key. Exact completed replays return the same proposal. Running, failed or
ambiguous jobs require reconciliation; changed content under the same key is
409. There is no automatic mutation retry. Runs are bounded to 150 seconds and
12 model steps. Errors disclose a `fallback_safe` boolean: a separate fallback
parser may run only when no approval/order mutation was attempted. In particular,
a transport failure at the gateway handoff is ambiguous and never permits an
automatic fallback. The fallback parser itself remains a separate gateway task.

Offline verification: `python -m pytest agent/tests/test_service.py`. This uses
the actual Buyer, MCP SDK and gateway routes, recorded Valio data and a scripted
model. A live inference check must be labelled separately from these tests.

Install from the repository root: `python -m pip install -e .`. The CLI loads the
root `.env` without overwriting exported variables. Copy `.env.example` to `.env`
and fill in `VERDA_INFERENCE_KEY`, which selects
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

Every order requires recorded human approval (#144, contract #143). Accepted
mandate verdicts are `NEEDS_APPROVAL` and `REFUSED` only. The CLI requests a human
decision and stops; it has no approval lookup and cannot place an order.

An authenticated host that resumes approved work may supply the synchronous
`Buyer(..., approval_lookup=...)` callback. It must fetch the stored approval
through `store`, scoped to the authenticated kitchen and requested offer. The
callback is application configuration, never a model argument or tool. Buyer
requires a matching offer, `APPROVED` status, nonempty approval/decider IDs and a
timezone-aware decision timestamp no later than now. Missing, pending, rejected
or invalid records and lookup failures deny placement. The offer must still be
valid, the exact total must still match simulation, and the gateway must verify
the stored human decision again before committing. Buyer never records a human
decision itself or treats a warning as approval.

Read-only policy recovery (#67): when the buyer rejects `search_products`,
`get_offer`, `simulate_order`, `get_order_status` or `get_audit_log` before
dispatch, it audits the attempt and returns a fixed `POLICY_REJECTED` tool error
to the model. The model may correct arguments within the existing step and
30-call limits. Rejected calls are never sent to the gateway. This does not
recover gateway failures, malformed tool responses, missing call IDs, or
unknown/malformed tool names. Mutation rejections and failures still stop immediately; audit failure
always stops dispatch, including during recovery.

`reason_code` comes from the closed `PolicyReason` enum (#96).
The envelope remains `{"error": {"code": "POLICY_REJECTED", ...}}`;
`reason_code` is inside that error object. It gives only the category to correct:

| Reason code | Meaning |
|---|---|
| `SCHEMA_INVALID` | Arguments do not match the tool schema, have an invalid encoding type, or are missing. |
| `MALFORMED_JSON` | The arguments string is not valid JSON. |
| `NEED_MISMATCH` | Use the application-provided need ID. |
| `DATE_MISMATCH` | Use the application-provided delivery date. |
| `UNKNOWN_ID` | Product, offer or order ID is not known in this run. |
| `OFFER_INVALID` | Refresh an offer with expired, missing or invalid validity data. |
| `RUN_MISMATCH` | Audit query must use the current run ID. |
| `POLICY_VIOLATION` | Generic fallback for another local policy rejection. |

Codes never contain actual IDs, dates, quantities, field paths, exception text or
upstream text. The audit finish event records the same fixed code. Classification
does not grant retries: only the existing known read-only rejection paths can
recover, with the same audit requirements, step limit and 30-call limit.

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

Recovery smoke test (2026-11-13, #67): an injected search call missing `filters`
was rejected before dispatch. Live Nemotron corrected it from the sanitized
feedback, then completed the milk proposal flow with `SENT_FOR_APPROVAL`.
The mock received one valid search and recorded ten audit events, including the
rejection. No live purchase or MongoDB write was performed.
