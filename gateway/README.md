# Valio adapter

From the repository root, install with `python -m pip install -e .` and export
`VALIO_API_KEY` in your shell (or load your local `.env` before starting Python).

```python
from gateway.valio_client import ValioClient

client = ValioClient()
client.ping()
prices = client.price(["462775", "462921"], "2026-11-16")
stock = client.availability(["462775", "462921"], "2026-11-16")
```

Requests use bounded 1,000-code chunks, a 30-second bounded cache and up to two
retries for network errors, HTTP 429 and 5xx. Only read operations are implemented.
Do not use this retry policy for gateway order placement. Check each price row's
`error` flag. Both stock sentinels become `availableAmount: null` with
`unknown_stock: true`. `closingTime` includes a timezone; `cutoff_passed` is
recomputed even on cache hits. Missing cutoffs or stock never produce an
`orderable: true` result. This is a preliminary upstream check, not mandate consent.
`orderable` also requires a valid `availableDate` no later than the requested date.
Later dates remain visible in the response for proposing a different delivery,
but must not be treated as fulfilment of the original deadline.

Run offline tests: `python -m unittest discover -s gateway/tests -v`.
Fixtures are small responses recorded from the challenge API, without credentials.

## MCP adapter (#21)

Start the stdio MCP server with `python -m gateway.mcp_server`. Set
`GATEWAY_BASE_URL` for the team HTTP gateway, defaulting to localhost port 8000.
No upstream API key is sent to the gateway. Keep it on a trusted internal network;
public deployment needs authentication and tenant authorization in the gateway.
The shared routes and fields live in `docs/contract.md` (contract PR #51).

For an isolated demo, explicitly run `python -m gateway.mcp_server --mock`.
This simulates a pending milk approval, never a live purchase. The real HTTP
gateway is a separate dependency (#19/#25); it is not implemented by this adapter.

All seven tools have typed inputs and restrictive descriptions. There are no
approve/cancel tools or model-supplied quantities. Mutation requests are sent
once; ambiguous transport failures must be reconciled before another attempt.
The mock has no persistence and is intended only for demos and tests.

Tests use an actual SDK MCP client and HTTP mock transport, plus a subprocess
stdio handshake. Run the same unittest command above after installing the project.
