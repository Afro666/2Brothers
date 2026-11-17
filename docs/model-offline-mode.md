# Explicit Nemotron offline mode

Set `NEMOTRON_ENABLED=false` in the deployment environment and recreate the
gateway and Buyer containers. The Compose file forwards the flag to both services.
No runtime environment or running deployment is changed by adding this option.

Enabled values are `true`, `1` and `on` (case-insensitive); the default is `true`.
Other values disable the model. Disabled free-text requests use the existing
deterministic fallback before contacting the Buyer worker. The existing ambiguity
checks still forbid retrying a request that might already have created a proposal.
Multi-item splitting uses its existing code fallback. Photo and text-generation
readers report their existing unavailable errors without opening a model client;
they do not invent results or silently switch to another provider.

The internal Buyer's `/health` remains a liveness check. Its additional fields are:

- `model_enabled`: the explicit operator setting.
- `model_configured`: enabled with a nonempty model credential; not a connectivity check.
- `model_reachable`: null, because liveness makes no inference request.

These booleans expose no key, model host or provider error text. A successful
liveness response does not establish that inference works. Kimi and DeepSeek
coding-worker access is independent of this application's Nemotron setting.
