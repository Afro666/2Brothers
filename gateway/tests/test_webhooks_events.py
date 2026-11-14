"""New webhook events (#1188): a refused agent action and a checked delivery.

The audit trail is the source; these tests check the two event bodies, the refusal
throttle and that a hook only gets what it subscribed to.
"""

import json

import pytest

from gateway import webhooks
from gateway.tests.test_delivery_note import BODY, ORDER, URL as NOTE_URL, FakeWorker, make as note_client
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, milk
from gateway.tests.test_webhooks import env, make, receiver  # noqa: F401 (fixtures)

APPROVE_ROUTE = "/v1/kitchens/{kitchen_id}/proposals/{proposal_id}/approve"


@pytest.fixture(autouse=True)
def fresh_refusal_memory(monkeypatch):
    """The throttle is in-process; each test starts without earlier refusals."""
    monkeypatch.setattr(webhooks, "_refused_seen", {})
    monkeypatch.setattr(webhooks, "_clock", lambda: 1000.0)


def test_a_refused_agent_approve_sends_the_route_pattern_and_no_path(env, receiver):
    client, _, _ = env
    make(client, ["agent.refused"])
    p = milk(client)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=AGENT,
                    json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"
    assert receiver.events() == ["agent.refused"]
    data = json.loads(receiver.calls[0]["body"])["data"]
    assert data == {"actor": "buyer-agent", "code": "HUMAN_SESSION_REQUIRED", "method": "POST",
                    "route": APPROVE_ROUTE}
    assert "path" not in data and p["proposal_id"] not in json.dumps(data)


def test_refusals_are_one_delivery_a_minute_per_actor_and_code(env, receiver, monkeypatch):
    client, _, db = env
    make(client, ["agent.refused"])
    now = [1000.0]
    monkeypatch.setattr(webhooks, "_clock", lambda: now[0])
    data = {"code": "HUMAN_SESSION_REQUIRED", "method": "POST", "route": APPROVE_ROUTE,
            "path": "/v1/kitchens/demo-kitchen/proposals/p-1/approve"}
    for _ in range(5):
        webhooks.dispatch(db, "demo-kitchen", "refused", data, actor="buyer-agent")
    assert receiver.events() == ["agent.refused"]
    now[0] += 61
    webhooks.dispatch(db, "demo-kitchen", "refused", data, actor="buyer-agent")
    assert receiver.events() == ["agent.refused", "agent.refused"]
    webhooks.dispatch(db, "demo-kitchen", "refused", {**data, "code": "NEEDS_APPROVAL"},
                      actor="buyer-agent")
    assert receiver.events() == ["agent.refused"] * 3


def test_a_refusal_with_a_concrete_path_as_route_sends_no_route(env, receiver):
    client, _, db = env
    make(client, ["agent.refused"])
    webhooks.dispatch(db, "demo-kitchen", "refused",
                      {"code": "HUMAN_SESSION_REQUIRED", "method": "POST",
                       "route": "/v1/kitchens/demo-kitchen/proposals/p-1/approve"},
                      actor="buyer-agent")
    assert receiver.events() == ["agent.refused"]
    data = json.loads(receiver.calls[0]["body"])["data"]
    assert data["route"] is None and "p-1" not in json.dumps(data)


def test_a_checked_delivery_sends_only_the_documented_counters(monkeypatch, receiver):
    client, _ = note_client(monkeypatch, FakeWorker())
    make(client, ["delivery.checked"])
    r = client.post(NOTE_URL, headers=HUMAN, json=BODY)
    assert r.status_code == 200, r.text
    assert receiver.events() == ["delivery.checked"]
    data = json.loads(receiver.calls[0]["body"])["data"]
    assert set(data) == {"order_id", "statuses", "complete", "needs_approval", "duration_ms"}
    assert (data["order_id"], data["statuses"], data["complete"], data["needs_approval"]) == (
        ORDER, {"SHORT": 1, "SUBSTITUTE": 1}, False, 1)
    assert isinstance(data["duration_ms"], int)
    sent = json.dumps(data)
    assert BODY["image_base64"][:200] not in sent and "ORD-DEMO" not in sent


def test_both_events_are_offered_and_a_hook_gets_only_its_subscriptions(env, receiver, monkeypatch):
    client, _, db = env
    offered = client.get(K + "/webhooks", headers=HUMAN).json()["events"]
    assert {"agent.refused", "delivery.checked"} <= set(offered)
    make(client, ["proposal.ready"])
    milk(client)
    webhooks.dispatch(db, "demo-kitchen", "refused",
                      {"code": "HUMAN_SESSION_REQUIRED", "method": "POST", "route": APPROVE_ROUTE,
                       "path": "/v1/kitchens/demo-kitchen/proposals/p-1/approve"}, actor="buyer-agent")
    webhooks.dispatch(db, "demo-kitchen", "delivery_note_read",
                      {"order_id": ORDER, "statuses": {"SHORT": 1}, "complete": False,
                       "needs_approval": 0, "duration_ms": 12}, actor="aron")
    assert receiver.events() == ["proposal.ready"]
