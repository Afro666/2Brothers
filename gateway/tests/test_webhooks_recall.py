"""Recall alert webhooks for stock matches and blocked purchase proposals (#1187)."""

import json
from datetime import timedelta

from gateway.tests.test_recall_routes import COFFEE, HUMAN, K, NOW, check, env  # noqa: F401 (fixture)
from gateway.tests.test_webhooks import URL, receiver  # noqa: F401 (fixture)
from store.history import record_stock_count


def make(client):
    r = client.post(K + "/webhooks", headers=HUMAN, json={"url": URL, "events": ["recall.alert"]})
    assert r.status_code == 200, r.text
    return r.json()


def stock_only(env):
    """Leave the recalled coffee on the shelf, with no open proposal to block."""
    client, db, gw, _ = env
    db.proposals.delete_many({})
    db.offers.delete_many({})
    record_stock_count(db, "hotel", NOW - timedelta(days=1),
                       [{"product_id": COFFEE, "unit": "KG", "on_hand": "3.253"}])
    return client, db, gw


def sent(receiver, case=None):
    return [json.loads(call["body"]) for call in receiver.calls
            if case is None or json.loads(call["body"])["data"].get("case") == case]


def test_stock_match_sends_one_found_alert(env, receiver):
    client, db, _ = stock_only(env)
    make(client)
    response = check(client)
    assert response.status_code == 200, response.text
    [alert] = response.json()["alerts"]
    [delivery] = sent(receiver)
    assert delivery["event"] == "recall.alert"
    assert delivery["data"] == {
        "case": "FOUND", "recall_event_id": alert["event_id"], "product_id": COFFEE,
        "product_name": alert["product_name"], "match": "possible",
        "found": {"stock": True, "recipes": 0, "open_proposal": False},
        "notice_url": alert["recall"]["url"], "next_step": alert["next_step"]}
    row = db.webhook_deliveries.find_one({})
    assert row["once_key"] == alert["event_id"] and row["ok"] is True


def test_later_check_does_not_send_the_same_alert_again(env, receiver):
    client, db, gw = stock_only(env)
    make(client)
    check(client, "one")
    gw.now = lambda: NOW + timedelta(seconds=60)
    check(client, "two")
    assert len(sent(receiver, "FOUND")) == 1
    assert db.webhook_deliveries.count_documents({}) == 1


def test_alert_from_before_hook_registration_is_sent_once(env, receiver):
    client, _, gw = stock_only(env)
    check(client, "one")
    assert receiver.calls == []
    make(client)
    gw.now = lambda: NOW + timedelta(seconds=60)
    check(client, "two")
    assert len(sent(receiver, "FOUND")) == 1
    gw.now = lambda: NOW + timedelta(seconds=120)
    check(client, "three")
    assert len(sent(receiver, "FOUND")) == 1


def test_cooldown_and_replay_send_nothing(env, receiver):
    client, _, gw = stock_only(env)
    make(client)
    check(client, "one")
    gw.now = lambda: NOW + timedelta(seconds=59)
    assert check(client, "two").json()["reused"] is True
    assert "reused" not in check(client, "one").json()
    assert len(sent(receiver, "FOUND")) == 1


def test_failed_delivery_is_retried_by_the_next_check(env, receiver):
    client, db, gw = stock_only(env)
    make(client)
    receiver.status = 500
    check(client, "one")
    assert len(receiver.calls) == 3
    receiver.status = 200
    gw.now = lambda: NOW + timedelta(seconds=60)
    check(client, "two")
    assert len(sent(receiver, "FOUND")) == 4
    assert db.webhook_deliveries.count_documents({"ok": False}) == 1
    assert db.webhook_deliveries.count_documents({"ok": True}) == 1
    gw.now = lambda: NOW + timedelta(seconds=120)
    check(client, "three")
    assert len(sent(receiver, "FOUND")) == 4


def test_malformed_stored_alert_does_not_fail_the_check(env, receiver):
    client, db, _ = stock_only(env)
    make(client)
    db.recall_alerts.insert_one({"_id": "recall-old", "kitchen_id": "hotel", "product_id": "999",
                                 "where": ["in stock: 2 KG"], "detected_at": "2020-01-01T00:00:00"})
    response = check(client)
    assert response.status_code == 200, response.text
    by_id = {d["data"]["recall_event_id"]: d["data"] for d in sent(receiver, "FOUND")}
    assert len(by_id) == 2
    assert by_id["recall-old"]["notice_url"] is None
    [good] = [k for k in by_id if k != "recall-old"]
    assert by_id[good]["notice_url"]


def test_blocked_proposal_alert_names_its_case(env, receiver):
    client, _, _, proposal = env
    make(client)
    check(client)
    [delivery] = sent(receiver)
    assert delivery["event"] == "recall.alert"
    assert delivery["data"] == {"case": "PROPOSAL_BLOCKED", "proposal_id": proposal["proposal_id"],
                                "product_ids": [COFFEE]}
