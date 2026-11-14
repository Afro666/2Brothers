"""Webhook `supplier.offer` (#1188): one delivery per offer step, only to its kitchen."""

import json
import time

import pytest

from gateway import webhooks
from gateway.tests.test_gateway_app import HUMAN
from gateway.tests.test_supplier_offers import K1, SHORT, SUBS, World
from gateway.tests.test_webhooks import env, make, receiver  # noqa: F401

KEYS = {"step", "offer_id", "supplier_id", "product_id", "replaces_product_id", "requested_date",
        "quantity", "unit"}
URL1 = "https://hooks.example.com/k1"
URL2 = "https://hooks.example.com/k2"


@pytest.fixture()
def w(monkeypatch):
    return World(monkeypatch)


def subscribe(client, kitchen_id, url):
    r = client.post(f"/v1/kitchens/{kitchen_id}/webhooks", headers=HUMAN,
                    json={"url": url, "events": ["supplier.offer"]})
    assert r.status_code == 200, r.text
    return r.json()


def test_a_new_offer_sends_one_received_event_with_the_documented_keys(w, receiver):
    subscribe(w.client, "K1", URL1)
    offer = w.offer().json()
    assert receiver.events() == ["supplier.offer"]
    data = json.loads(receiver.calls[0]["body"])["data"]
    assert set(data) == KEYS
    assert data == {"step": "RECEIVED", "offer_id": offer["offer_id"], "supplier_id": "sup-valio",
                    "product_id": SUBS[0], "replaces_product_id": SHORT,
                    "requested_date": "2026-11-16", "quantity": offer["quantity"],
                    "unit": offer["unit"]}
    assert w.offer().json()["offer_id"] == offer["offer_id"]     # the same idempotency key
    assert len(receiver.calls) == 1                               # a replay sends nothing more


def test_accept_and_decline_send_their_step_and_never_the_reason(w, receiver):
    subscribe(w.client, "K1", URL1)
    first = w.offer().json()
    accepted = w.client.post(f"{K1}/{first['offer_id']}/accept", headers=HUMAN).json()
    assert accepted["proposal_status"] == "READY"
    second = w.offer(key="o2", product_id=SUBS[1]).json()
    declined = w.client.post(f"{K1}/{second['offer_id']}/decline", headers=HUMAN,
                             json={"reason": "NO-OAT-TEXT"}).json()
    assert declined["status"] == "DECLINED"
    assert receiver.events() == ["supplier.offer"] * 4
    accepted_data = json.loads(receiver.calls[1]["body"])["data"]
    assert accepted_data["step"] == "ACCEPTED"
    assert accepted_data["proposal_id"] == accepted["proposal_id"]
    assert set(accepted_data) == KEYS | {"proposal_id"}
    declined_data = json.loads(receiver.calls[3]["body"])["data"]
    assert declined_data["step"] == "DECLINED" and set(declined_data) == KEYS
    assert all(b"NO-OAT-TEXT" not in call["body"] for call in receiver.calls)


def test_only_the_offer_kitchen_hook_gets_the_event(w, receiver):
    subscribe(w.client, "K1", URL1)
    subscribe(w.client, "K2", URL2)              # a second kitchen that shares its forecast too
    w.offer(kitchen_id="K1")
    assert [call["url"] for call in receiver.calls] == [URL1]
    assert w.db.webhooks.count_documents({}) == 2


def test_wait_for_deliveries_joins_the_started_threads(env, monkeypatch):
    client, _, db = env
    make(client, ["proposal.ready"])
    sent = []

    def slow(url, body, headers):
        time.sleep(0.25)
        sent.append(body)
        return 200

    monkeypatch.setattr(webhooks, "http_send", slow)  # run_async stays real
    webhooks.dispatch(db, "demo-kitchen", "proposal_created", {"proposal_id": "p1"})
    assert sent == [] and db.webhook_deliveries.count_documents({}) == 0
    webhooks.wait_for_deliveries(timeout=5)
    row = db.webhook_deliveries.find_one({})
    assert row is not None and row["event"] == "proposal.ready" and row["ok"] is True
    assert len(sent) == 1
