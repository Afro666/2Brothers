"""Valio's selling agent (#374): code builds the shortlist, the model only picks inside it."""

import asyncio
from datetime import date, datetime, timezone
import json
from pathlib import Path

from bson.decimal128 import Decimal128

import pytest

pytest.importorskip("mongomock")
pytest.importorskip("fastapi")

from agent import seller  # noqa: E402
from gateway.tests.test_supplier_offers import SHORT, SUBS, World  # noqa: E402

TODAY = date(2026, 11, 15)          # the shortage is on 2026-11-16


class FakeModel:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    async def complete_json(self, messages, schema, name, *, max_tokens=2048):
        self.calls.append(messages)
        if isinstance(self.answer, Exception):
            raise self.answer
        return {"role": "assistant", "content": self.answer if isinstance(self.answer, str)
                else json.dumps(self.answer)}


@pytest.fixture()
def w(monkeypatch):
    return World(monkeypatch)


def go(w, **kwargs):
    return asyncio.run(seller.run(w.gw, today=TODAY, **{"apply": False, "kitchen": "K1", **kwargs}))


def test_dry_run_prints_the_pick_and_sends_nothing(w):
    model = FakeModel({"index": 1, "reason": "Same pack size and in stock for Monday."})
    report = go(w, model=model)
    assert len(report) == 1
    row = report[0]
    assert row["result"] == "DRY_RUN" and row["offered_product_id"] == SUBS[1]
    assert row["shortlist"][0].startswith(SUBS[0]) and len(row["shortlist"]) == 4
    assert row["made_by"] == "nemotron-3.5-super-vl" and row["kitchen_needs"] == "40"
    assert w.db.supplier_offers.count_documents({}) == 0 and w.kinds() == []
    seen = json.dumps(model.calls)
    assert "Hotel One" not in seen and "K1" not in seen       # no kitchen name or id for the model
    assert "milk 462775" in seen and "oat drink 470002" in seen


def test_apply_sends_the_models_pick_once_with_the_gateways_quantity(w):
    model = FakeModel({"index": 1, "reason": "Same pack size and in stock for Monday."})
    report = go(w, model=model, apply=True, limit=1)
    assert report[0]["result"] == "OPEN" and report[0]["quantity"] == "40"
    stored = w.db.supplier_offers.find_one({})
    assert stored["product_id"] == SUBS[1] and stored["replaces_product_id"] == SHORT
    assert stored["made_by"] == "nemotron-3.5-super-vl" and stored["sent_by"] == "seller-agent"
    assert w.kinds() == ["supplier_offer_received"]
    again = go(w, model=model, apply=True, limit=1)            # a second run: nothing new, no model call
    assert again[0]["result"] == "ALREADY_OFFERED" and len(model.calls) == 1
    assert w.db.supplier_offers.count_documents({}) == 1


@pytest.mark.parametrize("answer", [
    {"index": 4, "reason": "outside the shortlist"}, {"index": -1, "reason": "x"},
    {"index": True, "reason": "a boolean is not an index"}, {"index": "1", "reason": "x"},
    {"index": 0, "reason": "\x00‮"}, {"index": 0}, [0, "x"], "not json", RuntimeError("no answer")])
def test_a_pick_outside_the_shortlist_or_no_valid_answer_means_no_offer(w, answer):
    report = go(w, model=FakeModel(answer), apply=True)
    assert report[0]["result"] == "NO_VALID_PICK" and "offered_product_id" not in report[0]
    assert w.db.supplier_offers.count_documents({}) == 0


def test_the_models_reason_is_cleaned_and_cut(w):
    model = FakeModel({"index": 0, "reason": "Good\x07 swap‮. " + "y" * 400})
    report = go(w, model=model, apply=True)
    reason = w.db.supplier_offers.find_one({})["reason"]
    assert report[0]["result"] == "OPEN" and len(reason) == 300 and reason.startswith("Good swap. yyy")


def test_shortlist_keeps_only_what_this_kitchen_may_get_and_what_can_arrive(w):
    w.db.kitchen_settings.insert_one({"_id": "K1", "excluded_allergens": ["AN"]})            # tree nuts
    w.db.products.update_one({"_id": SUBS[0]}, {"$set": {"allergens.contains": ["SA"]}})     # almond
    w.db.products.update_one({"_id": SUBS[1]}, {"$set": {"allergen_data_known": False}})     # unknown
    for p in w.fake.avail_data["products"]:
        if p["productId"] == SUBS[2]:
            p["scheduleLines"][0]["availableAmount"] = 10.0                                 # under K1's 40 L
    report = go(w)                                                                           # the rule picks
    assert report[0]["shortlist"] == [f"{SUBS[3]} oat drink {SUBS[3]}"]
    assert report[0]["offered_product_id"] == SUBS[3] and report[0]["made_by"] == "rule"
    w.db.products.update_one({"_id": SUBS[3]}, {"$set": {"net_content": {"value": 1.0, "unit": "KG"}}})
    assert go(w)[0]["result"] == "NO_SUBSTITUTE"                                             # another measure
    other = asyncio.run(seller.run(w.gw, today=TODAY, apply=False, kitchen="K2"))            # no nut rule
    assert other[0]["shortlist"] == [f"{SUBS[0]} oat drink {SUBS[0]}"]


def test_shortlist_reads_the_whole_category_and_puts_like_named_products_first(w):
    """No text search: it returned 50 hits by words and missed whole categories live."""
    w.gw._search = lambda *a, **k: pytest.fail("the shortlist must not depend on the text search")
    w.db.products.update_one({"_id": SUBS[2]}, {"$set": {"names": {"en": "lactose free milk 1 l"}}})
    w.db.products.update_one({"_id": SUBS[3]}, {"$set": {"category": "juice"}})          # another category
    w.db.products.insert_one({"_id": "own-milk", "source": "own", "kitchen_id": "K1", "category": "milk",
                              "names": {"en": "milk from the farm"}, "net_content": {"value": 1.0, "unit": "L"},
                              "allergen_data_known": True,
                              "allergens": {"contains": [], "may_contain": [], "undeclared": []}})
    assert [s.split()[0] for s in go(w)[0]["shortlist"]] == [SUBS[2], SUBS[0], SUBS[1]]


def test_valios_filler_amounts_are_not_confirmed_stock(w):
    for p in w.fake.avail_data["products"]:
        if p["productId"] == SUBS[0]:
            p["scheduleLines"][0]["availableAmount"] = 666666666.0
        if p["productId"] == SUBS[1]:
            p["scheduleLines"][0]["availableAmount"] = 1999999999.0
        if p["productId"] == SUBS[2]:
            del p["scheduleLines"][0]["availableDate"]
    assert [s.split()[0] for s in go(w)[0]["shortlist"]] == [SUBS[3]]


REAL = json.loads((Path(__file__).parent / "fixtures" / "seller_catalog.json").read_text(encoding="utf-8"))
# What Valio answered for these products on 2026-11-14 (amounts, missing lines, filler numbers).
REAL_STOCK = {"460137": 0.0, "460478": 0.0, "461903": 0.0,                 # the three short products
              "460012": 43.0, "460150": 1976.0, "460074": None,            # the cucumber category
              "460643": 121.0, "460603": 1999999999.0, "460541": 666666666.0,   # potatoes
              "461787": 300.0, "461872": 300.0, "461879": 300.0}            # fish
NEEDS = {"460478": "17.466", "461903": "12.226", "460137": "6.333"}        # the demo kitchen forecast, KG


@pytest.fixture()
def real(monkeypatch):
    """Cucumber, washed potato and salmon fillet with the catalog rows they have in real life:
    vegetables and potatoes carry no allergen data, the fish does."""
    from store.products import flatten
    world = World(monkeypatch)
    template = next(p for p in world.fake.avail_data["products"] if p["productId"] == SHORT)
    for raw in REAL:
        row = flatten(raw)
        world.db.products.replace_one({"_id": row["_id"]}, row, upsert=True)
        amount = REAL_STOCK[row["_id"]]
        lines = [] if amount is None else [{**template["scheduleLines"][0], "availableAmount": amount,
                                            "salesUnit": row["sales_unit"]}]
        world.fake.avail_data["products"].append({**template, "productId": row["_id"], "scheduleLines": lines})
    for p in world.fake.avail_data["products"]:
        if p["productId"] == "461872":
            p["closingTime"] = "2026-11-12T15:00:00+0200"                  # its cut-off passed
    world.db.forecasts.delete_many({})
    day = datetime(2026, 11, 16, tzinfo=timezone.utc)
    for pid, need in NEEDS.items():
        world.db.forecasts.insert_one({"ts": day, "meta": {"kitchen_id": "K1", "product_id": pid},
                                       "need": Decimal128(need), "unit": "KG"})
    world.db.kitchen_settings.insert_one({"_id": "K1", "excluded_allergens": ["AP", "AN", "AS"]})   # the demo mandate
    return world


def test_real_catalog_rows_cucumber_potato_and_salmon_each_get_a_substitute(real):
    report = asyncio.run(seller.run(real.gw, today=TODAY, apply=True, kitchen="K1", limit=3))
    by_short = {r["short_product_id"]: r for r in report}
    # Another potato with a real count; the two "plenty" filler amounts are not confirmed stock.
    assert by_short["460478"]["shortlist"] == ["460643 POTATO ROSAMUNDA WASHED"]
    # Fish has allergen data: only fish with allergen data, and not the one whose cut-off passed.
    assert by_short["461903"]["shortlist"] == ["461787 Mackerell whole fresh 200-400g"]
    # The namesake of the cucumber first, then the rest of the category; no stock line, no entry.
    assert by_short["460137"]["shortlist"] == ["460012 PICKLED CUCUMBER FI", "460150 COURGETTE FI"]
    assert [r["result"] for r in report] == ["OPEN", "OPEN", "OPEN"]
    stored = {d["replaces_product_id"]: d for d in real.db.supplier_offers.find({})}
    assert (stored["460137"]["product_id"], stored["460137"]["quantity"]) == ("460012", "6.333")
    assert stored["460137"]["allergen_data_known"] is False        # marked: a person checks the label
    assert stored["460478"]["allergen_data_known"] is False
    assert stored["461903"]["allergen_data_known"] is True


def test_a_misspelt_allergen_rule_means_no_offer(w):
    w.db.kitchen_settings.insert_one({"_id": "K1", "excluded_allergens": ["not-an-allergen"]})
    assert go(w, apply=True)[0]["result"] == "NO_SUBSTITUTE"
    assert w.db.supplier_offers.count_documents({}) == 0


def test_a_cut_off_that_passed_or_a_sales_block_is_not_offered(w):
    for p in w.fake.avail_data["products"]:
        if p["productId"] == SUBS[0]:
            p["closingTime"] = "2026-11-12T15:00:00+0200"
        if p["productId"] == SUBS[1]:
            p["salesBlock"] = True
        if p["productId"] == SUBS[2]:
            p["scheduleLines"][0]["availableAmount"] = 999999.0       # the sentinel: stock unknown
    assert go(w)[0]["shortlist"] == [f"{SUBS[3]} oat drink {SUBS[3]}"]


def test_without_the_model_the_rule_picks_the_first_entry_and_says_so(w):
    report = go(w, apply=True)
    stored = w.db.supplier_offers.find_one({})
    assert report[0]["result"] == "OPEN" and stored["product_id"] == SUBS[0] and stored["made_by"] == "rule"
    assert "Picked by rule, not by the model." in stored["reason"]


def test_a_kitchen_that_does_not_share_gets_nothing_and_every_kitchen_gets_one(w):
    assert go(w, kitchen="K3", apply=True) == [{
        "kitchen_id": "K3", "result": "SHARING_REQUIRED",
        "note": "this kitchen does not share its forecast with the supplier: it gets no offers"}]
    report = go(w, kitchen=None, apply=True)
    assert sorted((r["kitchen_id"], r["result"]) for r in report) == [("K1", "OPEN"), ("K2", "OPEN")]
    assert go(w, kitchen=None, apply=True, limit=1)[0]["result"] == "ALREADY_OFFERED"
    assert w.db.supplier_offers.count_documents({}) == 2


def test_cli_stops_before_any_work_when_the_model_key_is_missing(monkeypatch):
    monkeypatch.delenv("VERDA_INFERENCE_KEY", raising=False)
    monkeypatch.delenv("MONGODB_URI", raising=False)
    with pytest.raises(SystemExit) as stop:
        seller.main(["--dry-run"])
    assert "VERDA_INFERENCE_KEY" in str(stop.value)
    with pytest.raises(SystemExit):
        seller.main([])                       # --dry-run or --apply is required
