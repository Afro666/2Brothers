"""Delivery results over HTTP (#1304): photo persistence and the one-tap received route."""

from datetime import datetime, timezone

from gateway import approval_tokens, tokens, users
from gateway.tests.test_delivery_note import BODY, FakeWorker, ORDER, SHORT, URL, make
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW, env  # noqa: F401
from store import delivery_results

PW = "correct horse 42"
RECEIVED = f"{K}/orders/{ORDER}/received"
BODY_RECEIVED = {"idempotency_key": "received-1", "delivery_date": "2026-11-13", "complete": True}
LATER = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)


def add_order(db, order_id=ORDER, kitchen_id="demo-kitchen", *, outcome="CONFIRMED",
              status="SENT", lines=None, blocks=None, supplier_id="sup-a"):
    offer_id = "offer-" + order_id
    db.offers.insert_one({"_id": offer_id, "kitchen_id": kitchen_id,
                          "request": {"requested_date": "2026-11-13"}})
    db.orders.insert_one({"_id": order_id, "kitchen_id": kitchen_id, "offer_id": offer_id,
                          "idempotency_key": "order-" + order_id,
                          "outcome": outcome, "status": status, "supplier_id": supplier_id,
                          "created_at": NOW,
                          "lines": lines or [{"product_id": "p-1", "quantity": "40", "unit": "ST"}],
                          "blocks": blocks or []})


def bearer(token):
    return {"Authorization": "Bearer " + token}


def sign_in(client, db, email, role):
    users.create_user(db, email, PW, name=email, role=role, kitchen_id="demo-kitchen")
    client.cookies.clear()
    answer = client.post("/v1/auth/login", json={"email": email, "password": PW})
    assert answer.status_code == 200, answer.text


def test_a_photo_check_saves_days_late_and_an_unknown_date_is_null(monkeypatch):
    client, db = make(monkeypatch, FakeWorker({**SHORT, "note": {
        "order_ref": "ORD-DEMO-0001", "delivery_date": "2026-11-17"}}))
    answer = client.post(URL, headers=HUMAN, json=BODY)
    assert answer.status_code == 200 and answer.json()["saved"] is True
    [result] = delivery_results.delivery_history(db, "demo-kitchen")
    assert (result["source"], result["delivery_date"], result["days_late"]) == ("photo", "2026-11-17", 1)
    assert result["lines"] == [{"supplier_id": "sup-valio", "product_id": "462775",
                                "status": "SHORT", "ordered": "51", "delivered": "36", "unit": "ST"}]

    client, db = make(monkeypatch, FakeWorker({**SHORT, "note": {
        "order_ref": "ORD-DEMO-0001", "delivery_date": "unknown"}}))
    assert client.post(URL, headers=HUMAN, json=BODY).json()["saved"] is True
    [result] = delivery_results.delivery_history(db, "demo-kitchen")
    assert (result["delivery_date"], result["days_late"]) == (None, None)


def test_a_second_photo_check_is_revision_two_and_history_returns_the_current_one(monkeypatch):
    client, db = make(monkeypatch, FakeWorker(SHORT))
    assert client.post(URL, headers=HUMAN, json=BODY).status_code == 200
    assert client.post(URL, headers=HUMAN, json=BODY).status_code == 200
    history = delivery_results.delivery_history(db, "demo-kitchen")
    assert [row["revision"] for row in history] == [2]
    assert db.delivery_results.count_documents({}) == 2


def test_a_photo_result_keeps_delivered_in_the_order_unit(monkeypatch):
    line = {**SHORT["lines"][0], "ordered": "24", "received": "17", "missing": "7"}
    client, db = make(monkeypatch, FakeWorker({**SHORT, "lines": [line], "not_ordered": []}))
    db.orders.update_one({"_id": ORDER}, {"$set": {"lines": [
        {"product_id": "462775", "quantity": "2", "unit": "KI"}]}})
    assert client.post(URL, headers=HUMAN, json=BODY).status_code == 200
    [result] = delivery_results.delivery_history(db, "demo-kitchen")
    assert result["lines"] == [{"supplier_id": "sup-valio", "product_id": "462775",
                                "status": "SHORT", "ordered": "2", "delivered": "1.417",
                                "unit": "KI"}]


def test_a_mixed_supplier_order_keeps_the_split_on_its_lines(monkeypatch):
    lines = [{"product_id": "p-1", "status": "RECEIVED", "ordered": "1", "received": "1",
              "missing": "0", "base_unit": "ST", "lots": []},
             {"product_id": "p-2", "status": "RECEIVED", "ordered": "2", "received": "2",
              "missing": "0", "base_unit": "KI", "lots": []}]
    client, db = make(monkeypatch, FakeWorker({**SHORT, "lines": lines, "not_ordered": []}))
    db.orders.update_one({"_id": ORDER}, {"$set": {
        "supplier_id": None,
        "lines": [{"product_id": "p-1", "quantity": "1", "unit": "ST"},
                  {"product_id": "p-2", "quantity": "2", "unit": "KI"}],
        "blocks": [{"supplier_id": "sup-a", "product_ids": ["p-1"]},
                   {"supplier_id": "sup-b", "product_ids": ["p-2"]}]}})
    assert client.post(URL, headers=HUMAN, json=BODY).status_code == 200
    [result] = delivery_results.delivery_history(db, "demo-kitchen")
    assert result["supplier_id"] is None
    assert [(line["supplier_id"], line["product_id"]) for line in result["lines"]] == [
        ("sup-a", "p-1"), ("sup-b", "p-2")]


def test_received_saves_a_human_observation_without_touching_the_order(env):
    client, _, db = env
    add_order(db, lines=[{"product_id": "p-1", "quantity": "40", "unit": "ST"},
                         {"product_id": "p-2", "quantity": None, "unit": "KI"},
                         {"product_id": "p-3", "quantity": "3", "unit": "unknown"}],
              blocks=[{"supplier_id": "sup-a", "product_ids": ["p-1", "p-2", "p-3"]}])
    before = db.orders.find_one({"_id": ORDER})
    answer = client.post(RECEIVED, headers=HUMAN, json=BODY_RECEIVED)
    assert answer.status_code == 200, answer.text
    result = answer.json()["result"]
    assert (answer.json()["saved"], result["source"], result["checked_by"], result["days_late"]) == (
        True, "manual_complete", "aron", 0)
    assert [(line["product_id"], line["status"], line["ordered"], line["delivered"], line["unit"])
            for line in result["lines"]] == [("p-1", "RECEIVED", "40", "40", "ST"),
                                             ("p-2", "UNKNOWN", None, None, None),
                                             ("p-3", "UNKNOWN", "3", None, None)]
    assert result["not_ordered"] == [] and db.orders.find_one({"_id": ORDER}) == before
    [event] = [doc["event"] for doc in db.audit_log.find({}) if doc["event"]["kind"] == "delivery_result_saved"]
    assert (event["order_id"], event["result_id"], event["revision"], event["statuses"]) == (
        ORDER, result["result_id"], 1, {"RECEIVED": 1, "UNKNOWN": 2})
    assert set(event) <= {"event_id", "kind", "actor", "order_id", "result_id", "revision", "statuses"}


def test_received_replay_returns_the_old_result_and_changed_body_is_a_conflict(env):
    client, _, db = env
    add_order(db)
    first = client.post(RECEIVED, headers=HUMAN, json=BODY_RECEIVED)
    assert first.status_code == 200, first.text
    delivery_results.save_observation(
        db, kitchen_id="demo-kitchen", order_id=ORDER, supplier_id="sup-a",
        requested_date="2026-11-13", ordered_at=NOW, delivery_date="2026-11-18",
        checked_by="aron", checked_at=LATER, source="photo", lines=[], not_ordered=[])
    replay = client.post(RECEIVED, headers=HUMAN, json=BODY_RECEIVED)
    assert replay.status_code == 200 and replay.json() == first.json()
    assert [row["revision"] for row in delivery_results.delivery_history(db, "demo-kitchen")] == [2]
    changed = {**BODY_RECEIVED, "delivery_date": "2026-11-12"}
    answer = client.post(RECEIVED, headers=HUMAN, json=changed)
    assert answer.status_code == 409 and answer.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_received_needs_a_human_chef_or_approver(env):
    client, _, db = env
    add_order(db)
    assert client.post(RECEIVED, json=BODY_RECEIVED).status_code == 401
    assert client.post(RECEIVED, headers=AGENT, json=BODY_RECEIVED).json()["error"]["code"] == "SCOPE_REQUIRED"
    sign_in(client, db, "view@example.com", "viewer")
    assert client.post(RECEIVED, json=BODY_RECEIVED).json()["error"]["code"] == "ROLE_REQUIRED"
    sign_in(client, db, "chef@example.com", "chef")
    assert client.post(RECEIVED, json={**BODY_RECEIVED, "idempotency_key": "chef"}).status_code == 200
    client.cookies.clear()
    kitchen = tokens.create(db, "demo-kitchen", "pos", ["kitchen:write"], "aron")["token"]
    answer = client.post(RECEIVED, headers=bearer(kitchen), json={**BODY_RECEIVED, "idempotency_key": "pos"})
    assert answer.status_code == 403 and answer.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"
    users.create_user(db, "approver@example.com", PW, name="A", role="approver", kitchen_id="demo-kitchen")
    personal = approval_tokens.create(db, "approver@example.com", "demo-kitchen", "A", now=NOW)["token"]
    answer = client.post(RECEIVED, headers=bearer(personal), json={**BODY_RECEIVED, "idempotency_key": "chat"})
    assert answer.status_code == 403 and answer.json()["error"]["code"] == "SCOPE_REQUIRED"


def test_received_rejects_bad_dates_fields_orders_and_statuses(env):
    client, _, db = env
    add_order(db)
    for body in ({**BODY_RECEIVED, "delivery_date": "2026-11-14"},
                 {**BODY_RECEIVED, "extra": True}, {**BODY_RECEIVED, "complete": False},
                 {**BODY_RECEIVED, "idempotency_key": ""}):
        answer = client.post(RECEIVED, headers=HUMAN, json=body)
        assert answer.status_code == 422 and answer.json()["error"]["code"] == "INVALID_REQUEST", answer.text
    add_order(db, "theirs", "other-kitchen")
    assert client.post(f"{K}/orders/theirs/received", headers=HUMAN, json=BODY_RECEIVED).status_code == 404
    assert client.post(f"{K}/orders/nope/received", headers=HUMAN, json=BODY_RECEIVED).status_code == 404
    for index, (outcome, status) in enumerate((("NOT_SENT", None), ("CONFIRMED", "REJECTED"),
                                               ("CONFIRMED", "CANCELLED"))):
        add_order(db, f"bad-{index}", outcome=outcome, status=status)
        answer = client.post(f"{K}/orders/bad-{index}/received", headers=HUMAN,
                             json={**BODY_RECEIVED, "idempotency_key": f"bad-{index}"})
        assert answer.status_code == 409 and answer.json()["error"]["code"] == "NOT_PENDING"
