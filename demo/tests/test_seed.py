"""Demo data: no actuals in the future, deterministic, and the forecast proof holds."""

from datetime import date, datetime, timezone

import pytest

from demo.seed import DEMO_ID, build, load

mongomock = pytest.importorskip("mongomock")
TODAY = date(2026, 10, 12)


@pytest.fixture(scope="module")
def data():
    return build(seed=1, today=TODAY, future_weeks=2, kitchens=10)


def test_future_has_plans_and_forecasts_but_no_actuals(data):
    for name in ("stock", "covers", "orders", "deliveries"):
        assert all(r["ts"]["$date"] < TODAY.isoformat() for r in data[name]), name
    future = [r for r in data["forecasts"] if r["date"] >= TODAY.isoformat()]
    assert future and all(r["made_on"] == TODAY.isoformat() for r in future)
    assert any(p["week"] >= "2026-W43" for p in data["menu_plans"])


def test_past_forecasts_were_made_before_the_day(data):
    past = [r for r in data["forecasts"] if r["date"] < TODAY.isoformat()]
    assert past and all(r["made_on"] <= r["date"] for r in past)


def test_same_seed_same_data(data):
    again = build(seed=1, today=TODAY, future_weeks=2, kitchens=10)
    assert again["forecasts"][:50] == data["forecasts"][:50]
    assert len(again["stock"]) == len(data["stock"])


def test_load_and_prove_the_forecast(data, monkeypatch):
    from gateway.service import Gateway
    import store.history
    # mongomock has no time-series collections; plain collections behave the same here.
    monkeypatch.setattr(store.history, "ensure_history_collections",
                        lambda db: db.sharing.create_index([("kitchen_id", 1), ("supplier_id", 1)], unique=True))
    # The store keeps money as Decimal through its codec; mongomock has no codecs, so
    # convert to Decimal128 at the store boundary for this test only.
    from bson.decimal128 import Decimal128
    from decimal import Decimal
    real_insert = mongomock.collection.Collection.insert_many

    def insert_many(self, docs, *args, **kwargs):
        def fix(v):
            if isinstance(v, Decimal):
                return Decimal128(str(v))
            if isinstance(v, dict):
                return {k: fix(x) for k, x in v.items()}
            if isinstance(v, list):
                return [fix(x) for x in v]
            return v
        return real_insert(self, [fix(d) for d in docs], *args, **kwargs)

    monkeypatch.setattr(mongomock.collection.Collection, "insert_many", insert_many)
    db = mongomock.MongoClient(tz_aware=True)["test"]
    counts = load(db, data)
    assert counts["forecasts"] == len(data["forecasts"]) and counts["sharing"] >= 1
    load(db, data)                                   # idempotent: run twice, same counts
    assert db.forecasts.count_documents({}) == len(data["forecasts"])
    gw = Gateway(db, valio=None, now=lambda: datetime(2026, 10, 12, tzinfo=timezone.utc))
    proof = gw.forecast_accuracy(DEMO_ID, "2026-08-31", "2026-10-11")
    engine, base = proof["methods"]["engine"]["total"], proof["methods"]["weekday-average"]["total"]
    assert engine["actual"] > 0 and engine["wape"] < base["wape"]
    assert len(proof["methods"]["engine"]["weeks"]) == 6
    ahead = gw.forecast(DEMO_ID, "2026-10-12", "2026-10-25")["lines"]
    assert ahead and all(line["made_on"] == "2026-10-12" for line in ahead)
