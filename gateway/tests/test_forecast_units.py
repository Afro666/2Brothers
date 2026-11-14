"""The forecast check gives short and waste per unit and in euros (#1618)."""
from datetime import datetime, timezone
from decimal import Decimal

import mongomock

from gateway.forecast_value import units_and_prices
from gateway.service import Gateway


def ts(day, hour=22):
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00").replace(tzinfo=timezone.utc)


def stock(db, day, pid, unit, used, received=0):
    db.kitchen_stock.insert_one({"meta": {"kitchen_id": "k1", "product_id": pid}, "ts": ts(day),
                                 "unit": unit, "used": used, "short": 0, "received": received})


def forecast(db, day, pid, unit, need):
    for name in ("forecasts", "forecast_baseline"):
        db[name].insert_one({"meta": {"kitchen_id": "k1", "product_id": pid}, "ts": ts(day, 0),
                             "need": need, "unit": unit, "made_on": day})


def kitchen():
    db = mongomock.MongoClient(tz_aware=True).test
    # History so the weekday baseline is eligible on 2026-08-24.
    stock(db, "2026-08-17", "milk", "L", 10)
    stock(db, "2026-08-17", "eggs", "KG", 3)
    # Milk: sold in cases of 5 L at 4.38 EUR, short 2 L. Eggs: no order, waste 1 KG.
    stock(db, "2026-08-24", "milk", "L", 12, received=10)
    stock(db, "2026-08-24", "eggs", "KG", 3)
    db.deliveries.insert_one({"meta": {"kitchen_id": "k1", "product_id": "milk"}, "ts": ts("2026-08-24", 6),
                              "delivered_qty": 2})
    db.orders_history.insert_one({"meta": {"kitchen_id": "k1"}, "ts": ts("2026-08-23", 14),
                                  "lines": [{"product_id": "milk", "qty": 2, "unit_price": 4.38}]})
    forecast(db, "2026-08-24", "milk", "L", 10)
    forecast(db, "2026-08-24", "eggs", "KG", 4)
    return db


def test_units_and_prices_per_kitchen_unit():
    units, prices = units_and_prices(kitchen(), "k1", datetime(2026, 8, 17).date(), datetime(2026, 8, 24).date())
    assert units == {"milk": "L", "eggs": "KG"}
    assert prices == {"milk": Decimal("4.38") / Decimal("5")}


def test_forecast_check_has_no_sum_over_mixed_units():
    methods = Gateway(kitchen(), None).forecast_accuracy("k1", "2026-08-24", "2026-08-24")["methods"]
    for method in methods.values():
        total = method["total"]
        assert total["under"] is None and total["over"] is None
        rows = {row["unit"]: row for row in total["by_unit"]}
        assert rows["L"]["under"] == 2.0 and rows["L"]["under_eur"] == "1.75"
        assert rows["KG"]["over"] == 1.0 and rows["KG"]["over_eur"] is None
        assert total["under_eur"] == "1.75" and total["unpriced_series"] == 1
        assert method["weeks"][0]["by_unit"] == total["by_unit"]
