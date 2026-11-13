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

Run offline tests: `python -m unittest discover -s gateway/tests -v`.
Fixtures are small responses recorded from the challenge API, without credentials.
