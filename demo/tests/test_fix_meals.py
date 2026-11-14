"""Only the meal of the seeded menu entries changes (#1618)."""
import mongomock

from demo.fix_meals import fix
from store.repository import Repository


def plans(db):
    db.kitchens.insert_one({"_id": "demo-kitchen", "type": "hotel", "synthetic": True})
    db.kitchens.insert_one({"_id": "other-kitchen", "type": "hotel", "synthetic": True})
    repo = Repository(db)
    repo.menu_plans.put("demo-kitchen", "2026-W46", [
        {"date": "2026-11-09", "meal": "lunch", "recipe_id": "env-breakfast_buffet", "covers": 120},
        {"date": "2026-11-09", "meal": "lunch", "recipe_id": "env-burger", "covers": 40},
        # A person's own entries stay as they are, even a seeded recipe at another meal.
        {"date": "2026-11-10", "meal": "lunch", "recipe_id": "own-soup", "covers": 30},
        {"date": "2026-11-10", "meal": "other", "recipe_id": "env-burger", "covers": 5},
    ])
    repo.menu_plans.put("other-kitchen", "2026-W46", [
        {"date": "2026-11-09", "meal": "lunch", "recipe_id": "env-breakfast_buffet", "covers": 1}])
    return repo


def test_dry_run_lists_the_changes_and_writes_nothing():
    db = mongomock.MongoClient().test
    repo = plans(db)
    out = fix(db, "demo-kitchen", apply=False)
    assert out == {"weeks": 1, "entries": 2, "applied": False}
    assert [d["meal"] for d in repo.menu_plans.get("demo-kitchen", "2026-W46")["days"]] == [
        "lunch", "lunch", "lunch", "other"]


def test_apply_changes_only_the_meal_and_is_idempotent():
    db = mongomock.MongoClient().test
    repo = plans(db)
    assert fix(db, "demo-kitchen", apply=True)["entries"] == 2
    days = repo.menu_plans.get("demo-kitchen", "2026-W46")["days"]
    assert [(d["recipe_id"], d["meal"], d["covers"]) for d in days] == [
        ("env-breakfast_buffet", "breakfast", 120), ("env-burger", "dinner", 40),
        ("own-soup", "lunch", 30), ("env-burger", "other", 5)]
    assert fix(db, "demo-kitchen", apply=True) == {"weeks": 0, "entries": 0, "applied": True}
    assert repo.menu_plans.get("other-kitchen", "2026-W46")["days"][0]["meal"] == "lunch"


def test_refuses_a_kitchen_that_is_not_synthetic():
    db = mongomock.MongoClient().test
    plans(db)
    db.kitchens.insert_one({"_id": "real", "type": "hotel"})
    try:
        fix(db, "real", apply=True)
    except ValueError as error:
        assert "synthetic" in str(error)
    else:
        raise AssertionError("a real kitchen must be refused")
