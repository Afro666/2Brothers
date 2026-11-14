"""store/supplier_offers.py (#374): one offer per supplier, kitchen, product and date; decided once."""

import pytest

mongomock = pytest.importorskip("mongomock")

from store import supplier_offers as offers  # noqa: E402


def doc(key="k1", product="p1", day="2026-11-16", kitchen="K1"):
    return {"_id": offers.offer_id("sup", kitchen, product, day), "supplier_id": "sup", "kitchen_id": kitchen,
            "product_id": product, "requested_date": day, "idempotency_key": key, "status": offers.OPEN,
            "created_at": f"2026-11-14T05:00:00+00:00-{key}"}


@pytest.fixture()
def db():
    database = mongomock.MongoClient(tz_aware=True)["test"]
    offers.ensure_indexes(database)
    return database


def test_insert_stores_one_row_per_offer_and_per_key(db):
    first, created = offers.insert(db, doc())
    assert created and first["status"] == "OPEN"
    same_offer, created = offers.insert(db, doc(key="k2"))            # same four, another key
    assert not created and same_offer["idempotency_key"] == "k1"
    same_key, created = offers.insert(db, doc(key="k1", product="p2"))    # same key, another product
    assert not created and same_key["product_id"] == "p1"
    assert db.supplier_offers.count_documents({}) == 1
    assert offers.by_key(db, "sup", "k1")["_id"] == first["_id"]
    assert offers.by_key(db, "other", "k1") is None


def test_get_is_scoped_to_the_kitchen_and_the_list_is_newest_first(db):
    a, _ = offers.insert(db, doc("k1", "p1"))
    b, _ = offers.insert(db, doc("k2", "p2"))
    offers.insert(db, doc("k3", "p1", kitchen="K2"))
    assert offers.get(db, "K1", a["_id"])["_id"] == a["_id"]
    assert offers.get(db, "K2", a["_id"]) is None
    assert [row["_id"] for row in offers.list_for_kitchen(db, "K1")] == [b["_id"], a["_id"]]


def test_decide_changes_an_open_offer_once(db):
    a, _ = offers.insert(db, doc())
    done = offers.decide(db, "K1", a["_id"], offers.ACCEPTED, proposal_id="prop-1", decided_by="aron")
    assert done["status"] == "ACCEPTED" and done["proposal_id"] == "prop-1"
    assert offers.decide(db, "K1", a["_id"], offers.DECLINED, decided_by="tymon") is None
    assert offers.get(db, "K1", a["_id"])["decided_by"] == "aron"
    b, _ = offers.insert(db, doc("k2", "p2"))
    assert offers.decide(db, "K2", b["_id"], offers.DECLINED) is None      # another kitchen cannot
    with pytest.raises(ValueError):
        offers.decide(db, "K1", b["_id"], "OPEN")


def test_count_open_leaves_out_decided_and_past_offers(db):
    a, _ = offers.insert(db, doc("k1", "p1"))
    offers.insert(db, doc("k2", "p2"))
    offers.insert(db, doc("k3", "p3", day="2026-11-10"))                   # past its date
    offers.insert(db, doc("k4", "p4", kitchen="K2"))
    assert offers.count_open(db, "sup", "K1", "2026-11-14") == 2
    offers.decide(db, "K1", a["_id"], offers.DECLINED)
    assert offers.count_open(db, "sup", "K1", "2026-11-14") == 1
