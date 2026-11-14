"""POST /v1/kitchens/{k}/stock/photo (#373): scope, size, the worker handoff, the audit.
No network: the worker is a fake, or the real worker app with Nemotron's recorded reply."""
import base64
from datetime import datetime, timezone
import json

import httpx
import mongomock
import pytest
from fastapi.testclient import TestClient

from agent.service import WorkerError, create_app as worker_app
from agent.shelf import FIXTURES, RecordedModel
from agent.shelf_service import ShelfReader
from gateway import stock_photo, users
from gateway.app import create_app
from gateway.service import Gateway, GatewayError
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW
from store.history import record_stock_count

PHOTO = (FIXTURES / "shelf.png").read_bytes()
REPLY = json.loads((FIXTURES / "shelf.reply.json").read_text(encoding="utf-8"))
PRODUCTS = json.loads((FIXTURES / "kitchen.json").read_text(encoding="utf-8"))["products"]
URL = K + "/stock/photo"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


BODY = {"image_base64": b64(PHOTO)}
ROWS = [
    {"row": "COUNTED", "product_id": "463335", "product_name": "Valio Eila 3% 1 L", "label": "Valio Eila 3% 1L",
     "confidence": "high", "packs": 6, "pack_size": "1", "count": "6", "unit": "L"},
    {"row": "PLEASE_COUNT", "product_id": "463038", "product_name": "Valio Eila 10 L novobox",
     "label": "Valio Eila 10 L novobox", "confidence": "low", "packs": None, "pack_size": "10", "count": None, "unit": "L"},
    {"row": "UNMATCHED", "product_id": None, "product_name": None, "label": "Arla L m", "confidence": "low",
     "packs": None, "pack_size": None, "count": None, "unit": None},
]


class Recorded(RecordedModel):
    async def close(self):
        pass


class FakeWorker:
    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer if answer is not None else {"rows": ROWS}, error, []

    async def __call__(self, kitchen_id, image_base64):
        self.calls.append((kitchen_id, image_base64))
        if self.error:
            raise self.error
        return self.answer


def make(monkeypatch, worker=None):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    db = mongomock.MongoClient(tz_aware=True)["test"]
    gw = Gateway(db, None, now=lambda: NOW)
    return TestClient(create_app(gw, shelf_worker=worker)), db


def events(db, kind):
    return [doc["event"] for doc in db.audit_log.find({}) if doc["event"]["kind"] == kind]


def error_of(answer):
    return answer.status_code, answer.json()["error"]["code"]


def test_a_person_gets_the_rows_and_nothing_is_stored_but_one_audit_entry(monkeypatch):
    worker = FakeWorker()
    client, db = make(monkeypatch, worker)
    answer = client.post(URL, headers=HUMAN, json=BODY)
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert data["model"] == "nemotron-3.5-super-vl" and data["saved"] is False
    assert isinstance(data["duration_ms"], int) and data["rows"] == ROWS
    assert worker.calls == [("demo-kitchen", BODY["image_base64"])]             # one call, never retried
    assert db.kitchen_stock.count_documents({}) == 0 and db.stock_count_keys.count_documents({}) == 0
    written = {name: db[name].count_documents({}) for name in db.list_collection_names()}
    assert {name for name, n in written.items() if n} == {"audit_log"} and written["audit_log"] == 1
    [event] = events(db, "stock_photo_read")
    assert (event["actor"], event["rows"], event["counted"], event["model"]) == ("aron", 3, 1, "nemotron-3.5-super-vl")
    stored = json.dumps(list(db.audit_log.find({}, {"_id": 0})), default=str)
    assert BODY["image_base64"][:200] not in stored and "Arla L m" not in stored    # no image, no model text


def test_who_may_read_a_photo(monkeypatch):
    worker = FakeWorker()
    client, db = make(monkeypatch, worker)
    assert error_of(client.post(URL, json=BODY)) == (401, "UNAUTHENTICATED")
    assert error_of(client.post(URL, headers=AGENT, json=BODY)) == (403, "SCOPE_REQUIRED")     # never the Buyer
    made = lambda scopes: {"Authorization": "Bearer " + client.post(
        K + "/tokens", headers=HUMAN, json={"name": "t-" + scopes[0], "scopes": scopes}).json()["token"]}
    assert error_of(client.post(URL, headers=made(["kitchen:read"]), json=BODY)) == (403, "SCOPE_REQUIRED")
    assert error_of(client.post("/v1/kitchens/other-kitchen/stock/photo", headers=made(["kitchen:write"]),
                                json=BODY)) == (403, "KITCHEN_SCOPE")
    assert worker.calls == []
    assert client.post(URL, headers=made(["kitchen:write"]), json=BODY).status_code == 200
    users.create_user(db, "view@example.com", "viewer pass 12", name="V", role="viewer", kitchen_id="demo-kitchen")
    client.post("/v1/auth/login", json={"email": "view@example.com", "password": "viewer pass 12"})
    assert error_of(client.post(URL, json=BODY)) == (403, "ROLE_REQUIRED")
    assert len(worker.calls) == 1


def test_body_checks_come_before_the_worker(monkeypatch):
    worker = FakeWorker()
    client, db = make(monkeypatch, worker)
    post = lambda **kwargs: error_of(client.post(URL, headers=HUMAN, **kwargs))
    assert post(content=b"not json") == (422, "INVALID_JSON")
    assert post(json=["a list"]) == (422, "INVALID_JSON")
    assert post(json={}) == (422, "INVALID_REQUEST")
    assert post(json={"image_base64": "not base64 !"}) == (422, "INVALID_REQUEST")
    assert post(json={"image_base64": b64(b"GIF89a" + b"0" * 100)}) == (422, "NOT_AN_IMAGE")
    assert post(json={"image_base64": b64(b"%PDF-1.7 a delivery note")}) == (422, "NOT_AN_IMAGE")
    assert post(json={"image_base64": b64(b"\xff\xd8\xff" + b"0" * stock_photo.MAX_IMAGE_BYTES)}) == (413, "IMAGE_TOO_LARGE")
    assert post(content=b'{"image_base64": "' + b"A" * stock_photo.MAX_BODY_BYTES + b'"}') == (413, "IMAGE_TOO_LARGE")
    assert worker.calls == [] and db.audit_log.count_documents({}) == 0


@pytest.mark.parametrize("code,status", [("VISION_NOT_CONFIGURED", 503), ("VISION_UNAVAILABLE", 503),
                                         ("VISION_REPLY_INVALID", 502), ("VISION_TIMEOUT", 504)])
def test_a_failed_read_is_a_clear_code_and_an_audit_entry(monkeypatch, code, status):
    worker = FakeWorker(error=stock_photo._error(code))
    client, db = make(monkeypatch, worker)
    answer = client.post(URL, headers=HUMAN, json=BODY)
    assert error_of(answer) == (status, code) and "count by hand" in answer.json()["error"]["message"]
    assert len(worker.calls) == 1                                               # not retried
    [event] = events(db, "stock_photo_failed")
    assert event["code"] == code and event["actor"] == "aron"
    assert db.kitchen_stock.count_documents({}) == 0


def test_a_row_that_is_not_counted_never_leaves_with_a_number(monkeypatch):
    wrong = [{**ROWS[1], "packs": 2, "count": "20"}, {**ROWS[2], "packs": 1, "count": "1", "product_id": "464179",
                                                      "unit": "L", "pack_size": "10"}]
    client, _ = make(monkeypatch, FakeWorker({"rows": wrong}))
    rows = client.post(URL, headers=HUMAN, json=BODY).json()["rows"]
    assert [(r["row"], r["packs"], r["count"]) for r in rows] == [("PLEASE_COUNT", None, None), ("UNMATCHED", None, None)]
    assert rows[1]["product_id"] is None and rows[1]["unit"] is None
    for bad in ({}, {"rows": "none"}, {"rows": [{"row": "GUESSED"}]}, {"rows": [{**ROWS[0], "count": None}]},
                {"rows": [{**ROWS[0], "packs": "6"}]}):
        client, _ = make(monkeypatch, FakeWorker(bad))
        assert error_of(client.post(URL, headers=HUMAN, json=BODY)) == (502, "VISION_REPLY_INVALID")


# ---- the handoff to the worker (read_shelf_photo), like test_buyer_worker.py ------------

@pytest.fixture
def worker_http(monkeypatch):
    monkeypatch.setenv("BUYER_WORKER_URL", "http://worker.test")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    real = httpx.AsyncClient

    def use(transport):
        monkeypatch.setattr(stock_photo.httpx, "AsyncClient",
                            lambda *args, **kwargs: real(*args, **{**kwargs, "transport": transport}))
    return use


def handoff_error(monkeypatch):
    client, _ = make(monkeypatch)
    return error_of(client.post(URL, headers=HUMAN, json=BODY))


def test_worker_not_configured(monkeypatch):
    monkeypatch.delenv("BUYER_WORKER_URL", raising=False)
    assert handoff_error(monkeypatch) == (503, "VISION_NOT_CONFIGURED")


def test_worker_errors_map_to_contract_codes(monkeypatch, worker_http):
    seen = []

    def answer(status, code):
        def handler(request):
            seen.append(request)
            return httpx.Response(status, json={"error": {"code": code}})
        return httpx.MockTransport(handler)
    for status, code, expected in ((503, "VISION_NOT_CONFIGURED", (503, "VISION_NOT_CONFIGURED")),
                                   (504, "VISION_TIMEOUT", (504, "VISION_TIMEOUT")),
                                   (502, "VISION_REPLY_INVALID", (502, "VISION_REPLY_INVALID")),
                                   (401, "UNAUTHENTICATED", (503, "VISION_UNAVAILABLE")),
                                   (500, "SOMETHING_ODD", (503, "VISION_UNAVAILABLE"))):
        worker_http(answer(status, code))
        assert handoff_error(monkeypatch) == expected
    assert len(seen) == 5 and seen[0].url.path == "/shelf"                      # one request per call
    assert seen[0].headers["authorization"] == "Bearer agent-test-token"

    def down(request):
        raise httpx.ConnectError("down", request=request)

    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)
    worker_http(httpx.MockTransport(down))
    assert handoff_error(monkeypatch) == (503, "VISION_UNAVAILABLE")
    worker_http(httpx.MockTransport(slow))
    assert handoff_error(monkeypatch) == (504, "VISION_TIMEOUT")
    worker_http(httpx.MockTransport(lambda request: httpx.Response(200, text="<html>")))
    assert handoff_error(monkeypatch) == (503, "VISION_UNAVAILABLE")


def test_end_to_end_gateway_to_worker_with_the_recorded_nemotron_reply(monkeypatch, worker_http):
    """Person -> gateway route -> worker POST /shelf -> agent.shelf.read_shelf on the
    recorded reply. The stock the kitchen had before is the stock it has after."""
    client, db = make(monkeypatch)
    for p in PRODUCTS:
        db.products.insert_one({"_id": p["product_id"], "names": {"en": p["name"]},
                                "net_content": {"value": float(p["pack_size"]), "unit": "L"},
                                "net_content_source": "synkka"})
    record_stock_count(db, "demo-kitchen", datetime(2026, 11, 13, 20, 0, tzinfo=timezone.utc),
                       [{"product_id": p["product_id"], "on_hand": "3", "unit": "L"} for p in PRODUCTS])
    model = Recorded(REPLY)
    reader = ShelfReader(db, WorkerError, model_factory=lambda: model)
    worker_http(httpx.ASGITransport(app=worker_app(shelf=reader)))
    answer = client.post(URL, headers=HUMAN, json=BODY)
    assert answer.status_code == 200, answer.text
    rows = answer.json()["rows"]
    assert {r["product_id"]: r["count"] for r in rows if r["row"] == "COUNTED"} == {
        "462775": "7", "463335": "6", "462921": "4", "463038": "20"}
    assert [(r["row"], r["count"], r["confidence"]) for r in rows if r["row"] != "COUNTED"] == [("UNMATCHED", None, "low")]
    assert len(model.requests) == 1
    stock = {i["product_id"]: i["on_hand"] for i in client.get(K + "/stock", headers=HUMAN).json()["items"]}
    assert stock == {p["product_id"]: "3" for p in PRODUCTS}                    # nothing was counted for them
    assert db.kitchen_stock.count_documents({}) == len(PRODUCTS)
    assert [e["counted"] for e in events(db, "stock_photo_read")] == [4]


def test_gateway_error_type_is_used():
    assert isinstance(stock_photo._error("VISION_TIMEOUT"), GatewayError)
