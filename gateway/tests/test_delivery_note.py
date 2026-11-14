"""POST /v1/kitchens/{k}/orders/{order_id}/delivery-note/photo (#362): scope, the order,
the worker handoff, the audit. No network: a fake worker, or the real worker app with
Nemotron's recorded reply for the synthetic short delivery."""
import base64
import json

import httpx
import mongomock
import pytest
from fastapi.testclient import TestClient

from agent.receiving import FIXTURES, RecordedModel
from agent.receiving_service import DeliveryNoteReader
from agent.service import WorkerError, create_app as worker_app
from gateway import delivery_note
from gateway.app import create_app
from gateway.service import Gateway
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW

PHOTO = (FIXTURES / "short.png").read_bytes()
REPLY = json.loads((FIXTURES / "short.reply.json").read_text(encoding="utf-8"))
BODY = {"image_base64": base64.b64encode(PHOTO).decode("ascii")}
ORDER = "order-1"
URL = f"{K}/orders/{ORDER}/delivery-note/photo"
SHORT = {"note": {"order_ref": "ORD-DEMO-0001", "delivery_date": "2026-11-16"}, "complete": False,
         "lines": [{"product_id": "462775", "status": "SHORT", "ordered": "51", "received": "36",
                    "missing": "15", "base_unit": "ST", "lots": []}],
         "not_ordered": [{"product_id": "462921", "status": "SUBSTITUTE", "replaces": "462775", "quantity": "2",
                          "unit": "KI", "received": "10", "base_unit": "ST", "lot": "L1",
                          "best_before": "unknown", "needs_approval": True}]}


class Recorded(RecordedModel):
    async def close(self):
        pass


class FakeWorker:
    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer if answer is not None else SHORT, error, []

    async def __call__(self, kitchen_id, order_id, image_base64):
        self.calls.append((kitchen_id, order_id))
        if self.error:
            raise self.error
        return self.answer


def make(monkeypatch, worker=None):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    db = mongomock.MongoClient(tz_aware=True)["test"]
    db.offers.insert_one({"_id": "offer-1", "kitchen_id": "demo-kitchen",
                          "request": {"requested_date": "2026-11-16"}})
    db.orders.insert_one({"_id": ORDER, "kitchen_id": "demo-kitchen",
                          "offer_id": "offer-1", "supplier_id": "sup-valio",
                          "outcome": "CONFIRMED", "status": "SENT", "created_at": NOW,
                          "lines": [{"product_id": "462775", "quantity": "51", "unit": "ST"}]})
    db.orders.insert_one({"_id": "theirs", "kitchen_id": "other-kitchen", "lines": []})
    gw = Gateway(db, None, now=lambda: NOW)
    return TestClient(create_app(gw, delivery_note_worker=worker)), db


def events(db, kind):
    return [doc["event"] for doc in db.audit_log.find({}) if doc["event"]["kind"] == kind]


def error_of(answer):
    return answer.status_code, answer.json()["error"]["code"]


def test_a_person_gets_the_checked_lines_and_the_observation_is_saved(monkeypatch):
    worker = FakeWorker()
    client, db = make(monkeypatch, worker)
    answer = client.post(URL, headers=HUMAN, json=BODY)
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert (data["model"], data["saved"], data["order_id"], data["complete"]) == (
        "nemotron-3.5-super-vl", True, ORDER, False)
    assert data["lines"][0]["missing"] == "15" and data["not_ordered"][0]["needs_approval"] is True
    assert worker.calls == [("demo-kitchen", ORDER)]
    written = {n for n in db.list_collection_names() if db[n].count_documents({})}
    assert written == {"orders", "offers", "delivery_results", "delivery_result_current", "audit_log"}
    assert db.delivery_results.count_documents({}) == 1 and db.audit_log.count_documents({}) == 2
    [event] = events(db, "delivery_note_read")
    assert (event["actor"], event["order_id"], event["statuses"]) == ("aron", ORDER, {"SHORT": 1, "SUBSTITUTE": 1})
    [saved] = events(db, "delivery_result_saved")
    assert (saved["order_id"], saved["revision"], saved["statuses"]) == (ORDER, 1, {"SHORT": 1, "SUBSTITUTE": 1})
    stored = json.dumps([*db.audit_log.find({}, {"_id": 0}), *db.delivery_results.find({}, {"_id": 0})],
                        default=str)
    assert BODY["image_base64"][:200] not in stored and "ORD-DEMO" not in stored
    assert "L1" not in stored and "best_before" not in stored


def test_who_and_which_order(monkeypatch):
    worker = FakeWorker()
    client, _ = make(monkeypatch, worker)
    assert error_of(client.post(URL, json=BODY)) == (401, "UNAUTHENTICATED")
    assert error_of(client.post(URL, headers=AGENT, json=BODY)) == (403, "SCOPE_REQUIRED")    # never the Buyer
    assert error_of(client.post(f"{K}/orders/nope/delivery-note/photo", headers=HUMAN, json=BODY)) == (
        404, "ORDER_NOT_FOUND")
    assert error_of(client.post(f"{K}/orders/theirs/delivery-note/photo", headers=HUMAN, json=BODY)) == (
        404, "ORDER_NOT_FOUND")                                                  # another kitchen's order
    assert error_of(client.post(URL, headers=HUMAN, json={"image_base64": "bad !"})) == (422, "INVALID_REQUEST")
    assert worker.calls == []


def test_a_substitute_always_needs_a_yes_and_a_bad_answer_is_refused(monkeypatch):
    sneaky = {**SHORT, "complete": True, "not_ordered": [{**SHORT["not_ordered"][0], "needs_approval": False}]}
    client, _ = make(monkeypatch, FakeWorker(sneaky))
    data = client.post(URL, headers=HUMAN, json=BODY).json()
    assert data["not_ordered"][0]["needs_approval"] is True and data["complete"] is False
    for bad in ({}, {**SHORT, "lines": [{"status": "GUESSED"}]}, {**SHORT, "not_ordered": "none"}):
        client, _ = make(monkeypatch, FakeWorker(bad))
        assert error_of(client.post(URL, headers=HUMAN, json=BODY)) == (502, "VISION_REPLY_INVALID")


def test_a_failed_read_is_a_clear_code_and_an_audit_entry(monkeypatch):
    client, db = make(monkeypatch, FakeWorker(error=delivery_note._error("VISION_TIMEOUT")))
    answer = client.post(URL, headers=HUMAN, json=BODY)
    assert error_of(answer) == (504, "VISION_TIMEOUT") and "by hand" in answer.json()["error"]["message"]
    [event] = events(db, "delivery_note_failed")
    assert (event["code"], event["order_id"]) == ("VISION_TIMEOUT", ORDER)


@pytest.fixture
def worker_http(monkeypatch):
    monkeypatch.setenv("BUYER_WORKER_URL", "http://worker.test")
    real = httpx.AsyncClient

    def use(transport):
        monkeypatch.setattr(delivery_note.httpx, "AsyncClient",
                            lambda *args, **kwargs: real(*args, **{**kwargs, "transport": transport}))
    return use


def test_end_to_end_gateway_to_worker_with_the_recorded_nemotron_reply(monkeypatch, worker_http):
    """Person -> gateway route -> worker POST /delivery-note -> agent.receiving on the
    recorded reply for the synthetic short note: 15 bottles missing, a 10-pack substitute."""
    client, db = make(monkeypatch)
    for pid, case in (("462775", 12.0), ("462921", 5.0)):
        db.products.insert_one({"_id": pid, "names": {"en": f"milk {pid}"}, "raw": {
            "id": pid, "salesUnit": "ST", "baseUnit": "ST",
            "units": [{"unitId": "ST", "sizeInBaseUnits": 1.0}, {"unitId": "KI", "sizeInBaseUnits": case}]}})
    model = Recorded(REPLY)
    reader = DeliveryNoteReader(db, WorkerError, model_factory=lambda: model)
    worker_http(httpx.ASGITransport(app=worker_app(delivery_note=reader)))
    answer = client.post(URL, headers=HUMAN, json=BODY)
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert [(ln["product_id"], ln["status"], ln["missing"]) for ln in data["lines"]] == [("462775", "SHORT", "15")]
    assert [(ln["product_id"], ln["status"], ln["received"], ln["needs_approval"]) for ln in data["not_ordered"]] == [
        ("462921", "SUBSTITUTE", "10", True)]
    assert len(model.requests) == 1 and db.kitchen_stock.count_documents({}) == 0


# ---- The claim (#1198): the value of what did not come, from the order's own prices ----

DEMO_ORDER = [{"product_id": "463982", "quantity": "3", "unit": "KI", "unit_price": "31.01"},
              {"product_id": "460838", "quantity": "1", "unit": "KI", "unit_price": "29.06"},
              {"product_id": "463335", "quantity": "40", "unit": "ST", "unit_price": "1.40"}]
DEMO_LINES = [{"product_id": "463982", "status": "SHORT", "ordered": "3", "received": "1", "missing": "2",
               "base_unit": "KI", "lots": []},
              {"product_id": "460838", "status": "MISSING", "ordered": "1", "received": "0", "missing": "1",
               "base_unit": "KI", "lots": []},
              {"product_id": "463335", "status": "RECEIVED", "ordered": "40", "received": "40", "missing": "0",
               "base_unit": "ST", "lots": []}]


def test_each_short_line_has_its_value_at_the_orders_price_and_one_total(monkeypatch):
    client, db = make(monkeypatch, FakeWorker({**SHORT, "lines": DEMO_LINES, "not_ordered": []}))
    db.orders.update_one({"_id": ORDER}, {"$set": {"lines": DEMO_ORDER, "blocks": [
        {"supplier_id": "sup-valio", "name": "Valio Aimo", "product_ids": ["463982", "460838", "463335"]}]}})
    data = client.post(URL, headers=HUMAN, json=BODY).json()
    assert [(ln["order_quantity"], ln["order_unit"], ln["missing_order_qty"], ln["unit_price"], ln["claim_eur"])
            for ln in data["lines"]] == [("3", "KI", "2", "31.01", "62.02"), ("1", "KI", "1", "29.06", "29.06"),
                                         ("40", "ST", "0", "1.40", "0.00")]
    assert data["claim"] == {"currency": "EUR", "total_eur": "91.08", "lines": 2, "quantity": "3", "unit": "KI",
                             "not_valued": 0, "supplier_name": "Valio Aimo"}


def test_the_value_converts_base_units_to_the_order_unit_and_rounds_half_up(monkeypatch):
    # 7 of a 12-pack case ordered as 2 KI (24 ST) at EUR 10.00 a case: 7/12 case = EUR 5.8333 -> 5.83.
    lines = [{"product_id": "462775", "status": "SHORT", "ordered": "24", "received": "17", "missing": "7",
              "base_unit": "ST", "lots": []}]
    client, db = make(monkeypatch, FakeWorker({**SHORT, "lines": lines, "not_ordered": []}))
    db.orders.update_one({"_id": ORDER}, {"$set": {"lines": [
        {"product_id": "462775", "quantity": "2", "unit": "KI", "unit_price": "10.00"}]}})
    data = client.post(URL, headers=HUMAN, json=BODY).json()
    assert (data["lines"][0]["missing_order_qty"], data["lines"][0]["claim_eur"]) == ("0.583", "5.83")
    assert (data["claim"]["total_eur"], data["claim"]["quantity"], data["claim"]["unit"]) == ("5.83", "0.583", "KI")
    assert data["claim"]["supplier_name"] is None                                   # no supplier block stored


def test_unknown_or_unpriced_lines_are_never_given_a_value(monkeypatch):
    lines = [{"product_id": "463982", "status": "UNKNOWN", "ordered": "3", "received": None, "missing": None,
              "base_unit": "KI", "lots": []},
             {"product_id": "460838", "status": "MISSING", "ordered": "1", "received": "0", "missing": "1",
              "base_unit": "KI", "lots": []},
             {"product_id": "463335", "status": "SHORT", "ordered": "40", "received": "30", "missing": "10",
              "base_unit": "ST", "lots": []}]
    client, db = make(monkeypatch, FakeWorker({**SHORT, "lines": lines, "not_ordered": []}))
    db.orders.update_one({"_id": ORDER}, {"$set": {"lines": [
        {**DEMO_ORDER[0]}, {**DEMO_ORDER[1], "unit_price": None}, {**DEMO_ORDER[2]}]}})
    data = client.post(URL, headers=HUMAN, json=BODY).json()
    assert [ln["claim_eur"] for ln in data["lines"]] == [None, None, "14.00"]
    assert data["lines"][0]["missing_order_qty"] is None
    claim = data["claim"]
    assert (claim["total_eur"], claim["lines"], claim["not_valued"]) == ("14.00", 2, 2)
    assert (claim["quantity"], claim["unit"]) == (None, None)                       # KI and ST: no one unit


def test_a_line_that_does_not_match_the_stored_order_gets_no_price(monkeypatch):
    # The worker's lines follow the order's lines; one that names another product is never priced.
    lines = [{**DEMO_LINES[0], "product_id": "999999"}]
    client, db = make(monkeypatch, FakeWorker({**SHORT, "lines": lines, "not_ordered": []}))
    db.orders.update_one({"_id": ORDER}, {"$set": {"lines": DEMO_ORDER[:1]}})
    data = client.post(URL, headers=HUMAN, json=BODY).json()
    assert (data["lines"][0]["claim_eur"], data["lines"][0]["unit_price"]) == (None, None)
    assert (data["claim"]["total_eur"], data["claim"]["not_valued"]) == ("0.00", 1)


def test_a_complete_delivery_claims_nothing(monkeypatch):
    lines = [{**DEMO_LINES[2]}]
    client, db = make(monkeypatch, FakeWorker({**SHORT, "lines": lines, "not_ordered": []}))
    db.orders.update_one({"_id": ORDER}, {"$set": {"lines": DEMO_ORDER[2:]}})
    data = client.post(URL, headers=HUMAN, json=BODY).json()
    assert data["complete"] is True
    assert data["claim"] == {"currency": "EUR", "total_eur": "0.00", "lines": 0, "quantity": None, "unit": None,
                             "not_valued": 0, "supplier_name": None}
