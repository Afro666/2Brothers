"""The demo offer reset: a new round for one kitchen; nothing is deleted."""

import pytest

from demo.reset_offers import reset
from store import supplier_offers as offers

mongomock = pytest.importorskip("mongomock")


def seed(db):
    for oid, kitchen, status in (("a", "demo-kitchen", "ACCEPTED"), ("b", "demo-kitchen", "DECLINED"),
                                 ("c", "other-kitchen", "ACCEPTED")):
        db.supplier_offers.insert_one({"_id": oid, "kitchen_id": kitchen, "status": status,
                                       "product_name": "flounder", "requested_date": "2026-11-20"})


def test_dry_run_lists_the_rounds_offers_and_changes_nothing():
    db = mongomock.MongoClient(tz_aware=True)["t"]
    seed(db)
    out = reset(db, "demo-kitchen", apply=False)
    assert out["round"] == 0 and out["new_round"] is None and len(out["offers"]) == 2
    assert offers.round_of(db, "demo-kitchen") == 0 and db.audit_log.count_documents({}) == 0


def test_apply_starts_a_new_round_keeps_every_offer_and_writes_one_audit_entry():
    db = mongomock.MongoClient(tz_aware=True)["t"]
    seed(db)
    out = reset(db, "demo-kitchen", apply=True)
    assert out["new_round"] == 1 and offers.round_of(db, "demo-kitchen") == 1
    assert offers.round_of(db, "other-kitchen") == 0
    assert db.supplier_offers.count_documents({}) == 3
    events = list(db.audit_log.find({}))
    assert len(events) == 1 and events[0]["event"]["kind"] == "demo_offers_reset"
    assert reset(db, "demo-kitchen", apply=False)["offers"] == []           # the new round has none yet
