# Recall holds on proposals

Additive fields on kitchen proposal responses (same kitchen authorization):

- `recall_alerts`: recorded monitor alerts, including product ID, match level,
  notice URL/date, lot or best-before text, and the reason for the match.
- `replacement_proposal_id`: a separately simulated proposal, or null.
- `recall_replan_error`: a bounded machine-readable reason when no safe
  replacement could be produced. A failure never removes the hold.

## Exact alert fields

The names below match `monitor.recalls.scan`; `review` is the warning enum
value (not `review_only`). Every alert has these fields unless marked optional.

| Field | JSON type | Meaning |
| --- | --- | --- |
| `event_id` | string | Stable recall/kitchen/product event identifier. |
| `type` | string, always `recall.alert` | Event type. |
| `kitchen_id`, `product_id` | string | Scoped kitchen and catalog product IDs. |
| `product_name` | string or null | Catalog English name, when known. |
| `match` | `exact`, `possible`, `review` | Barcode match, brand/product match, or human review warning. |
| `why` | string | Explanation of the product match. |
| `where` | string[] | Detection-time stock/recipe/proposal context; not live inventory. |
| `next_step` | string | Pack/lot checking instructions. |
| `detected_at` | ISO 8601 datetime string | First recorded detection time. |
| `replacement_proposal` | object[] | Up to three unapproved ideas: `product_id` string, `name` and `brand` string or null. Not engine quotes. |
| `recall` | object | Source notice, with fields below. |
| `status` | `active` or `dismissed`, optional | Omitted legacy status means active. |
| `dismissed_by`, `dismissed_at`, `dismiss_reason` | string, optional | Human identity, ISO 8601 datetime, and recorded reason after dismissal. |

| `recall` field | JSON type | Meaning |
| --- | --- | --- |
| `url` | HTTPS URL string | Official notice source. |
| `date` | `YYYY-MM-DD` string or null | Notice publication date. |
| `title`, `reason`, `action` | string or null | Notice heading, hazard and official action. |
| `recalled_product`, `brand`, `gtin`, `package_size` | string or null | Explicit notice facts; unknown facts remain null. |
| `lot` | string or null | Exact lot/best-before text. Null never means all packs are safe. |

`recall_replan_error` is null on success/no error, otherwise exactly one of:

| Code | Meaning |
| --- | --- |
| `KITCHEN_POLICY_UNKNOWN` | No explicit trusted kitchen allergen policy. |
| `NO_SAFE_REPLACEMENT` | No eligible different-brand, non-recalled alternative with known safe allergen data. |
| `REPLACEMENT_SHORTFALL` | The engine could not cover the complete need; the partial replacement is rejected. |
| `REPLACEMENT_UNAVAILABLE` | Quoting or replacement persistence failed; the original hold remains. |

Unknown future error codes must display a generic failure and keep the hold.
Supplier stock uncertainty is carried by `lines[].unknown_stock`; it is not
a fifth replan error. Engine sizing never establishes allergen safety.

## Human recovery (#459)

> **Proposed, not served yet.** The gateway does not serve the dismiss route
> (`POST /v1/kitchens/{kitchen_id}/recalls/{event_id}/dismiss`) yet, and it does
> not yet reject `BLOCKED_BY_RECALL` proposals. Both are tracked in #459. Remove
> this note when #459 merges.

The existing `POST /v1/kitchens/{kitchen_id}/proposals/{proposal_id}/reject`
also accepts `BLOCKED_BY_RECALL`. It closes that basket and its pending approval,
without dismissing the recall for future quotes. Approval and rejection compete
on the proposal state; a committed/approved order cannot be rejected here.

`POST /v1/kitchens/{kitchen_id}/recalls/{event_id}/dismiss` requires the same
human session as approval, plus the usual kitchen authorization. Body:
`{"reason": "Checked packs; the affected lot is not held here"}`. Reason must
be a trimmed string of 10–500 characters. The UI requires explicit confirmation
that the person checked affected packs and the notice. The response is:

```json
{
  "event_id": "recall-example",
  "status": "dismissed",
  "dismissed_by": "chef",
  "dismissed_at": "2026-11-14T02:00:00+00:00",
  "dismiss_reason": "Checked packs; affected lot is not held here"
}
```

Missing/scoped-out events return 404 `RECALL_NOT_FOUND`; agent-only sessions
return 403 `HUMAN_SESSION_REQUIRED`; invalid reasons return 422
`INVALID_REQUEST`. Repeating a dismissal returns the first stored decision and
its single audit event. It does not overwrite the first person's reason.
Dismissal prevents that event from blocking future quotes or being reapplied by
a repeat monitor poll. Other active events for the product continue to block.
Already held baskets remain held and must be rejected; a newly quoted basket
requires a new human approval. Nothing is automatically ordered or cancelled.
There is no automatic recall expiry: publication age does not prove lot safety.

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
