"""The worker's POST /shelf (#373): the recorded Nemotron reply, no network."""
import asyncio
import base64
from datetime import datetime, timezone
import json

import mongomock
import pytest
from fastapi.testclient import TestClient

from agent.model import ModelError
from agent.service import WorkerError, create_app
from agent.shelf import FIXTURES, RecordedModel
from agent.shelf_service import MAX_IMAGE_BYTES, ShelfReader, contract_rows, kitchen_products
from store.history import record_stock_count
from store.repository import Repository

KITCHEN = "demo-kitchen"
PHOTO = (FIXTURES / "shelf.png").read_bytes()
REPLY = json.loads((FIXTURES / "shelf.reply.json").read_text(encoding="utf-8"))
PRODUCTS = json.loads((FIXTURES / "kitchen.json").read_text(encoding="utf-8"))["products"]
AT = datetime(2026, 11, 14, 2, 0, tzinfo=timezone.utc)
BEARER = {"Authorization": "Bearer agent-test-token"}


class Recorded(RecordedModel):
    closed = False

    async def close(self):
        self.closed = True


def reply_of(*items):
    return {"role": "assistant", "content": json.dumps({"items": [
        {"label": label, "count": count, "confidence": confidence} for label, count, confidence in items]})}


def kitchen_db():
    """The fixture kitchen as the store holds it: catalog rows and one stock count."""
    db = mongomock.MongoClient(tz_aware=True)["test"]
    for p in PRODUCTS:
        db.products.insert_one({"_id": p["product_id"], "names": {"en": p["name"]},
                                "net_content": {"value": float(p["pack_size"]), "unit": "L"},
                                "net_content_source": "synkka"})
    record_stock_count(db, KITCHEN, AT, [{"product_id": p["product_id"], "on_hand": "3", "unit": "L"}
                                         for p in PRODUCTS])
    return db


def reader_for(db, reply=REPLY, **kwargs):
    model = Recorded(reply)
    return ShelfReader(db, WorkerError, model_factory=lambda: model, **kwargs), model


def read(db, reply=REPLY, photo=PHOTO, **kwargs):
    reader, model = reader_for(db, reply, **kwargs)
    return asyncio.run(reader.read(KITCHEN, photo)), model


def refused(db, reply=REPLY, photo=PHOTO, **kwargs):
    with pytest.raises(WorkerError) as caught:
        read(db, reply, photo, **kwargs)
    return caught.value.status, caught.value.code


def test_recorded_shelf_becomes_counts_in_the_kitchens_unit():
    db = kitchen_db()
    answer, model = read(db)
    assert answer["model"] == "nemotron-3.5-super-vl"
    counted = {r["product_id"]: r for r in answer["rows"] if r["row"] == "COUNTED"}
    assert {pid: (r["packs"], r["pack_size"], r["count"], r["unit"]) for pid, r in counted.items()} == {
        "462775": (7, "1", "7", "L"), "463335": (6, "1", "6", "L"), "462921": (4, "1", "4", "L"),
        "463038": (2, "10", "20", "L")}                          # two 10 L boxes are 20 L
    assert counted["463335"]["product_name"] == "Valio Eila 3% 1 L" and counted["463335"]["label"] == "Valio Eila 3% 1L"
    assert model.closed and len(model.requests) == 1             # one model call, then closed


def test_low_confidence_row_has_no_number():
    answer, _ = read(kitchen_db())
    [hidden] = [r for r in answer["rows"] if r["confidence"] == "low"]
    assert hidden == {"row": "UNMATCHED", "product_id": None, "product_name": None, "label": "Arla L m",
                      "confidence": "low", "packs": None, "pack_size": None, "count": None, "unit": None}
    reply = reply_of(("Valio Eila 3% 1 L", "6", "low"), ("Valio Eila organic 1 L", "unknown", "high"))
    rows = read(kitchen_db(), reply)[0]["rows"]
    assert [(r["row"], r["packs"], r["count"]) for r in rows] == [("PLEASE_COUNT", None, None)] * 2
    assert [r["product_id"] for r in rows] == ["463335", "462921"] and rows[0]["unit"] == "L"


def test_one_unsure_row_makes_the_whole_product_unknown():
    reply = reply_of(("Valio Eila 3% 1 L", "6", "high"), ("Valio Eila 3% 1 L", "2", "low"),
                     ("Valio Eila organic 1 L", "4", "high"))
    rows = read(kitchen_db(), reply)[0]["rows"]
    assert [(r["row"], r["count"]) for r in rows] == [("PLEASE_COUNT", None), ("PLEASE_COUNT", None), ("COUNTED", "4")]


def test_unknown_pack_size_is_please_count_never_a_guess():
    db = kitchen_db()
    db.products.update_one({"_id": "463335"}, {"$set": {"net_content": None}})                 # no net content
    db.products.update_one({"_id": "462921"}, {"$set": {"net_content": {"value": 1.0, "unit": "KG"}}})   # other unit
    db.products.update_one({"_id": "462775"}, {"$set": {"net_content_source": "base_unit"}})   # sold by weight
    rows = {r["product_id"]: r for r in read(db)[0]["rows"] if r["product_id"]}
    for pid in ("463335", "462921", "462775"):
        assert (rows[pid]["row"], rows[pid]["packs"], rows[pid]["pack_size"], rows[pid]["count"]) == \
            ("PLEASE_COUNT", None, None, None)
    assert rows["463038"]["count"] == "20"


def test_products_are_the_stock_list_and_own_products_of_this_kitchen_only():
    db = kitchen_db()
    Repository(db).own_products.create(KITCHEN, {"product_id": "own-rye", "name": "Rye sourdough loaf",
                                                 "supplier_id": "sup-bakery", "unit": "ST"})
    Repository(db).own_products.create("other-kitchen", {"product_id": "own-other", "name": "Oat drink barista",
                                                         "supplier_id": "sup-x", "unit": "ST"})
    db.products.insert_one({"_id": "999", "names": {"en": "Catalog product nobody stocks"}})
    products = {p["product_id"]: p for p in kitchen_products(db, KITCHEN)}
    assert set(products) == {p["product_id"] for p in PRODUCTS} | {"own-rye"}
    assert products["own-rye"] == {"product_id": "own-rye", "name": "Rye sourdough loaf", "unit": "PCS", "pack_size": "1"}
    rows = read(db, reply_of(("Rye sourdough loaf", "3", "medium"), ("Oat drink barista", "2", "high")))[0]["rows"]
    assert [(r["row"], r["product_id"], r["count"], r["unit"]) for r in rows] == [
        ("COUNTED", "own-rye", "3", "PCS"), ("UNMATCHED", None, None, None)]


def test_reading_writes_nothing():
    db = kitchen_db()
    before = {name: db[name].count_documents({}) for name in db.list_collection_names()}
    read(db)
    assert {name: db[name].count_documents({}) for name in db.list_collection_names()} == before
    assert before["kitchen_stock"] == len(PRODUCTS)


def test_no_model_key_is_vision_not_configured(monkeypatch):
    monkeypatch.delenv("VERDA_INFERENCE_KEY", raising=False)
    reader = ShelfReader(kitchen_db(), WorkerError)             # the real Nemotron factory
    with pytest.raises(WorkerError) as caught:
        asyncio.run(reader.read(KITCHEN, PHOTO))
    assert (caught.value.status, caught.value.code) == (503, "VISION_NOT_CONFIGURED")


def test_model_failure_reply_outside_schema_and_timeout_have_their_own_codes():
    class Down(Recorded):
        async def complete_json(self, *args, **kwargs):
            raise ModelError("Nemotron HTTP 500")

    class Slow(Recorded):
        async def complete_json(self, *args, **kwargs):
            await asyncio.sleep(5)

    db = kitchen_db()
    for model, expected in ((Down(REPLY), (503, "VISION_UNAVAILABLE")),
                            (Recorded({"role": "assistant", "content": '{"items": [{"label": "x", "count": "many"}]}'}),
                             (502, "VISION_REPLY_INVALID")),
                            (Slow(REPLY), (504, "VISION_TIMEOUT"))):
        reader = ShelfReader(db, WorkerError, model_factory=lambda: model, timeout=0.05)
        with pytest.raises(WorkerError) as caught:
            asyncio.run(reader.read(KITCHEN, PHOTO))
        assert (caught.value.status, caught.value.code) == expected
        assert model.closed


def test_not_an_image_and_too_large_never_reach_the_model():
    db = kitchen_db()
    reader, model = reader_for(db)
    for photo, expected in ((b"GIF89a" + b"0" * 50, (422, "NOT_AN_IMAGE")), (b"", (422, "NOT_AN_IMAGE")),
                            (b"\x89PNG" + b"0" * MAX_IMAGE_BYTES, (413, "IMAGE_TOO_LARGE"))):
        with pytest.raises(WorkerError) as caught:
            asyncio.run(reader.read(KITCHEN, photo))
        assert (caught.value.status, caught.value.code) == expected
    assert model.requests == []


def test_contract_rows_keep_two_counted_rows_apart():
    products = [{"product_id": "p", "name": "Milk 1 L", "unit": "L", "pack_size": "1.5"}]
    rows = [{"label": "Milk 1 L", "confidence": "high", "product_id": "p", "name": "Milk 1 L", "packs": n,
             "status": "COUNTED"} for n in (2, 3)]
    assert [r["count"] for r in contract_rows(rows, products)] == ["3", "4.5"]


def http(monkeypatch, reader):
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    monkeypatch.delenv("GATEWAY_KITCHEN_ID", raising=False)
    return TestClient(create_app(shelf=reader))


def body(photo=PHOTO, kitchen=KITCHEN):
    return {"kitchen_id": kitchen, "image_base64": base64.b64encode(photo).decode("ascii")}


def test_shelf_endpoint_answers_the_rows(monkeypatch):
    reader, _ = reader_for(kitchen_db())
    client = http(monkeypatch, reader)
    answer = client.post("/shelf", headers=BEARER, json=body())
    assert answer.status_code == 200, answer.text
    assert [r["row"] for r in answer.json()["rows"]] == ["COUNTED"] * 4 + ["UNMATCHED"]


def test_shelf_endpoint_refusals(monkeypatch):
    reader, model = reader_for(kitchen_db())
    client = http(monkeypatch, reader)

    def code(**kwargs):
        answer = client.post("/shelf", **kwargs)
        return answer.status_code, answer.json()["error"]["code"]
    assert code(json=body()) == (401, "UNAUTHENTICATED")
    assert code(headers={"Authorization": "Bearer wrong"}, json=body()) == (401, "UNAUTHENTICATED")
    assert code(headers=BEARER, json=body(kitchen="other-kitchen")) == (403, "KITCHEN_SCOPE")
    assert code(headers=BEARER, json={"kitchen_id": KITCHEN}) == (422, "INVALID_REQUEST")
    assert code(headers=BEARER, json={"kitchen_id": KITCHEN, "image_base64": "not base64 !"}) == (422, "INVALID_REQUEST")
    assert code(headers=BEARER, content=b"not json") == (422, "INVALID_REQUEST")
    assert code(headers=BEARER, json=body(b"plain text, not a photo")) == (422, "NOT_AN_IMAGE")
    assert code(headers=BEARER, json=body(b"\x89PNG" + b"0" * MAX_IMAGE_BYTES)) == (413, "IMAGE_TOO_LARGE")
    assert model.requests == []


def test_demo_shelf_matches_the_live_kitchens_catalog_names():
    """demo-shelf.png carries the names of the live demo kitchen's stock list; the reply is
    Nemotron's real one (2026-11-14). Butter and yoghurt show packs x pack size in KG."""
    truth = {"463335": 6, "464194": 5, "464187": 4, "462718": 3, "463437": 4}    # make_demo_shelf.py TRUTH
    products = json.loads((FIXTURES / "demo-kitchen.json").read_text(encoding="utf-8"))["products"]
    db = mongomock.MongoClient(tz_aware=True)["test"]
    for p in products:
        db.products.insert_one({"_id": p["product_id"], "names": {"en": p["name"]},
                                "net_content": {"value": float(p["pack_size"]), "unit": p["unit"]},
                                "net_content_source": "synkka"})
    record_stock_count(db, KITCHEN, AT, [{"product_id": p["product_id"], "on_hand": "1", "unit": p["unit"]}
                                         for p in products])
    reply = json.loads((FIXTURES / "demo-shelf.reply.json").read_text(encoding="utf-8"))
    rows = read(db, reply, (FIXTURES / "demo-shelf.png").read_bytes())[0]["rows"]
    counted = {r["product_id"]: (r["packs"], r["count"], r["unit"]) for r in rows if r["row"] == "COUNTED"}
    assert counted == {"463335": (6, "6", "L"), "464194": (5, "5", "L"), "464187": (4, "4", "L"),
                       "462718": (3, "6", "KG"), "463437": (4, "2", "KG")}
    assert all(counted[pid][0] == truth[pid] for pid in counted)
    [hidden] = [r for r in rows if r["row"] != "COUNTED"]                   # the half hidden Edam
    assert (hidden["row"], hidden["label"], hidden["count"]) == ("UNMATCHED", "Valio Edam 17 %", None)
