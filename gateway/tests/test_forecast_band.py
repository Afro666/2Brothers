"""GET forecast (#578): the p10-p90 band comes from each product's own forecast errors."""

from datetime import datetime, timedelta, timezone

import mongomock

from gateway.service import Gateway

K = "k1"
NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)


def history(db, pid, ratios):
    """One past day per ratio: forecast 10, actual 10 * ratio."""
    for d, ratio in enumerate(ratios, start=1):
        ts = NOW - timedelta(days=d)
        meta = {"kitchen_id": K, "product_id": pid}
        db.forecasts.insert_one({"ts": ts, "meta": meta, "need": 10.0, "unit": "KG"})
        db.kitchen_stock.insert_one({"ts": ts, "meta": meta, "used": 10.0 * ratio, "short": 0})


def ahead(db, pid):
    db.forecasts.insert_one({"ts": NOW + timedelta(days=1), "meta": {"kitchen_id": K, "product_id": pid},
                             "need": 10.0, "unit": "KG", "made_on": "2026-10-12"})


def forecast(db):
    gw = Gateway(db, valio=None, now=lambda: NOW)
    out = gw.forecast(K, "2026-10-13", "2026-10-13")
    return out, {line["product_id"]: line for line in out["lines"]}


def test_volatile_and_steady_products_get_their_own_band():
    db = mongomock.MongoClient(tz_aware=True)["test"]
    history(db, "milk", [0.98 + 0.002 * (i % 10) for i in range(25)])   # +-2%
    history(db, "herbs", [0.5 + 0.04 * i for i in range(25)])           # 0.5 .. 1.46
    history(db, "rare", [1.0, 1.1, 0.9])                               # too few of its own
    for pid in ("milk", "herbs", "rare"):
        ahead(db, pid)

    out, lines = forecast(db)
    width = {pid: line["p90"] - line["p10"] for pid, line in lines.items()}
    assert width["herbs"] > 5 * width["milk"]
    assert lines["milk"]["band_from"] == lines["herbs"]["band_from"] == "product forecast errors"
    # The rare product uses the pooled kitchen errors: neither milk's nor herbs' band.
    assert lines["rare"]["band_from"] == "own forecast errors" == out["band_from"]
    assert width["milk"] < width["rare"] < width["herbs"]


def test_few_errors_anywhere_falls_back_to_default_spread():
    db = mongomock.MongoClient(tz_aware=True)["test"]
    history(db, "rare", [1.0, 1.1, 0.9])
    ahead(db, "rare")
    out, lines = forecast(db)
    assert out["band_from"] == lines["rare"]["band_from"] == "default spread"
    assert lines["rare"]["p10"] < 10 < lines["rare"]["p90"]
