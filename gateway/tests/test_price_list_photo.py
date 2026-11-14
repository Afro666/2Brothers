"""The price-list photo route (#1174): drafts only, never a write; a person saves each row."""
import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.service import Gateway, GatewayError
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW, env  # noqa: F401 (fixture)
from gateway.valio_client import ValioClient

ROOT = Path(__file__).resolve().parents[2]
REPLY = json.loads((ROOT / "agent" / "fixtures" / "price_list" / "demo.reply.json").read_text(encoding="utf-8"))
PHOTO = base64.b64encode((ROOT / "demo" / "price-list-photo.png").read_bytes()).decode()
URL = K + "/suppliers/sup-bakery/price-list/photo"


def app_for(env, worker):
    client, fake, db = env
    client.post(K + "/suppliers", headers=HUMAN, json={"supplier_id": "sup-bakery", "name": "Corner Bakery (demo)",
                                                       "adapter": "manual", "terms": {}})
    client.post(K + "/suppliers", headers=HUMAN, json={"supplier_id": "sup-api", "name": "API supplier",
                                                       "adapter": "valio_api", "terms": {}})
    r = client.post(K + "/products", headers=HUMAN, json={
        "product_id": "own-rye-loaf", "name": "Rye sourdough loaf 800 g", "supplier_id": "sup-bakery", "unit": "ST",
        "base_unit": "KG", "pack_size_in_base_units": "0.8", "unit_price_eur": "4.20", "allergen_data": "UNKNOWN"})
    assert r.status_code in (200, 201), r.text
    gw = Gateway(db, ValioClient("test-key", transport=fake.transport, ttl=0, now=lambda: NOW), now=lambda: NOW)
    return TestClient(create_app(gw, price_list_worker=worker)), db


def recorded(calls):
    async def worker(kitchen_id, encoded):
        calls.append((kitchen_id, encoded))
        return REPLY
    return worker


def test_photo_gives_drafts_writes_nothing_and_audits_counts_only(env):
    calls = []
    client, db = app_for(env, recorded(calls))
    before = list(db.products.find({"source": "own"}))
    r = client.post(URL, headers=HUMAN, json={"image_base64": PHOTO})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["supplier_id"] == "sup-bakery" and data["currency"] == "EUR" and data["vat"] == "INCLUDED"
    assert len(data["rows"]) == 8 and len(calls) == 1
    rye = next(row for row in data["rows"] if row["name"] == "Rye sourdough loaf 800 g")
    assert rye["match"]["kind"] == "PRICE_CHANGED" and rye["match"]["unit_price_eur"] == "4.20"
    assert rye["draft"]["unit_price_eur"] == "4.40"
    assert list(db.products.find({"source": "own"})) == before            # the stored price is still 4.20
    events = [e["event"] for e in db.audit_log.find({"event.kind": "price_list_photo_read"})]
    assert len(events) == 1 and events[0]["statuses"] == {"READ": 7, "PLEASE_CHECK": 1}
    text = json.dumps(events, default=str)
    assert "Rye" not in text and "4.40" not in text and PHOTO[:40] not in text


def test_a_checked_draft_saves_with_the_existing_product_route_and_keeps_its_source(env):
    client, db = app_for(env, recorded([]))
    data = client.post(URL, headers=HUMAN, json={"image_base64": PHOTO}).json()
    draft = next(row for row in data["rows"] if row["name"] == "Baguette")["draft"]
    saved = client.post(K + "/products", headers=HUMAN, json=draft)
    assert saved.status_code in (200, 201), saved.text
    assert saved.json()["price_source"] == "price_list_photo" and saved.json()["allergen_data"] == "UNKNOWN"
    old = client.get(K + "/products/own-rye-loaf", headers=HUMAN).json()
    assert old["price_source"] == "entered"                                # rows from before #1174 read as entered


def test_supplier_rules_scope_and_a_bad_reply(env):
    async def bad(kitchen_id, encoded):
        return {"rows": "not a list"}
    client, db = app_for(env, bad)
    body = {"image_base64": PHOTO}
    assert client.post(K + "/suppliers/nope/price-list/photo", headers=HUMAN, json=body).json()["error"]["code"] == "SUPPLIER_NOT_FOUND"
    assert client.post(K + "/suppliers/sup-api/price-list/photo", headers=HUMAN, json=body).json()["error"]["code"] == "SUPPLIER_HAS_API"
    assert client.post(URL, headers=AGENT, json=body).status_code == 403
    r = client.post(URL, headers=HUMAN, json=body)
    assert r.status_code == 502 and r.json()["error"]["code"] == "VISION_REPLY_INVALID"
    assert db.audit_log.count_documents({"event.kind": "price_list_photo_failed"}) == 1
    assert client.post(URL, headers=HUMAN, json={"image_base64": base64.b64encode(b"not an image").decode()}).status_code == 422


def test_a_worker_error_is_passed_on(env):
    async def down(kitchen_id, encoded):
        raise GatewayError(504, "VISION_TIMEOUT", "slow")
    client, _ = app_for(env, down)
    r = client.post(URL, headers=HUMAN, json={"image_base64": PHOTO})
    assert r.status_code == 504 and r.json()["error"]["code"] == "VISION_TIMEOUT"
