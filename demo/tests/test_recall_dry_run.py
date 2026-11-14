"""#1076: the recall dry run lists what the check would alert and writes nothing."""

from datetime import datetime, timezone

import pytest

mongomock = pytest.importorskip("mongomock")

from demo.recall_dry_run import COFFEE, main, verdict  # noqa: E402

NOW = "2026-11-14T18:00:00+00:00"
KITCHEN = "demo-kitchen"


def product(db, pid, brand, name, gtin=None):
    db.products.insert_one({"_id": pid, "brand": brand, "names": {"en": name, "fi": name},
                            "units": [{"unitId": "ST", "gtin": gtin}] if gtin else []})


def stock(db, pid, on_hand):
    db.kitchen_stock.insert_one({"ts": datetime(2026, 11, 13, tzinfo=timezone.utc),
                                 "meta": {"kitchen_id": KITCHEN, "product_id": pid},
                                 "unit": "KG", "on_hand": on_hand, "source": "manual"})


def kitchen():
    db = mongomock.MongoClient(tz_aware=True)["t"]
    product(db, COFFEE, "Kulta Katriina", "Kulta Katriina Perinteinen kahvi")
    product(db, "462775", "Valio", "Valio maito 1 l")
    stock(db, COFFEE, 3.25)
    stock(db, "462775", 10)
    return db


def snapshot(db):
    return {name: list(db[name].find()) for name in db.list_collection_names()}


def test_only_the_coffee_alerts_and_nothing_is_written(capsys):
    db = kitchen()
    before = snapshot(db)
    assert main(["--kitchen", KITCHEN, "--now", NOW], db=db) == 0
    out = capsys.readouterr().out
    assert f"[possible] {COFFEE}" in out and "in stock: 3.25 KG" in out
    assert "OK: only the expected products would alert" in out
    assert snapshot(db) == before                     # no recall_alerts, no audit entry, no hold
    assert "recall_alerts" not in db.list_collection_names()


def test_another_alerting_product_fails_the_dry_run(capsys):
    db = kitchen()
    product(db, "469512", "Elovena", "Elovena kaurajuoma kahviin barista 1 l")
    stock(db, "469512", 6)
    assert main(["--kitchen", KITCHEN, "--now", NOW], db=db) == 1
    out = capsys.readouterr().out
    assert "unexpected: 469512" in out and "NOT OK" in out


def test_a_kitchen_without_the_coffee_reports_it_missing(capsys):
    db = kitchen()
    db.kitchen_stock.delete_many({"meta.product_id": COFFEE})
    assert main(["--kitchen", KITCHEN, "--now", NOW], db=db) == 1
    assert f"missing: {COFFEE}" in capsys.readouterr().out


def test_review_alerts_count_only_with_strict():
    alerts = [{"product_id": COFFEE, "match": "possible"}, {"product_id": "x", "match": "review"}]
    assert verdict(alerts, {COFFEE})["ok"]
    assert verdict(alerts, {COFFEE}, strict=True)["unexpected"] == ["x"]
