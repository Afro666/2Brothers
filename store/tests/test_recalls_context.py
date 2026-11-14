"""The kitchen the recall monitor scans: open proposals, the shelf and the recipes (#358)."""

from datetime import datetime, timedelta, timezone

import pytest

mongomock = pytest.importorskip("mongomock")

from store import recalls  # noqa: E402
from store.history import record_stock_count  # noqa: E402
from store.repository import Repository  # noqa: E402

NOW = datetime(2026, 11, 14, 7, 0, tzinfo=timezone.utc)


def database():
    db = mongomock.MongoClient(tz_aware=True).db
    for pid in ("461332", "475842", "400100", "400200", "400300"):
        db.products.insert_one({"_id": pid, "brand": "B", "names": {"en": "Product " + pid}})
    return db


def count(db, kitchen, pid, on_hand, at=NOW, unit="KG"):
    record_stock_count(db, kitchen, at, [{"product_id": pid, "unit": unit, "on_hand": on_hand}])


def test_no_proposal_no_stock_no_recipe_is_an_empty_kitchen():
    kitchen, proposals = recalls.context(database(), "hotel")
    assert proposals == []
    assert kitchen == {"kitchen_id": "hotel", "products": [], "proposal": [], "stock": {}, "recipes": {}}


def test_counted_stock_is_in_the_kitchen_without_any_proposal():
    db = database()
    count(db, "hotel", "461332", "3.253")
    kitchen, proposals = recalls.context(db, "hotel")
    assert proposals == [] and kitchen["proposal"] == []
    assert kitchen["stock"] == {"461332": (3.253, "KG")}
    assert [row["product_id"] for row in kitchen["products"]] == ["461332"]


def test_a_zero_count_is_not_on_the_shelf_and_the_newest_count_wins():
    db = database()
    count(db, "hotel", "461332", "4", at=NOW - timedelta(days=2))
    count(db, "hotel", "461332", "0")
    count(db, "hotel", "475842", "0", at=NOW - timedelta(days=2))
    count(db, "hotel", "475842", "2")
    kitchen, _ = recalls.context(db, "hotel")
    assert kitchen["stock"] == {"475842": (2.0, "KG")}
    assert [row["product_id"] for row in kitchen["products"]] == ["475842"]


def test_an_uncounted_product_is_unknown_never_zero():
    db = database()
    count(db, "hotel", "461332", None)
    kitchen, _ = recalls.context(db, "hotel")
    assert kitchen["stock"] == {"461332": (None, "KG")}
    assert [row["product_id"] for row in kitchen["products"]] == ["461332"]


def test_another_kitchens_shelf_and_recipes_are_not_read():
    db = database()
    count(db, "school", "461332", "9")
    Repository(db).recipes.create("school", {"name": "Coffee", "portions": 10, "ingredients": [
        {"product_id": "461332", "qty_per_portion": "0.01", "unit": "KG"}]})
    kitchen, _ = recalls.context(db, "hotel")
    assert kitchen["stock"] == {} and kitchen["recipes"] == {} and kitchen["products"] == []


def test_recipe_ingredients_are_in_the_kitchen_with_the_recipe_names():
    db = database()
    recipes = Repository(db).recipes
    recipes.create("hotel", {"name": "Breakfast coffee", "portions": 10, "ingredients": [
        {"product_id": "461332", "qty_per_portion": "0.01", "unit": "KG"},
        {"product_id": "400100", "qty_per_portion": "0.02", "unit": "L"}]})
    recipes.create("hotel", {"name": "Tiramisu", "portions": 8, "ingredients": [
        {"product_id": "461332", "qty_per_portion": "0.005", "unit": "KG"}]})
    kitchen, _ = recalls.context(db, "hotel")
    assert kitchen["recipes"] == {"461332": ["Breakfast coffee", "Tiramisu"], "400100": ["Breakfast coffee"]}
    assert sorted(row["product_id"] for row in kitchen["products"]) == ["400100", "461332"]


def test_open_proposal_products_stay_and_join_the_shelf():
    db = database()
    db.offers.insert_one({"_id": "o1", "simulation": {"lines": [{"product_id": "400200"}]}})
    db.offers.insert_one({"_id": "o2", "simulation": {"lines": [{"product_id": "400300"}]}})
    db.proposals.insert_one({"_id": "p1", "kitchen_id": "hotel", "status": "READY", "offer_id": "o1"})
    db.proposals.insert_one({"_id": "p2", "kitchen_id": "hotel", "status": "APPROVED", "offer_id": "o2"})
    count(db, "hotel", "461332", "1.5")
    kitchen, proposals = recalls.context(db, "hotel")
    assert [p["_id"] for p in proposals] == ["p1"]
    assert kitchen["proposal"] == ["400200"]            # only open proposals; the shelf is not a proposal
    assert [row["product_id"] for row in kitchen["products"]] == ["400200", "461332"]
