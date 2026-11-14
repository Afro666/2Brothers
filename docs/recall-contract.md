# Recall holds on proposals

Additive fields on kitchen proposal responses (same kitchen authorization):

- `recall_alerts`: recorded monitor alerts, including product ID, match level,
  notice URL/date, lot or best-before text, and the reason for the match.
- `replacement_proposal_id`: a separately simulated proposal, or null.
- `recall_replan_error`: a bounded machine-readable reason when no safe
  replacement could be produced. A failure never removes the hold.

`BLOCKED_BY_RECALL` is a non-approvable proposal status. Its affected lines
carry `recall_status: "BLOCKED_BY_RECALL"`. Exact and possible matches hold
the original proposal; review-only matches add a warning. An approval of a
held proposal fails with HTTP 409 `BLOCKED_BY_RECALL`.

Replacement proposals are ordinary READY proposals with a different ID,
offer, exact total and pending human approval. Engine sizing and the trusted
kitchen allergen policy apply. A suggested product ID in recall text is not
trusted product or allergen data. Failure to find a safe replacement leaves
the original blocked. No monitor call places an order.

The internal monitor applies recorded notices to currently open proposals
through the shared store and gateway modules. There is no public mutation
route accepting arbitrary recall alerts from a browser or model. Repeated
polls preserve the original notice event and replacement identity.

Ordering is serialized against a recall hold on the proposal state. An
already committed order is not cancelled by a later notice; it remains an
audited recall incident requiring human follow-up.
