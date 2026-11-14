# Public-docs-only Buyer experiment (#372)

On 2026-11-14, a fresh OpenAI Codex CLI session generated the
[client](../../../agent/examples/public_buyer_client.py) using only the public
site's `/llms.txt` and `/gateway/openapi.json`. No repository files were supplied
or read by that session. It ran in an initially empty directory with user config,
bundled skills and previous session context excluded. This was context isolation,
not an OS guarantee that other local files were inaccessible.

The explicit successful model was `gpt-6.1-sol`, using ChatGPT browser login.
No Verda model was invoked. The agent never received the kitchen token. The host
reviewed the generated client, then supplied the token through its environment
for one live execution. This is an operator-assisted experiment, not an autonomous
purchase or proof that an unauthenticated visitor can order.

## Evidence

- [Exact prompt](prompt.txt), repeated across four fresh CLI attempts.
- [Successful generation screen recording](generation.mp4): actual live CLI
  output in a dedicated window, cropped to that window. No desktop or credentials.
- [Generation transcript](generation-transcript.txt): commands and responses;
  no hidden reasoning or credentials.
- [Actual live result](live-result.json): proposal
  `0619d3c19a7b494d9d5a2b1e38795c29`, status `PENDING`, verdict `NEEDS_APPROVAL`,
  expected total EUR 2545.01. Stock remains unconfirmed on some lines; the costly
  confirmed alternative exceeds the configured price premium. No approval or
  order placement was called.
- [Manifest](manifest.json): client SHA-256, all attempt durations and wall time.

## Failures and timing

There was one task prompt, submitted in four invocations, with three operator
configuration retries. Attempt 1 selected `gpt-5.4`, unsupported by this ChatGPT
login (6.1 s). Attempt 2 could not execute/write under the local policy (21.1 s).
Attempt 3 fetched the docs but was interrupted before writing a client (49.3 s).
Attempt 4 used a separate process group and completed in 70.7 s. The first live
client execution then succeeded without changing the generated code.

Operator-inclusive wall time from the first attempt to the saved live result was
408.6 s (6 min 49 s), derived from local file timestamps. This includes setup,
review and waiting. It is not a measured coding speed-up or a one-minute
end-to-end success. The client hash in the manifest identifies the exact bytes run.

## Reproduce

Set `BUYER_TOKEN` privately in the process environment and `BUYER_KITCHEN_ID` to
your kitchen. Run `python public_buyer_client.py` in a new working directory.
The script creates one proposal-flow state file and never approves or places an
order. Its fixed request date is **2026-11-16**; this artifact records that day's
experiment, not a rolling-date production client.

Do not remove `buyer-state.json` to retry an uncertain write. Reconcile its saved
IDs with the gateway first. The OpenAPI document did not describe request bodies;
the client followed the concrete workflow payloads in `/llms.txt`.
