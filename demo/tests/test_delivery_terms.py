"""#1453: demo lead time and reliability are deterministic, in range, and marked demo."""

import pytest

from demo.delivery_terms import RANGES, build, kind
from demo.seed import DEMO_OWN_PRODUCTS

CATALOG = [
    {"_id": "1", "names": {"en": "Fresh salmon fillet 1 kg"}, "temperature": "chilled"},
    {"_id": "2", "names": {"fi": "Ruisleipä 500 g"}, "temperature": "ambient"},
    {"_id": "3", "names": {"en": "Wheat flour 2 kg"}, "temperature": "ambient"},
    {"_id": "4", "names": {"en": "Milk 1 L"}, "temperature": "chilled"},
    {"_id": "5", "names": {"en": "Frozen fish fingers"}, "temperature": "frozen"},
]


def test_kinds_set_the_lead_time_override():
    _, products = build(1, CATALOG, DEMO_OWN_PRODUCTS)
    by_id = {p["product_id"]: p for p in products}
    assert [by_id[i]["kind"] for i in "12345"] == ["fish", "bakery", "dry", "other", "other"]
    assert [by_id[i].get("lead_time_days") for i in "12345"] == [1, 1, 2, None, None]
    assert by_id["own-rye-loaf"]["supplier_id"] == "sup-bakery" and by_id["own-rye-loaf"]["lead_time_days"] == 1
    assert kind(None, None) == "other"


def test_same_seed_same_values_and_in_range():
    suppliers, products = build(1, CATALOG, DEMO_OWN_PRODUCTS)
    assert build(1, CATALOG, DEMO_OWN_PRODUCTS) == (suppliers, products)
    assert build(2, CATALOG, DEMO_OWN_PRODUCTS)[1] != products
    for p in products:
        low, high = RANGES[p["kind"]]
        assert low <= p["reliability"] <= high
    assert {s["supplier_id"] for s in suppliers} == {"sup-valio", "sup-bakery"}
    assert all(0 < s["reliability"] < 1 and s["lead_time_days"] >= 1 for s in suppliers)


def test_load_writes_rows_marked_demo_and_runs_again():
    mongomock = pytest.importorskip("mongomock")
    from demo.delivery_terms import load
    from store import demo_delivery

    db = mongomock.MongoClient().db
    db.kitchens.insert_one({"_id": "demo-kitchen", "synthetic": True})
    db.products.insert_many([{**p, "source": "valio"} for p in CATALOG])
    first = load(db)
    assert load(db) == first == 2 + len(CATALOG) + len(DEMO_OWN_PRODUCTS)
    assert db[demo_delivery.COLLECTION].count_documents({"demo": {"$ne": True}}) == 0
    found = demo_delivery.lookup(db, "demo-kitchen", "sup-valio", ["1", "own-rye-loaf"])
    assert found["supplier"]["lead_time_days"] == 2
    assert set(found["products"]) == {"1"}                 # the bakery's product is not Valio's
