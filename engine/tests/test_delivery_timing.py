"""Delivery timing (#1306): the statistics on hand-made histories, and the capped safety stock."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from engine.delivery_timing import (MAX_SHARE, MAX_SIGMA_DAYS, delivery_timing,
                                    learned_safety_stock, mean_days_late, on_time_rate,
                                    sigma_lead_time)

TODAY = date(2026, 11, 14)
KITCHEN = "k-1"
SUPPLIER = "bakery"
PRODUCT = "rye-bread"
Z = 1.96


def delivery(order_id, days_late=0, *, offset=10, promised_after=2, kitchen=KITCHEN,
             supplier=SUPPLIER, product=PRODUCT, revision=1, known=True):
    """One order: promised `promised_after` days after it was placed, delivered `days_late`
    days after the promise. `known=False`: nobody read the delivery date."""
    requested = TODAY - timedelta(days=offset)
    ordered = requested - timedelta(days=promised_after)
    delivered = requested + timedelta(days=days_late) if known else None
    return {
        "kitchen_id": kitchen, "order_id": order_id, "revision": revision,
        "supplier_id": supplier, "requested_date": requested.isoformat(),
        "ordered_at": f"{ordered.isoformat()}T09:00:00Z",
        "delivery_date": delivered.isoformat() if delivered else None,
        "days_late": days_late if known else None,
        "checked_at": f"{(delivered or requested).isoformat()}T08:00:00Z",
        "lines": [{"supplier_id": supplier, "product_id": product, "status": "RECEIVED",
                   "ordered": "10", "delivered": "10", "unit": "KG"}],
    }


def history(lateness, **kwargs):
    return [delivery(f"o{index}", late, offset=20 - index, **kwargs)
            for index, late in enumerate(lateness)]


def late_fact(active=True):
    return {"id": "lf_TEST", "kind": "SUPPLIER_LATE", "supplier_id": SUPPLIER,
            "name": "Corner Bakery", "active": active}


# --- the three statistics ---

def test_on_time_rate_counts_early_and_on_the_day_as_on_time():
    assert on_time_rate([0, 0, 1, 1, 1]) == Decimal("0.4")
    assert on_time_rate([-2, 0, 0]) == Decimal(1)
    assert on_time_rate([]) is None


def test_mean_days_late_is_over_late_deliveries_only_and_early_counts_as_zero():
    assert mean_days_late([0, 0, 1, 1, 1]) == Decimal(1)
    assert mean_days_late([-3, 0, 2, 4]) == Decimal(3)          # never (2 + 4 - 3) / 4
    assert mean_days_late([-3, -1, 0]) == Decimal(0)
    assert mean_days_late([]) is None


def test_sigma_lead_time_is_the_population_standard_deviation():
    assert sigma_lead_time([2, 2, 2, 2, 2]) == Decimal(0)
    assert float(sigma_lead_time([2, 2, 3, 3, 3])) == pytest.approx(0.4899, abs=1e-4)
    assert sigma_lead_time([]) is None


# --- per supplier, from a history ---

def test_all_on_time_gives_rate_one_and_no_spread():
    timing = delivery_timing(KITCHEN, SUPPLIER, history([0, 0, 0, 0, 0]), TODAY)
    assert timing["deliveries"] == 5 and timing["late"] == 0
    assert timing["on_time_rate"] == Decimal(1) and timing["mean_days_late"] == Decimal(0)
    assert timing["mean_lead_time"] == Decimal(2) and timing["sigma_lead_time"] == Decimal(0)
    assert timing["scope"] == "supplier"


def test_three_of_five_a_day_late():
    timing = delivery_timing(KITCHEN, SUPPLIER, history([0, 1, 0, 1, 1]), TODAY)
    assert timing["deliveries"] == 5 and timing["late"] == 3
    assert timing["on_time_rate"] == Decimal("0.4")
    assert timing["mean_days_late"] == Decimal(1)
    assert timing["mean_lead_time"] == Decimal("2.6")
    assert float(timing["sigma_lead_time"]) == pytest.approx(0.4899, abs=1e-4)
    assert timing["evidence"] == {"rows": 5, "late": 3, "scope": "supplier",
                                  "from": (TODAY - timedelta(days=20)).isoformat(),
                                  "to": (TODAY - timedelta(days=15)).isoformat(),
                                  "last": (TODAY - timedelta(days=15)).isoformat()}


def test_an_early_delivery_is_on_time_and_adds_no_negative_lateness():
    timing = delivery_timing(KITCHEN, SUPPLIER, history([-1, -1, 0, 2, 2]), TODAY)
    assert timing["on_time_rate"] == Decimal("0.6")
    assert timing["mean_days_late"] == Decimal(2)
    assert timing["sigma_lead_time"] > 0          # an early arrival still spreads the lead time


def test_fewer_than_five_deliveries_give_nothing():
    assert delivery_timing(KITCHEN, SUPPLIER, history([1, 1, 1, 1]), TODAY) is None


def test_an_unknown_delivery_date_is_left_out_and_never_counts_as_on_time():
    rows = history([1, 1, 1, 1]) + [delivery("unread", known=False, offset=5)]
    assert delivery_timing(KITCHEN, SUPPLIER, rows, TODAY) is None
    rows.append(delivery("fifth", 0, offset=4))
    timing = delivery_timing(KITCHEN, SUPPLIER, rows, TODAY)
    assert timing["deliveries"] == 5 and timing["on_time_rate"] == Decimal("0.2")


def test_deliveries_older_than_eight_weeks_do_not_count():
    rows = history([1, 1, 1, 1]) + [delivery("old", 1, offset=58)]    # delivered 57 days ago
    assert delivery_timing(KITCHEN, SUPPLIER, rows, TODAY) is None


def test_another_kitchen_or_supplier_never_counts():
    rows = history([1, 1, 1, 1])
    rows.append(delivery("theirs", 1, offset=5, kitchen="k-2"))
    rows.append(delivery("other", 1, offset=5, supplier="dairy"))
    assert delivery_timing(KITCHEN, SUPPLIER, rows, TODAY) is None
    assert delivery_timing(KITCHEN, "dairy", rows, TODAY) is None


def test_a_recheck_replaces_the_reading_and_counts_the_order_once():
    rows = history([0, 0, 0, 0, 1])
    rows.append(delivery("o4", 0, offset=16, revision=2))       # the recheck: on time after all
    timing = delivery_timing(KITCHEN, SUPPLIER, rows, TODAY)
    assert timing["deliveries"] == 5 and timing["late"] == 0


def test_per_product_needs_five_deliveries_of_that_product():
    rows = history([1, 1, 1, 1, 1]) + [
        delivery(f"b{index}", 0, offset=9 - index, product="buns") for index in range(5)]
    bread = delivery_timing(KITCHEN, SUPPLIER, rows, TODAY, product_id=PRODUCT)
    assert bread["scope"] == "product" and bread["on_time_rate"] == Decimal(0)
    buns = delivery_timing(KITCHEN, SUPPLIER, rows, TODAY, product_id="buns")
    assert buns["on_time_rate"] == Decimal(1)
    assert delivery_timing(KITCHEN, SUPPLIER, rows[:9], TODAY, product_id="buns") is None
    assert delivery_timing(KITCHEN, SUPPLIER, rows, TODAY)["on_time_rate"] == Decimal("0.5")


# --- the safety stock ---

def timing_3_of_5():
    return delivery_timing(KITCHEN, SUPPLIER, history([0, 1, 0, 1, 1]), TODAY)


def test_safety_stock_rises_by_z_times_daily_demand_times_sigma():
    adjusted, info = learned_safety_stock("70", "10", timing_3_of_5(), late_fact(),
                                          z=Z, lead_time_days=2, unit="KG")
    # 1.96 x 10 KG/day x 0.4899 days = 9.60 KG
    assert adjusted == Decimal("79.6")
    assert info == {"fact_id": "lf_TEST", "kind": "SUPPLIER_LATE", "name": "Corner Bakery",
                    "from_qty": "70", "to_qty": "79.6", "unit": "KG", "safety_stock": "9.6",
                    "sigma_lead_time": 0.49, "capped": False,
                    "evidence": timing_3_of_5()["evidence"]}
    assert isinstance(adjusted, Decimal)


def test_safety_stock_never_passes_a_quarter_of_the_need():
    # A one-day window: 70 KG/day x 1.96 x 0.49 would add 67 KG, almost double.
    adjusted, info = learned_safety_stock("70", "70", timing_3_of_5(), late_fact(),
                                          z=Z, lead_time_days=2, unit="KG")
    assert MAX_SHARE == Decimal("0.25")
    assert adjusted == Decimal("87.5") and info["safety_stock"] == "17.5"
    assert info["capped"] is True


def test_a_wild_spread_counts_for_two_days_at_most():
    rows = [delivery(f"o{index}", late, offset=20 - index)
            for index, late in enumerate([0, 9, 0, 9, 9])]
    timing = delivery_timing(KITCHEN, SUPPLIER, rows, TODAY)
    assert timing["sigma_lead_time"] > MAX_SIGMA_DAYS
    adjusted, info = learned_safety_stock("700", "1", timing, late_fact(),
                                          z=Z, lead_time_days=2, unit="KG")
    assert info["sigma_lead_time"] == 2.0 and info["capped"] is True
    assert adjusted == Decimal("703.92")                        # 1.96 x 1 x 2


def test_no_safety_stock_without_a_late_supplier():
    on_time = delivery_timing(KITCHEN, SUPPLIER, history([0, 0, 0, 0, 1]), TODAY)   # 0.8
    assert learned_safety_stock("70", "10", on_time, late_fact(), z=Z, lead_time_days=2) == (
        Decimal("70"), None)
    steady = delivery_timing(KITCHEN, SUPPLIER, history([1, 1, 1, 1, 1]), TODAY)    # late, sigma 0
    assert learned_safety_stock("70", "10", steady, late_fact(), z=Z, lead_time_days=2) == (
        Decimal("70"), None)
    assert learned_safety_stock("70", "10", None, late_fact(), z=Z, lead_time_days=2) == (
        Decimal("70"), None)


def test_a_switched_off_fact_restores_the_plain_number():
    assert learned_safety_stock("70", "10", timing_3_of_5(), late_fact(active=False),
                                z=Z, lead_time_days=2) == (Decimal("70"), None)
    assert learned_safety_stock("70", "10", timing_3_of_5(),
                                {**late_fact(), "kind": "SUPPLIER_SHORT"},
                                z=Z, lead_time_days=2) == (Decimal("70"), None)


def test_no_demand_or_a_bad_number_changes_nothing():
    timing = timing_3_of_5()
    assert learned_safety_stock("70", "0", timing, late_fact(), z=Z, lead_time_days=2)[1] is None
    assert learned_safety_stock("0", "10", timing, late_fact(), z=Z, lead_time_days=2)[1] is None
    assert learned_safety_stock("x", "10", timing, late_fact(), z=Z, lead_time_days=2) == ("x", None)
    assert learned_safety_stock("70", float("nan"), timing, late_fact(), z=Z,
                                lead_time_days=2)[1] is None


def test_the_learned_mean_lead_time_replaces_the_term_from_one_day_of_difference():
    from engine.delivery_timing import lead_time_for
    assert lead_time_for(2, Decimal("2.6")) == Decimal(2)       # under a day: the term stays
    assert lead_time_for(1, Decimal("2.6")) == Decimal("2.6")
    assert lead_time_for(None, Decimal("2.6")) == Decimal("2.6")
    assert lead_time_for(2, None) == Decimal(2)
    assert lead_time_for(None, None) == Decimal(0)
