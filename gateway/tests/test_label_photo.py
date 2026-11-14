"""The label photo route (#1175): shown to a person, stored nowhere."""
import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.service import Gateway, GatewayError
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW, env  # noqa: F401 (fixture)
from gateway.valio_client import ValioClient

ROOT = Path(__file__).resolve().parents[2]
REPLY = json.loads((ROOT / "agent" / "fixtures" / "label" / "demo.reply.json").read_text(encoding="utf-8"))
PHOTO = base64.b64encode((ROOT / "demo" / "label-photo.png").read_bytes()).decode()
URL = K + "/orders/ord-label-1/label/photo"


def app_for(env, worker):
    _, fake, db = env
    db.orders.insert_one({"_id": "ord-label-1", "kitchen_id": "demo-kitchen",
                          "lines": [{"product_id": "own-cinnamon-bun", "quantity": "40", "unit": "ST"}]})
    db.orders.insert_one({"_id": "ord-other", "kitchen_id": "other-kitchen", "lines": []})
    db.products.insert_one({"_id": "own-cinnamon-bun", "source": "own", "kitchen_id": "demo-kitchen",
                            "names": {"en": "Cinnamon bun", "fi": "Cinnamon bun", "sv": "Cinnamon bun"},
                            "units": [{"unit": "ST", "size_in_base_units": 1.0, "gtin": None}],
                            "allergens": {"contains": [], "may_contain": [], "undeclared": []},
                            "allergen_data_known": False})
    db.products.insert_one({"_id": "own-elsewhere", "source": "own", "kitchen_id": "other-kitchen",
                            "names": {"en": "Secret"}, "units": [], "allergens": {}, "allergen_data_known": False})
    db.kitchen_settings.update_one({"_id": "demo-kitchen"}, {"$set": {"excluded_allergens": ["peanuts"]}}, upsert=True)
    gw = Gateway(db, ValioClient("test-key", transport=fake.transport, ttl=0, now=lambda: NOW), now=lambda: NOW)
    return TestClient(create_app(gw, label_photo_worker=worker)), db


def recorded(calls):
    async def worker(kitchen_id, encoded):
        calls.append(kitchen_id)
        return REPLY
    return worker


def test_label_warns_about_the_kitchens_excluded_allergen_and_stores_nothing(env):
    calls = []
    client, db = app_for(env, recorded(calls))
    before = db.products.find_one({"_id": "own-cinnamon-bun"})
    r = client.post(URL, headers=HUMAN, json={"image_base64": PHOTO, "product_id": "own-cinnamon-bun"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["outcome"] == "EXCLUDED_ALLERGEN" and data["in_order"] is True and len(calls) == 1
    assert data["excluded_hits"] == [{"code": "AP", "level": "MAY_CONTAIN"}]
    assert "peanuts" in data["message"] and data["catalog_allergen_data"] == "UNKNOWN"
    assert db.products.find_one({"_id": "own-cinnamon-bun"}) == before           # unknown stays unknown
    events = [e["event"] for e in db.audit_log.find({"event.kind": "label_photo_read"})]
    assert len(events) == 1 and events[0]["outcome"] == "EXCLUDED_ALLERGEN"
    assert events[0]["counts"] == {"excluded_hits": 1, "differences": 0, "please_check": 0}
    text = json.dumps(events, default=str)
    assert "VEHNÄJAUHO" not in text and "Korvapuusti" not in text and PHOTO[:40] not in text


def test_order_product_scope_and_a_bad_reply(env):
    async def bad(kitchen_id, encoded):
        return {"contains": "nope"}
    client, db = app_for(env, bad)
    body = {"image_base64": PHOTO, "product_id": "own-cinnamon-bun"}
    assert client.post(K + "/orders/ord-other/label/photo", headers=HUMAN, json=body).json()["error"]["code"] == "ORDER_NOT_FOUND"
    assert client.post(URL, headers=HUMAN, json={**body, "product_id": "own-elsewhere"}).json()["error"]["code"] == "PRODUCT_NOT_FOUND"
    assert client.post(URL, headers=HUMAN, json={"image_base64": PHOTO}).json()["error"]["code"] == "PRODUCT_NOT_FOUND"
    assert client.post(URL, headers=AGENT, json=body).status_code == 403
    r = client.post(URL, headers=HUMAN, json=body)
    assert r.status_code == 502 and r.json()["error"]["code"] == "VISION_REPLY_INVALID"
    assert db.audit_log.count_documents({"event.kind": "label_photo_failed"}) == 1


def test_a_worker_error_is_passed_on(env):
    async def down(kitchen_id, encoded):
        raise GatewayError(503, "VISION_UNAVAILABLE", "down")
    client, _ = app_for(env, down)
    r = client.post(URL, headers=HUMAN, json={"image_base64": PHOTO, "product_id": "own-cinnamon-bun"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "VISION_UNAVAILABLE"
