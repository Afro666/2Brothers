"""The agent audit ingestion contract (POST /audit/events).

Only the fields the contract names are accepted, and an agent can never pre-write the
id the gateway derives for its own events (for example a proposal rejection).
"""

from gateway import service
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env, milk  # noqa: F401
from store.audit import list_events


def post(client, body, headers=AGENT):
    return client.post("/audit/events", headers=headers, json=body)


def test_unknown_fields_such_as_kind_and_actor_are_refused(env):
    client, _, db = env
    before = db.audit_log.count_documents({})
    r = post(client, {"event_id": "e1", "type": "tool_call_started",
                      "kind": "order_placed", "actor": "human"})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "INVALID_REQUEST"
    assert db.audit_log.count_documents({}) == before


def test_an_unknown_type_is_refused(env):
    client, _, db = env
    before = db.audit_log.count_documents({})
    r = post(client, {"event_id": "e2", "type": "order_placed"})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "INVALID_REQUEST"
    assert db.audit_log.count_documents({}) == before


def test_a_tool_call_is_stored_under_a_namespaced_id_and_exact_replays_append_nothing(env):
    client, _, db = env
    body = {"event_id": "client-event-1", "run_id": "run-1", "type": "tool_call_started",
            "tool": "search_products", "arguments": {"query_present": True}}
    first = post(client, body)
    assert first.status_code == 200, first.text
    assert first.json() == {"event_id": "client-event-1", "stored": True}

    stored = db.audit_log.find_one({"event.event_id": "agent:demo-kitchen:client-event-1"})
    assert stored is not None
    assert stored["event"]["event_id"].startswith("agent:demo-kitchen:")
    assert db.audit_log.count_documents({"event.type": "tool_call_started"}) == 1

    replay = post(client, body)
    assert replay.status_code == 200, replay.text
    assert replay.json() == {"event_id": "client-event-1", "stored": True}
    assert db.audit_log.count_documents({"event.type": "tool_call_started"}) == 1

    conflict = post(client, {**body, "tool": "get_offer"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert db.audit_log.count_documents({"event.type": "tool_call_started"}) == 1


def test_an_agent_cannot_squat_the_gateways_derived_rejection_event_id(env):
    client, _, db = env
    p = milk(client)
    derived = "proposal-rejected:" + service._hash(["demo-kitchen", p["proposal_id"]])
    squat = post(client, {"event_id": derived, "type": "tool_call_started", "tool": "search_products"})
    assert squat.status_code == 200, squat.text

    rejected = client.post(f"{K}/proposals/{p['proposal_id']}/reject", headers=HUMAN,
                           json={"reason": "too much"})
    assert rejected.status_code == 200, rejected.text
    rows = [e for e in list_events(db, kitchen_id="demo-kitchen")
            if e["event"].get("kind") == "proposal_rejected"]
    assert len(rows) == 1
    assert rows[0]["event"]["proposal_id"] == p["proposal_id"]
