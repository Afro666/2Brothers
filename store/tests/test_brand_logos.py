"""store.brand_logos: one row per brand, written once, and the brands still to ask."""
from datetime import datetime, timezone

import pytest

mongomock = pytest.importorskip("mongomock")

from store import brand_logos  # noqa: E402

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
URL = "https://media.brand.dev/valio.png"


@pytest.fixture()
def db():
    return mongomock.MongoClient(tz_aware=True)["test"]


def test_a_row_is_written_once(db):
    brand_logos.put(db, "Valio", status="found", checked_at=NOW, logo_url=URL, background="own", domain="valio.fi")
    brand_logos.put(db, "Valio", status="none", checked_at=NOW)
    row = brand_logos.get_many(db, ["Valio"])["Valio"]
    assert row["status"] == "found" and row["logo_url"] == URL and row["background"] == "own"
    assert row["domain"] == "valio.fi"


def test_none_keeps_no_logo_fields(db):
    brand_logos.put(db, "HK", status="none", checked_at=NOW, logo_url=URL, background="own", domain="hk.fi")
    row = brand_logos.get_many(db, ["HK"])["HK"]
    assert (row["status"], row["logo_url"], row["background"], row["domain"]) == ("none", None, None, None)


@pytest.mark.parametrize("fields", [
    {"status": "maybe"},
    {"status": "found", "logo_url": "http://plain.example/logo.png", "background": "own"},
    {"status": "found", "logo_url": URL, "background": "blue"},
    {"status": "found"},
])
def test_a_bad_row_is_refused(db, fields):
    with pytest.raises(ValueError):
        brand_logos.put(db, "Valio", checked_at=NOW, **fields)
    assert db.brand_logos.count_documents({}) == 0


def test_get_many_leaves_out_unknown_names(db):
    brand_logos.put(db, "HK", status="none", checked_at=NOW)
    assert set(brand_logos.get_many(db, ["HK", "Arla", "HK"])) == {"HK"}
    assert brand_logos.get_many(db, []) == {}


def test_unchecked_brands_most_products_first(db):
    rows = [("1", "Valio"), ("2", "Valio"), ("3", "Valio"), ("4", "Arla"), ("5", "Arla"),
            ("6", "Fazer"), ("7", "Atria"), ("8", None), ("9", "")]
    db.products.insert_many([{"_id": pid, "source": "valio", "brand": brand} for pid, brand in rows])
    db.products.insert_one({"_id": "own-1", "source": "own", "brand": "My kitchen", "kitchen_id": "K01"})
    brand_logos.put(db, "Arla", status="none", checked_at=NOW)
    assert brand_logos.unchecked_brands(db, 10) == ["Valio", "Atria", "Fazer"]
    assert brand_logos.unchecked_brands(db, 1) == ["Valio"]
    assert brand_logos.unchecked_brands(db, 0) == []
