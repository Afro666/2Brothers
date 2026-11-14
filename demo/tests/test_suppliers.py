"""The invented demo suppliers (#1604): clearly demo, idempotent, removable, and kept away from
the rehearsed stage stories (docs/demo.md)."""

import re
from decimal import Decimal

import pytest

mongomock = pytest.importorskip("mongomock")

from demo.suppliers import PRODUCT_IDS, PRODUCTS, SUPPLIER_IDS, SUPPLIERS, load, main, remove  # noqa: E402
from store.repository import Repository  # noqa: E402

KITCHEN = "demo-kitchen"
# Words of the rehearsed requests and beats: the milk stories (1,000 L and 200 L), cream and
# cheese, oat drink, chicken breast, the peanut-butter refusal and the recalled coffee.
STAGE = re.compile(r"milk|maito|cream|kerma|cheese|juusto|butter|\bvoi\b|oat drink|kaurajuoma"
                   r"|chicken|kana|peanut|maapähkinä|coffee|kahvi", re.I)


@pytest.fixture()
def db():
    return mongomock.MongoClient(tz_aware=True)["test"]


def test_every_supplier_is_invented_demo_data_and_manual():
    assert len(SUPPLIERS) == 4
    for s in SUPPLIERS:
        assert s["name"].endswith("(demo)") and s["supplier_id"].startswith("sup-demo-")
        assert s["adapter"] == "manual"                  # no API: stock unknown, a person may approve
        terms = s["terms"]
        assert None not in (terms["free_delivery_threshold_eur"], terms["delivery_fee_eur"],
                            terms["order_days"], terms["cutoff_time"], terms["lead_time_days"])


def test_products_are_the_same_as_a_valio_product_with_its_category_and_a_vat_rate():
    assert len(set(PRODUCT_IDS)) == len(PRODUCTS)
    for p in PRODUCTS:
        assert p["product_id"].startswith("own-demo-") and p["supplier_id"] in SUPPLIER_IDS
        assert re.fullmatch(r"\d{6}", p["catalog_product_id"]) and re.fullmatch(r"\d{5}", p["category"])
        assert p["vat_rate"] == "13.5" and Decimal(p["unit_price_eur"]) > 0
    assert {p["supplier_id"] for p in PRODUCTS} == set(SUPPLIER_IDS)


def test_nothing_touches_the_rehearsed_stage_stories():
    hits = [p["name"] for p in PRODUCTS if STAGE.search(p["name"])]
    assert hits == []
    # Not the Valio products of the stories either: the milks, cream, butter, cheese, chicken, coffee.
    stage_ids = {"463171", "463335", "464194", "463437", "462616", "462281", "461332", "463380", "462775"}
    assert not stage_ids & {p["catalog_product_id"] for p in PRODUCTS}
    assert not any(a["code"] == "AP" for p in PRODUCTS for a in p["allergens"])
    # Nor their categories, so the Buyer's kind filter for those requests keeps what it had:
    # milk 10400, cream 10401, butter 10500, cheese 10602, chicken 18750, coffee 22300.
    assert not {"10400", "10401", "10500", "10602", "18750", "22300"} & {p["category"] for p in PRODUCTS}


def test_load_is_idempotent_and_remove_deletes_exactly_these(db):
    repo = Repository(db)
    repo.suppliers.create(KITCHEN, {"supplier_id": "sup-bakery", "name": "Corner Bakery (demo)",
                                    "adapter": "manual", "terms": {}})
    repo.own_products.create(KITCHEN, {"product_id": "own-rye-loaf", "name": "Rye", "supplier_id": "sup-bakery",
                                       "unit": "ST"})
    assert load(db) == load(db) == {"suppliers": 4, "products": len(PRODUCTS)}
    assert {s["supplier_id"] for s in repo.suppliers.list(KITCHEN)} == {"sup-bakery", *SUPPLIER_IDS}
    salmon = repo.own_products.get(KITCHEN, "own-demo-salmon-fillet")
    assert (salmon["catalog_product_id"], salmon["category"], salmon["vat_rate"]) == ("461903", "18701", "13.5")
    assert remove(db) == {"suppliers": 4, "products": len(PRODUCTS)}
    assert [s["supplier_id"] for s in repo.suppliers.list(KITCHEN)] == ["sup-bakery"]
    assert [p["product_id"] for p in repo.own_products.list(KITCHEN)] == ["own-rye-loaf"]
    assert remove(db) == {"suppliers": 0, "products": 0}


def test_dry_run_writes_nothing(capsys, monkeypatch, db):
    monkeypatch.setattr("store.db.get_db", lambda: db)
    main([])
    assert "nothing written" in capsys.readouterr().out
    assert db.suppliers.count_documents({}) == 0
