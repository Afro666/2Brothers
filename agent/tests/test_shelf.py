import asyncio
from datetime import datetime, timezone
import json

import pytest

from agent.shelf import (FIXTURES, SHELF_SCHEMA, RecordedModel, count_rows, main, match_product,
                         read_shelf, stock_count_body)
from agent.vision import VisionError

PRODUCTS = json.loads((FIXTURES / "kitchen.json").read_text(encoding="utf-8"))["products"]
REPLY = json.loads((FIXTURES / "shelf.reply.json").read_text(encoding="utf-8"))
TRUTH = {"462775": 7, "463335": 6, "462921": 4, "463038": 2}   # make_shelf.py; 464179 is half hidden
AT = datetime(2026, 11, 14, 2, 0, tzinfo=timezone.utc)


def rows_for(reply=REPLY):
    model = RecordedModel(reply)
    return asyncio.run(read_shelf(FIXTURES / "shelf.png", PRODUCTS, model)), model


def test_recorded_shelf_counts_four_products_within_one_pack():
    rows, model = rows_for()
    counted = {r["product_id"]: r["packs"] for r in rows if r["status"] == "COUNTED"}
    assert set(counted) == set(TRUTH)
    assert all(abs(counted[pid] - n) <= 1 for pid, n in TRUTH.items())
    [request] = model.requests
    assert request["schema"] is SHELF_SCHEMA
    assert request["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_half_hidden_box_is_never_a_number():
    rows, _ = rows_for()
    unsure = [r for r in rows if r["confidence"] == "low"]
    assert unsure and all(r["packs"] is None and r["status"] != "COUNTED" for r in unsure)


def test_low_confidence_or_unknown_count_asks_a_person():
    reply = {"items": [{"label": "Valio Eila 3% 1 L", "count": "6", "confidence": "low"},
                       {"label": "Valio Eila organic 1 L", "count": "unknown", "confidence": "high"}]}
    assert [r["status"] for r in count_rows(reply, PRODUCTS)] == ["PLEASE_COUNT", "PLEASE_COUNT"]


def test_match_needs_one_clear_product():
    assert match_product("Arla lactose free 1L", PRODUCTS)["product_id"] == "462775"
    assert match_product("Valio Eila 10L novobox", PRODUCTS)["product_id"] == "463038"
    assert match_product("Valio Eila 1 L", PRODUCTS) is None        # 3% and organic tie
    assert match_product("Oat drink barista", PRODUCTS) is None


def test_stock_count_body_sends_only_what_a_person_confirmed():
    rows, _ = rows_for()
    body = stock_count_body(rows, PRODUCTS, {"462775": 7, "463038": 2}, AT, "shelf-test")
    counts = {c["product_id"]: c["on_hand"] for c in body["counts"]}
    assert counts == {"462775": "7", "463038": "20", "463335": None, "462921": None}
    assert all(c["unit"] == "L" for c in body["counts"]) and body["source"] == "manual"
    with pytest.raises(ValueError):
        stock_count_body(rows, PRODUCTS, {}, datetime(2026, 11, 14), "naive")


def test_reply_outside_schema_is_refused():
    with pytest.raises(VisionError):
        rows_for({"role": "assistant", "content": json.dumps({"items": [{"label": "x", "count": "about 6",
                                                                          "confidence": "high"}]})})


def test_cli_offline(capsys):
    assert main([str(FIXTURES / "shelf.png")]) == 0
    assert "COUNTED      7 packs       462775" in capsys.readouterr().out
    assert main([str(FIXTURES / "shelf.png"), "--confirm-all"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert {c["product_id"]: c["on_hand"] for c in body["counts"]}["463038"] == "20"
