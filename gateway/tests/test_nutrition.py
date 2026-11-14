"""Nutrition from the catalog's label data: per recipe portion, per menu day, per order."""

from decimal import Decimal as D

from engine import nutrition
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env  # noqa: F401 (fixture)


def label(kcal, protein, fat, carbs, salt, unit="GRM", basis=100.0, with_kcal=True):
    rows = [{"id": "PRO-", "value": protein, "basisQuantity": basis, "basisQuantityUnit": unit},
            {"id": "FAT", "value": fat, "basisQuantity": basis, "basisQuantityUnit": unit},
            {"id": "CHOAVL", "value": carbs, "basisQuantity": basis, "basisQuantityUnit": unit},
            {"id": "SALTEQ", "value": salt, "basisQuantity": basis, "basisQuantityUnit": unit},
            {"id": "ENER-KJO", "value": round(kcal * 4.184), "basisQuantity": basis, "basisQuantityUnit": unit}]
    if with_kcal:
        rows.append({"id": "ENER-E14", "value": kcal, "basisQuantity": basis, "basisQuantityUnit": unit})
    return {"synkkaData": {"nutritionalContent": rows}}


MILK = label(46, 3.4, 1.5, 4.8, 0.1, unit="MLT")
OATS = label(370, 13.0, 7.0, 58.0, 0.0)
PORRIDGE = {"recipe_id": "porridge", "name": "Oat porridge", "ingredients": [
    {"product_id": "469549", "qty_per_portion": "0.2", "unit": "L"},
    {"product_id": "oats", "qty_per_portion": "0.05", "unit": "KG"}]}


def test_label_is_read_per_100_and_kj_is_the_fallback():
    got = nutrition.per_100(MILK)
    assert got["basis"] == "ml" and got["kcal"] == D("46") and got["protein_g"] == D("3.4")
    assert nutrition.per_100(label(46, 3.4, 1.5, 4.8, 0.1, with_kcal=False))["kcal"].quantize(D("1")) == D("46")
    assert nutrition.per_100(label(120, 4, 2, 20, 0.5, basis=40.0))["kcal"] == D("300")      # 40 g basis scaled
    assert nutrition.per_100({"synkkaData": {"nutritionalContent": []}}) is None
    assert nutrition.per_100(None) is None
    portion_only = {"synkkaData": {"nutritionalContent": [
        {"id": "ENER-E14", "value": 200, "basisQuantity": 1.0, "basisQuantityUnit": "PTN"}]}}
    assert nutrition.per_100(portion_only) is None                                           # cannot be scaled


def test_recipe_portion_adds_up_and_names_what_it_cannot_count():
    products = {"469549": {"raw": MILK}, "oats": {"raw": OATS}}
    got = nutrition.recipe_portion(PORRIDGE, products)
    assert got["per_portion"]["kcal"] == D("277")            # 200 ml x 0.46 + 50 g x 3.70
    assert got["per_portion"]["protein_g"] == D("13.3") and got["complete"] is True
    missing = nutrition.recipe_portion(PORRIDGE, {"469549": {"raw": MILK}, "oats": {"raw": None}})
    assert missing["complete"] is False and missing["unknown"] == ["oats"]
    assert missing["per_portion"]["kcal"] == D("92")         # the known part only, and it says so


def seed(client, db):
    db.products.update_one({"_id": "469549"}, {"$set": {
        "names": {"en": "Valio semi skimmed milk 1 l"}, "raw": MILK, "sales_unit": "ST",
        "net_content": {"value": 1.0, "unit": "L"}, "units": [{"unit": "ST", "size_in_base_units": 1.0}]}}, upsert=True)
    db.products.insert_one({"_id": "oats", "names": {"en": "Oat flakes"}, "raw": OATS,
                            "net_content": {"value": 1.0, "unit": "KG"}})
    assert client.post(K + "/recipes", headers=HUMAN, json=PORRIDGE).status_code == 200
    plan = {"days": [{"date": "2026-11-16", "meal": "breakfast", "recipe_id": "porridge", "covers": 100},
                     {"date": "2026-11-17", "meal": "breakfast", "recipe_id": "porridge", "covers": 80}]}
    assert client.put(K + "/menu-plans/2026-W47", headers=HUMAN, json=plan).status_code == 200


def test_recipe_route(env):
    client, _, db = env
    seed(client, db)
    got = client.get(K + "/recipes/porridge/nutrition", headers=AGENT).json()
    assert got["per_portion"]["kcal"] == "277" and got["complete"] is True and got["unknown"] == []
    assert client.get(K + "/recipes/nope/nutrition", headers=AGENT).status_code == 404


def test_window_planned_per_day_and_ordered_against_planned(env):
    client, _, db = env
    seed(client, db)
    got = client.get(K + "/nutrition?from=2026-11-16&to=2026-11-22", headers=AGENT).json()
    days = {d["date"]: d for d in got["days"]}
    assert days["2026-11-16"]["kcal"] == "27700" and days["2026-11-16"]["kcal_per_cover"] == "277"
    assert got["planned"]["kcal"] == "49860" and got["planned"]["complete"] is True
    assert got["ordered"]["lines"] == 0 and got["ordered_vs_planned"] is None      # nothing ordered yet: not 0
    db.proposals.insert_one({"_id": "p1", "kitchen_id": "demo-kitchen", "idempotency_key": "n1",
                             "request": {"requested_date": "2026-11-16"}})
    db.orders.insert_one({"_id": "o1", "kitchen_id": "demo-kitchen", "idempotency_key": "n1", "outcome": "CONFIRMED",
                          "proposal_id": "p1", "lines": [{"product_id": "469549", "quantity": "40", "unit": "ST"},
                                                         {"product_id": "462775", "quantity": "5", "unit": "ST"}]})
    got = client.get(K + "/nutrition?from=2026-11-16&to=2026-11-22", headers=AGENT).json()
    assert got["ordered"]["kcal"] == "18400"                # 40 L milk x 460 kcal
    assert got["ordered"]["known_lines"] == 1 and got["ordered"]["unknown"] == ["462775"]
    assert got["ordered_vs_planned"] == "0.37"
    assert client.get(K + "/nutrition?from=2026-11-16", headers=AGENT).status_code == 422
