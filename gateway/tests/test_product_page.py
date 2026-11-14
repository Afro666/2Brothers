"""The product page route (#1603): one call, every part with its source, unknown stays unknown."""

from datetime import datetime, timezone

import pytest

pytest.importorskip("mongomock")
pytest.importorskip("fastapi")

from gateway.tests.test_gateway_app import HUMAN, K, env, milk  # noqa: E402, F401
from store.repository import Repository  # noqa: E402

PID = "462775"
RAW_TEXT = {
    "marketingTexts": [{"language": "en", "value": "Lactose-free milk for kitchens."},
                       {"language": "fi", "value": "Laktoositon maito."}],
    "keyIngredients": [{"language": "en", "value": "MILK"}],
    "ingredients": [{"sequence": 1, "names": [{"language": "en", "value": "Milk"}, {"language": "fi", "value": "Maito"}]}],
    "storageInstructions": [{"language": "en", "value": "Keep below +6 C."}],
    "producers": [{"id": "1", "name": "Testi Oy"}],
    "nutritionalContent": [{"id": "ENER-E14", "value": 46.0, "unit": "E14", "basisQuantity": 100.0, "basisQuantityUnit": "MLT"},
                           {"id": "FAT", "value": 1.5, "unit": "GRM", "basisQuantity": 100.0, "basisQuantityUnit": "MLT"}],
    "vatCode": "MEDIUM",
}


@pytest.fixture()
def page(env):
    client, fake, db = env
    db.products.update_one({"_id": PID}, {"$set": {
        "source": "valio", "names": {"en": "Lactose-free milk 1 l", "fi": "Laktoositon maito 1 l"},
        "brand": "Testi", "category": "10101", "sales_unit": "ST", "base_unit": "ST",
        "net_content": {"value": 1.0, "unit": "L"}, "country": "fi", "temperature": "chilled",
        "allergens": {"contains": ["AM"], "may_contain": [], "undeclared": []}, "allergen_data_known": True,
        "free_from": ["ML"], "vat_code": "MEDIUM", "vat_rate": "13.5", "vat_source": "catalog",
        "raw.synkkaData": RAW_TEXT}})
    repo = Repository(db)
    repo.suppliers.create("demo-kitchen", {"supplier_id": "sup-valio", "name": "Valio Aimo", "adapter": "valio_api",
                                           "terms": {"free_delivery_threshold_eur": "300.00", "delivery_fee_eur": "25.00",
                                                     "order_days": ["MON", "TUE"], "cutoff_time": "17:00",
                                                     "lead_time_days": 1}})
    repo.suppliers.create("demo-kitchen", {"supplier_id": "sup-dairy", "name": "Hill Dairy (demo)", "adapter": "manual",
                                           "terms": {"lead_time_days": 2, "order_days": ["WED"], "cutoff_time": "12:00"}})
    repo.own_products.create("demo-kitchen", {"product_id": "own-milk-cheap", "name": "Farm milk 1 l",
                                              "supplier_id": "sup-dairy", "unit": "ST", "base_unit": "L",
                                              "pack_size_in_base_units": "1", "unit_price_eur": "1.10",
                                              "vat_rate": "13.5", "catalog_product_id": PID})
    repo.own_products.create("demo-kitchen", {"product_id": "own-milk-dear", "name": "Farm milk 2 l",
                                              "supplier_id": "sup-dairy", "unit": "ST", "base_unit": "L",
                                              "pack_size_in_base_units": "2", "unit_price_eur": "5.00",
                                              "catalog_product_id": PID})
    repo.own_products.create("other-kitchen", {"product_id": "own-other", "name": "Not yours",
                                               "supplier_id": "sup-x", "unit": "ST", "catalog_product_id": PID})
    return client, fake, db


def get(client, pid=PID, query=""):
    return client.get(f"{K}/catalog/products/{pid}{query}", headers=HUMAN)


def test_catalog_product_page_has_every_part_with_its_source(page):
    client, _, _ = page
    r = get(client, query="?date=2026-11-16")
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["product_id"] == PID and p["product"]["names"]["en"] == "Lactose-free milk 1 l"
    assert "raw" not in p["product"] and "embedding" not in p["product"]
    assert p["about"]["marketing_text"]["en"] == "Lactose-free milk for kitchens."
    assert p["about"]["ingredients"] == [{"en": "Milk", "fi": "Maito"}]
    assert p["about"]["producer"] == "Testi Oy" and p["about"]["source"] == "Valio product data"
    assert p["allergens"]["known"] is True
    assert p["allergens"]["contains"] == [{"code": "AM", "name": "milk"}]
    assert p["nutrition"]["basis"] == "ml" and p["nutrition"]["values"]["fat_g"] == "1.5"
    assert p["vat"] == {"code": "MEDIUM", "rate": "13.5", "source": "Valio product data, vatCode"}
    assert p["origin"]["country"] == "fi" and p["storage"]["temperature"] == "chilled"
    live = p["live"]
    assert (live["date"], live["price_ex_vat"], live["tax_rate"], live["error"]) == ("2026-11-16", "2.57", "13.5", None)
    assert live["stock"]["available"] == "51" and live["stock"]["unknown"] is False
    assert p["recall"] == {"status": "CLEAR", "alerts": [], "source": "this kitchen's recall alerts"}


def test_suppliers_valio_first_then_the_same_product_elsewhere_cheapest_per_litre(page):
    client, _, _ = page
    suppliers = get(client).json()["suppliers"]
    assert [(s["supplier_id"], s["product_id"]) for s in suppliers] == [
        ("sup-valio", PID), ("sup-dairy", "own-milk-cheap"), ("sup-dairy", "own-milk-dear")]
    valio, cheap, dear = suppliers
    assert (valio["price_ex_vat"], valio["price_source"], valio["stock_known"]) == ("2.57", "Valio price API", True)
    assert (valio["free_delivery_threshold_eur"], valio["lead_time_days"], valio["lead_time_source"]) == (
        "300", 1, "supplier_terms")
    assert (cheap["price_ex_vat"], cheap["vat_rate"], cheap["stock_known"]) == ("1.1", "13.5", False)
    assert (cheap["lead_time_days"], cheap["order_days"], cheap["name"]) == (2, ["WED"], "Hill Dairy (demo)")
    assert dear["vat_rate"] is None                     # nothing entered: unknown
    assert all(s["product_id"] != "own-other" for s in suppliers)   # never another kitchen's


def test_unknown_valio_stock_stays_unknown(page):
    client, _, _ = page
    stock = get(client, "463335", "?date=2026-11-16").json()["live"]["stock"]    # 9999999999 in the fixture
    assert stock["unknown"] is True and stock["available"] is None


def test_valio_down_never_fails_the_page(page):
    client, fake, _ = page

    def broken():
        raise RuntimeError("upstream text that must not leak")
    fake.hook = broken
    r = get(client)
    assert r.status_code == 200
    live = r.json()["live"]
    assert live["error"] == "VALIO_UNAVAILABLE" and live["price_ex_vat"] is None and live["stock"] is None
    assert "upstream" not in r.text


def test_kitchen_stats_orders_waiting_proposals_stock_recipes(page):
    client, _, db = page
    p = milk(client, quantity="51")                     # a READY proposal with 462775
    repo = Repository(db)
    repo.recipes.create("demo-kitchen", {"recipe_id": "rec-porridge", "name": "Porridge", "portions": 1,
                                         "ingredients": [{"product_id": PID, "qty_per_portion": "0.2", "unit": "L"}]})
    from store.history import record_stock_count
    record_stock_count(db, "demo-kitchen", datetime(2026, 11, 13, 8, tzinfo=timezone.utc),
                       [{"product_id": PID, "unit": "L", "on_hand": "12"}])
    k = get(client).json()["kitchen"]
    assert [w["proposal_id"] for w in k["proposals_waiting"]] == [p["proposal_id"]]
    assert k["proposals_waiting"][0]["quantity"] == "51"
    assert k["recipes"] == [{"recipe_id": "rec-porridge", "name": "Porridge", "qty_per_portion": "0.2", "unit": "L"}]
    assert k["stock"]["on_hand"] == "12" and k["stock"]["unit"] == "L"
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert r.status_code == 200, r.text
    k = get(client).json()["kitchen"]
    assert k["proposals_waiting"] == []
    (order,) = k["orders"]
    assert (order["order_id"], order["quantity"], order["total"]) == (r.json()["order_id"], "51", "131.07")


def test_newest_waiting_proposal_shows_past_200_older_ready_ones(page):
    client, _, db = page
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.proposals.insert_many([{"_id": f"old-{i}", "kitchen_id": "demo-kitchen", "status": "READY",
                               "offer_id": f"old-offer-{i}", "idempotency_key": f"old-{i}",
                               "created_at": old} for i in range(250)])
    p = milk(client, quantity="51")                     # inserted last, created newest
    waiting = get(client).json()["kitchen"]["proposals_waiting"]
    assert [w["proposal_id"] for w in waiting] == [p["proposal_id"]]


def test_recall_alert_blocks_until_dismissed(page):
    client, _, db = page
    db.recall_alerts.insert_one({"_id": "recall-1", "kitchen_id": "demo-kitchen", "product_id": PID,
                                 "match": "exact", "recall": {"title": "Milk recall"}})
    recall = get(client).json()["recall"]
    assert recall["status"] == "BLOCKED_BY_RECALL" and recall["alerts"][0]["title"] == "Milk recall"
    db.recall_alerts.update_one({"_id": "recall-1"}, {"$set": {"status": "dismissed"}})
    assert get(client).json()["recall"]["status"] == "CLEAR"


def test_own_product_page_lists_its_supplier_then_the_catalog_product(page):
    client, _, _ = page
    p = get(client, "own-milk-dear").json()
    assert p["live"] is None and p["about"] is None and p["nutrition"] is None
    assert p["allergens"]["known"] is False              # nothing entered: unknown, never free from
    assert [s["product_id"] for s in p["suppliers"]] == ["own-milk-dear", PID, "own-milk-cheap"]
    assert p["suppliers"][1]["price_ex_vat"] == "2.57"   # the catalog product's live price
    assert p["vat"] == {"code": None, "rate": None, "source": None}   # nothing entered: unknown


def test_vat_source_on_the_page_is_a_label_for_the_row_enum(page):
    # #1609: the row says `catalog` / `entered`; the page's `vat.source` reads like its other sources
    client, _, _ = page
    assert get(client).json()["product"]["vat_source"] == "catalog"
    own = get(client, "own-milk-cheap").json()
    assert own["product"]["vat_source"] == "entered"
    assert own["vat"] == {"code": None, "rate": "13.5", "source": "entered by the kitchen"}


def test_a_row_with_the_old_free_text_source_still_reads(page):
    # live rows filled before #1609 keep the old text until `python -m store.vat --apply`
    client, _, db = page
    db.products.update_one({"_id": PID}, {"$set": {"vat_source": "Valio product data, vatCode"}})
    assert get(client).json()["vat"]["source"] == "Valio product data, vatCode"


def test_unknown_or_other_kitchens_product_is_404_and_bad_date_422(page):
    client, _, _ = page
    for pid in ("999999", "own-other"):
        r = get(client, pid)
        assert r.status_code == 404 and r.json()["error"]["code"] == "PRODUCT_NOT_FOUND"
    r = get(client, query="?date=16.11.2026")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST"


def test_needs_kitchen_read(page):
    client, _, _ = page
    assert client.get(f"{K}/catalog/products/{PID}").status_code == 401



def test_every_allergen_code_has_a_name_not_only_the_first_of_its_group():
    """Review of #1625: GB (barley) and SA (almond) came back with name None."""
    from gateway.product_page import ALLERGEN_NAMES
    from store.search import ALLERGENS
    for codes in ALLERGENS.values():
        for code in codes:
            assert ALLERGEN_NAMES.get(code), code
    assert ALLERGEN_NAMES["GB"] == "barley (gluten)" and ALLERGEN_NAMES["SA"] == "almond (nuts)"
    assert ALLERGEN_NAMES["AM"] == "milk" and ALLERGEN_NAMES["AW"] == "gluten"
