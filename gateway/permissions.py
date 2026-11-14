"""What the Buyer does alone, what a person signs off, what it can never do (#273).

One source for the Permissions screen and the docs. Every "never" row names the gateway
rule that enforces it, and gateway/tests/test_permissions.py proves each one against the
running app, so this table cannot drift from the code.
"""

from __future__ import annotations

ALONE = [
    {"action": "Search the catalog", "audit_kind": "search",
     "rule": "Read-only search; products with no allergen data are shown as unknown, never as safe."},
    {"action": "Compare price, reliability and carbon", "audit_kind": "offer",
     "rule": "Live Valio price and stock only for the shortlisted products; within 3% on price the more reliable, then lower-carbon offer wins."},
    {"action": "Choose products", "audit_kind": "offer",
     "rule": "The Buyer picks product codes; it cannot pass a quantity. The gateway sizes every line from the stored need."},
    {"action": "Size quantities", "audit_kind": "simulate",
     "rule": "Done by the engine (packs, lot sizes, confirmed stock first), never by the model."},
    {"action": "Split an order", "audit_kind": "simulate",
     "rule": "Confirmed stock first, the rest on the cheapest unconfirmed offer, a shortfall is reported."},
    {"action": "Refuse unsafe lines", "audit_kind": "mandate_check",
     "rule": "A passed cut-off, a sales block, a kitchen allergen rule or a recall removes the line, with the reason."},
    {"action": "Ask for approval", "audit_kind": "approval",
     "rule": "Every proposal opens a pending approval with the exact total a person will see."},
]

PERSON = [
    {"action": "Every order", "audit_kind": "approval",
     "rule": "An approver says yes to the total shown; the gateway re-checks live price and stock and refuses if it moved (TOTAL_MISMATCH)."},
    {"action": "Any substitute", "audit_kind": "approval",
     "rule": "A substitute is proposed with what changes; a person picks it."},
    {"action": "Standing-order changes", "audit_kind": "settings",
     "rule": "Drift is shown; the standing order changes only when a person edits it."},
    {"action": "Sharing forecasts", "audit_kind": "forecast_share",
     "rule": "Only a person grants or revokes sharing with a supplier; each change is an audit entry."},
    {"action": "API tokens and webhooks", "audit_kind": "token_created",
     "rule": "Only an approver creates or revokes them; a token can read or propose, never approve."},
]

NEVER = [
    {"action": "Approve or reject an order", "audit_kind": "approval", "id": "approve",
     "rule": "Approve and reject need a signed-in approver: 403 HUMAN_SESSION_REQUIRED for the agent and for every API token; kitchen:approve cannot be put on a token."},
    {"action": "Place an order nobody approved", "audit_kind": "order", "id": "place_unapproved",
     "rule": "place_order returns 403 NEEDS_APPROVAL until a person approved that exact offer."},
    {"action": "Cancel an order", "audit_kind": "order", "id": "cancel",
     "rule": "No cancel tool or route exists for the agent."},
    {"action": "Change a quantity", "audit_kind": "order", "id": "change_quantity",
     "rule": "Tools take product codes only; quantities come from the stored need, and an approved order has no edit route."},
    {"action": "Act for another kitchen", "audit_kind": "token_created", "id": "other_kitchen",
     "rule": "A token is bound to one kitchen: 403 KITCHEN_SCOPE elsewhere."},
]


def matrix() -> dict:
    strip = lambda rows: [{k: v for k, v in r.items() if k != "id"} for r in rows]  # noqa: E731
    return {"alone": strip(ALONE), "person": strip(PERSON), "never": strip(NEVER)}
