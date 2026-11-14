"""The delivery beat (#1198): one fixed demo order, and the prepared note photo for it gives
one short and one missing line, 3 cases, EUR 91.08 to claim. No network: the gateway, the
real worker app and agent.receiving, with the hand-written reply for demo-note.png."""
import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.receiving import FIXTURES, RecordedModel
from agent.receiving_service import DeliveryNoteReader
from agent.service import WorkerError, create_app as worker_app
from demo import delivery_order
from gateway import delivery_note
from gateway.app import create_app
from gateway.service import Gateway
from gateway.tests.test_gateway_app import HUMAN, K, NOW

mongomock = pytest.importorskip("mongomock")

# Pack sizes as the Valio catalog gives them (baseUnit and units of the raw row).
CATALOG = {"463982": ("KI", {"KI": 1.0, "PAL": 48.0}), "460838": ("KI", {"KI": 1.0}),
           "463335": ("ST", {"ST": 1.0, "KI": 5.0, "CS": 20.0})}


class Recorded(RecordedModel):
    async def close(self):
        pass


@pytest.fixture
def db():
    return mongomock.MongoClient(tz_aware=True)["test"]


def test_the_demo_order_is_placed_once_with_the_catalog_prices(db):
    first = delivery_order.place(db)
    again = delivery_order.place(db)
    assert first["order_id"] == again["order_id"] and db.orders.count_documents({}) == 1
    order = db.orders.find_one({})
    assert (order["kitchen_id"], order["outcome"], order["status"], order["reference"]) == (
        "demo-kitchen", "CONFIRMED", "SENT", "DEMO-1198")
    assert [(ln["product_id"], ln["quantity"], ln["unit"], ln["unit_price"], ln["total"]) for ln in order["lines"]] == [
        ("463982", "3", "KI", "31.01", "93.03"), ("460838", "1", "KI", "29.06", "29.06"),
        ("463335", "40", "ST", "1.40", "56.00")]
    assert str(order["expected_total"]) == "178.09"
    assert order["blocks"] == [{"supplier_id": "sup-valio", "name": "Valio Aimo",
                                "product_ids": ["463982", "460838", "463335"]}]
    assert order.get("proposal_id") is None      # no delivery day: never counted as stock on order
    assert len([e for e in db.audit_log.find({}) if e["event"]["kind"] == "demo_delivery_order_placed"]) == 1


def test_find_reports_the_order_without_writing(db):
    assert delivery_order.find(db) is None and db.orders.count_documents({}) == 0
    placed = delivery_order.place(db)
    assert delivery_order.find(db)["order_id"] == placed["order_id"]


def test_the_prepared_photo_gives_three_cases_short_and_the_eur_to_claim(db, monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    monkeypatch.setenv("BUYER_WORKER_URL", "http://worker.test")
    order_id = delivery_order.place(db)["order_id"]
    for pid, (base, units) in CATALOG.items():
        db.products.insert_one({"_id": pid, "names": {"en": pid}, "raw": {
            "id": pid, "baseUnit": base, "units": [{"unitId": u, "sizeInBaseUnits": s} for u, s in units.items()]}})
    reply = json.loads((FIXTURES / "demo-note.reply.json").read_text(encoding="utf-8"))
    model = Recorded(reply)
    reader = DeliveryNoteReader(db, WorkerError, model_factory=lambda: model)
    real = httpx.AsyncClient
    transport = httpx.ASGITransport(app=worker_app(delivery_note=reader))
    monkeypatch.setattr(delivery_note.httpx, "AsyncClient",
                        lambda *args, **kwargs: real(*args, **{**kwargs, "transport": transport}))
    client = TestClient(create_app(Gateway(db, None, now=lambda: NOW)))
    photo = base64.b64encode((FIXTURES / "demo-note.png").read_bytes()).decode("ascii")
    answer = client.post(f"{K}/orders/{order_id}/delivery-note/photo", headers=HUMAN, json={"image_base64": photo})
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert data["note"] == {"order_ref": "DEMO-1198", "delivery_date": "2026-11-16"}
    assert [(ln["product_id"], ln["status"], ln["missing_order_qty"], ln["claim_eur"]) for ln in data["lines"]] == [
        ("463982", "SHORT", "2", "62.02"), ("460838", "MISSING", "1", "29.06"), ("463335", "RECEIVED", "0", "0.00")]
    assert data["not_ordered"] == [] and data["complete"] is False
    assert data["claim"] == {"currency": "EUR", "total_eur": "91.08", "lines": 2, "quantity": "3", "unit": "KI",
                             "not_valued": 0, "supplier_name": "Valio Aimo"}
    assert len(model.requests) == 1 and db.kitchen_stock.count_documents({}) == 0
