"""Learning facts: trusted corrections only, and delivery statistics without invented zeros."""

import math
from datetime import date, timedelta
from decimal import Decimal

import pytest

from engine.learning import (apply_ratio, correction_ratio_fact, declined_product_fact,
                             fact_id, supplier_facts)


TODAY = date(2026, 11, 14)
KITCHEN = "k-1"
PRODUCT = "potato"
SUPPLIER = "supplier-1"


def when(offset):
    return TODAY - timedelta(days=offset)


def feedback(offset, *, feedback_id=None, kind="qty_changed", from_qty="40", to_qty="20",
             need="40", reason="TOO_MUCH", approved=True, ran_out=None, product_id=PRODUCT):
    key = feedback_id or f"fb-{offset}-{kind}-{to_qty}"
    return {
        "feedback_id": key,
        "ts": f"{when(offset).isoformat()}T10:00:00Z",
        "kitchen_id": KITCHEN,
        "proposal_id": f"p-{key}",
        "product_id": product_id,
        "kind": kind,
        "from_qty": from_qty,
        "to_qty": to_qty,
        "unit": "KG",
        "reason": reason,
        "context": {"forecast_need": need},
        "outcome": {"ran_out": ran_out},
        "approved": approved,
    }


def delivery(order_id, *, days_late=0, offset=10, supplier=SUPPLIER, revision=1,
             has_delivery_date=True, ordered_before=2, has_ordered_at=True,
             checked_offset=None, lines=None):
    delivered = when(offset) if has_delivery_date else None
    ordered = delivered - timedelta(days=ordered_before) if delivered and has_ordered_at else None
    checked = when(checked_offset) if checked_offset is not None else delivered
    return {
        "kitchen_id": KITCHEN,
        "order_id": order_id,
        "revision": revision,
        "supplier_id": supplier,
        "delivery_date": delivered.isoformat() if delivered else None,
        "ordered_at": f"{ordered.isoformat()}T00:00:00Z" if ordered else None,
        "days_late": days_late,
        "checked_at": f"{checked.isoformat()}T08:00:00Z" if checked else None,
        "lines": lines or [],
    }


def test_potato_case_learns_half_from_forecast_need():
    rows = [feedback(offset) for offset in (40, 30, 20, 10)]
    fact = correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY)

    assert fact is not None
    assert fact["kind"] == "CORRECTION_RATIO"
    assert fact["value"] == pytest.approx(0.5)
    assert fact["raw_value"] == pytest.approx(0.5)
    assert fact["applicable"] is True
    assert fact["active"] is True
    assert fact["evidence"] == {"rows": 4, "from": when(40).isoformat(),
                                "to": when(10).isoformat(), "last": when(10).isoformat()}
    assert fact["since"] == fact["evidence"]["last"]


def test_a_row_against_an_already_learned_quantity_uses_forecast_need():
    rows = [feedback(offset, from_qty="20", to_qty="20") for offset in (10, 9, 8)]
    fact = correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY)

    assert fact is not None
    assert fact["value"] == pytest.approx(0.5)
    assert fact["value"] != pytest.approx(1.0)


def test_stock_menu_and_ran_out_rows_do_not_count():
    rows = [feedback(offset) for offset in (10, 9, 8)]
    rows += [
        feedback(7, reason="IN_STOCK", feedback_id="in-stock"),
        feedback(6, reason="MENU_CHANGED", feedback_id="menu"),
        feedback(5, ran_out=True, feedback_id="ran-out"),
    ]
    fact = correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY)

    assert fact is not None
    assert fact["evidence"]["rows"] == 3


def test_fewer_than_three_corrections_makes_no_fact():
    rows = [feedback(offset) for offset in (10, 9)]
    assert correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY) is None


def test_missing_or_untrusted_forecast_need_excludes_the_row():
    rows = [feedback(offset) for offset in (10, 9)]
    missing = feedback(8)
    missing["context"]["forecast_need"] = None
    rows.append(missing)
    assert correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY) is None

    rows[-1]["context"]["forecast_need"] = "NaN"
    assert correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY) is None


def test_out_of_band_ratio_is_clamped_and_not_applicable():
    rows = [feedback(offset, to_qty="8") for offset in (10, 9, 8)]
    fact = correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY)

    assert fact is not None
    assert fact["raw_value"] == pytest.approx(0.2)
    assert fact["value"] == pytest.approx(0.3)
    assert fact["applicable"] is False


def test_no_change_band_makes_no_fact():
    rows = [feedback(offset, to_qty="40") for offset in (10, 9, 8)]
    assert correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY) is None


def test_unapproved_rows_do_not_count():
    rows = [feedback(offset, approved=False) for offset in (10, 9, 8)]
    assert correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY) is None


def test_eight_week_window_is_inclusive_and_older_rows_drop_out():
    current = [feedback(offset) for offset in (10, 9, 8)]
    boundary = feedback(56, feedback_id="boundary")
    fact = correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", current + [boundary], TODAY)
    assert fact is not None
    assert fact["evidence"]["rows"] == 4

    old = [feedback(57, feedback_id="old")]
    assert correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", current + old, TODAY)["evidence"]["rows"] == 3
    assert correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato",
                                 [feedback(59), feedback(58), feedback(57)], TODAY) is None


def test_only_the_last_eight_ratios_contribute():
    rows = [feedback(offset, to_qty="36") for offset in (18, 17)]
    rows += [feedback(offset, to_qty="20") for offset in range(16, 8, -1)]
    fact = correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY)

    assert fact is not None
    assert fact["evidence"]["rows"] == 8
    assert fact["evidence"]["from"] == when(16).isoformat()
    assert fact["value"] == pytest.approx(0.5)


def test_removal_counts_as_zero_ratio():
    rows = [feedback(offset, kind="line_removed", to_qty="0") for offset in (10, 9, 8)]
    fact = correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY)

    assert fact is not None
    assert fact["raw_value"] == 0
    assert fact["value"] == pytest.approx(0.3)
    assert fact["applicable"] is False


def test_declined_after_three_qualifying_removals():
    rows = [feedback(offset, kind="line_removed", reason="TOO_MUCH") for offset in (10, 9, 8)]
    fact = declined_product_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY)

    assert fact is not None
    assert fact["kind"] == "DECLINED_PRODUCT"
    assert fact["value"] == 1
    assert fact["evidence"]["rows"] == 3


def test_an_addition_resets_decline_history():
    old = [feedback(offset, kind="line_removed") for offset in (12, 11, 10)]
    addition = feedback(9, kind="line_added")
    after = [feedback(offset, kind="line_removed") for offset in (8, 7)]
    assert declined_product_fact(KITCHEN, PRODUCT, "Washed potato", old + [addition] + after,
                                 TODAY) is None

    after.append(feedback(6, kind="line_removed"))
    fact = declined_product_fact(KITCHEN, PRODUCT, "Washed potato", old + [addition] + after,
                                 TODAY)
    assert fact is not None
    assert fact["evidence"]["rows"] == 3
    assert fact["evidence"]["from"] == when(8).isoformat()


def test_in_stock_removals_do_not_decline():
    rows = [feedback(offset, kind="line_removed", reason="IN_STOCK") for offset in (10, 9, 8)]
    assert declined_product_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY) is None


def test_late_example_uses_positive_days_only():
    observations = [
        delivery("o1", days_late=1, offset=10),
        delivery("o2", days_late=1, offset=9),
        delivery("o3", days_late=1, offset=8),
        delivery("o4", days_late=0, offset=7),
        delivery("o5", days_late=0, offset=6),
    ]
    facts = supplier_facts(KITCHEN, SUPPLIER, "Supplier", observations, TODAY)
    late = next(fact for fact in facts if fact["kind"] == "SUPPLIER_LATE")

    assert late["on_time_rate"] == pytest.approx(0.4)
    assert late["mean_days_late"] == pytest.approx(1)
    assert late["value"] == pytest.approx(1)
    assert late["deliveries"] == 5
    assert late["evidence"]["rows"] == 5


def test_early_deliveries_do_not_reduce_lateness():
    observations = [
        delivery(f"o{index}", days_late=days_late, offset=10 - index)
        for index, days_late in enumerate((-5, 0, 0, 0, 1))
    ]
    facts = supplier_facts(KITCHEN, SUPPLIER, "Supplier", observations, TODAY)
    late = next(fact for fact in facts if fact["kind"] == "SUPPLIER_LATE")

    assert late["on_time_rate"] == pytest.approx(0.8)
    assert late["mean_days_late"] == pytest.approx(1)


def test_unknown_dates_are_excluded_from_their_statistics():
    observations = [delivery(f"o{index}", days_late=0, offset=10 - index) for index in range(5)]
    observations.append(delivery("unknown", days_late=None, has_delivery_date=False,
                                 has_ordered_at=False, checked_offset=1))
    facts = supplier_facts(KITCHEN, SUPPLIER, "Supplier", observations, TODAY)
    late = next(fact for fact in facts if fact["kind"] == "SUPPLIER_LATE")

    assert late["deliveries"] == 6
    assert late["on_time_rate"] == pytest.approx(1)
    assert late["mean_lead_time"] == pytest.approx(2)
    assert late["sigma_lead_time"] == pytest.approx(0)


def test_negative_lead_times_are_excluded_not_clamped():
    observations = [delivery(f"o{index}", days_late=0, offset=10 - index)
                    for index in range(4)]
    observations.append(delivery("backwards", days_late=0, offset=5, ordered_before=-2))
    facts = supplier_facts(KITCHEN, SUPPLIER, "Supplier", observations, TODAY)
    late = next(fact for fact in facts if fact["kind"] == "SUPPLIER_LATE")

    assert late["mean_lead_time"] == pytest.approx(2)
    assert late["sigma_lead_time"] == pytest.approx(0)


def test_fewer_than_five_deliveries_makes_no_supplier_facts():
    observations = [delivery(f"o{index}", offset=10 - index) for index in range(4)]
    assert supplier_facts(KITCHEN, SUPPLIER, "Supplier", observations, TODAY) == []


def test_mixed_supplier_order_counts_once_and_skips_the_other_supplier():
    mixed_lines = [
        {"supplier_id": SUPPLIER, "ordered": "10", "delivered": "5", "unit": "KG"},
        {"supplier_id": SUPPLIER, "ordered": "10", "delivered": "10", "unit": "KG"},
        {"supplier_id": "supplier-2", "ordered": "100", "delivered": "0", "unit": "KG"},
    ]
    observations = [delivery(f"o{index}", offset=10 - index) for index in range(4)]
    observations.append(delivery("mixed", supplier=None, offset=5, lines=mixed_lines))
    facts = supplier_facts(KITCHEN, SUPPLIER, "Supplier", observations, TODAY)
    late = next(fact for fact in facts if fact["kind"] == "SUPPLIER_LATE")
    short = next(fact for fact in facts if fact["kind"] == "SUPPLIER_SHORT")

    assert late["deliveries"] == 5
    assert late["evidence"]["rows"] == 5
    assert short["value"] == pytest.approx(0.75)
    assert short["fill_rate"] == pytest.approx(0.75)


def test_fill_rate_skips_unknown_and_unit_mismatch_lines():
    lines = [
        {"supplier_id": SUPPLIER, "ordered": "10", "delivered": "5", "unit": "KG"},
        {"supplier_id": SUPPLIER, "ordered": "10", "delivered": "10",
         "ordered_unit": "KG", "delivered_unit": "ST"},
        {"supplier_id": SUPPLIER, "ordered": "5", "delivered": None, "unit": "KG"},
    ]
    observations = [delivery("o1", offset=10, lines=lines)]
    observations += [delivery(f"o{index}", offset=10 - index) for index in range(2, 6)]
    facts = supplier_facts(KITCHEN, SUPPLIER, "Supplier", observations, TODAY)
    short = next(fact for fact in facts if fact["kind"] == "SUPPLIER_SHORT")

    assert short["value"] == pytest.approx(0.5)


def test_fact_id_depends_on_sorted_evidence_and_not_time():
    first = fact_id(KITCHEN, "CORRECTION_RATIO", PRODUCT, "v1", ["fb-2", "fb-1"])
    same = fact_id(KITCHEN, "CORRECTION_RATIO", PRODUCT, "v1", ["fb-1", "fb-2"])
    newer = fact_id(KITCHEN, "CORRECTION_RATIO", PRODUCT, "v1", ["fb-1", "fb-2", "fb-3"])

    assert first.startswith("lf_")
    assert first == same
    assert first != newer
    assert first != fact_id(KITCHEN, "DECLINED_PRODUCT", PRODUCT, "v1", ["fb-1", "fb-2"])


def test_apply_ratio_uses_decimal_quantities_and_reports_the_plan_fields():
    rows = [feedback(offset) for offset in (10, 9, 8)]
    fact = correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY)
    adjusted, info = apply_ratio("40", fact)

    assert adjusted == Decimal("20")
    assert info == {
        "fact_id": fact["id"],
        "from_qty": "40",
        "to_qty": "20",
        "ratio": pytest.approx(0.5),
        "evidence": fact["evidence"],
    }
    assert "unit" not in info


def test_apply_ratio_requires_an_active_applicable_correction():
    rows = [feedback(offset) for offset in (10, 9, 8)]
    fact = correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY)

    assert apply_ratio("40", {**fact, "active": False}) == (Decimal("40"), None)
    assert apply_ratio("40", {**fact, "kind": "DECLINED_PRODUCT"}) == (Decimal("40"), None)

    low_rows = [feedback(offset, to_qty="8") for offset in (10, 9, 8)]
    low = correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", low_rows, TODAY)
    assert apply_ratio("40", low) == (Decimal("40"), None)


def test_fact_numbers_are_finite():
    rows = [feedback(offset) for offset in (10, 9, 8)]
    fact = correction_ratio_fact(KITCHEN, PRODUCT, "Washed potato", rows, TODAY)
    observations = [delivery(f"o{index}", days_late=1, offset=10 - index) for index in range(5)]
    supplier = supplier_facts(KITCHEN, SUPPLIER, "Supplier", observations, TODAY)

    for number in (fact["value"], fact["raw_value"]):
        assert math.isfinite(number)
    for supplier_fact in supplier:
        for key in ("value", "on_time_rate", "mean_days_late", "mean_lead_time",
                    "sigma_lead_time", "fill_rate"):
            if key in supplier_fact:
                assert math.isfinite(supplier_fact[key])


def test_since_is_the_evidence_versions_first_day_not_today():
    """The same evidence must give the same fact on every day it is read (contract)."""
    from datetime import date
    from engine.learning import correction_ratio_fact
    rows = [{"kind": "qty_changed", "product_id": "p", "kitchen_id": "k", "from_qty": "40", "to_qty": "20",
             "reason": "TOO_MUCH", "approved": True, "ts": f"2026-11-0{d}T10:00:00Z", "feedback_id": f"f{d}",
             "context": {"forecast_need": "40"}, "outcome": {"ran_out": None}} for d in (2, 5, 9)]
    a = correction_ratio_fact("k", "p", "Potato", rows, date(2026, 11, 14))
    b = correction_ratio_fact("k", "p", "Potato", rows, date(2026, 11, 20))
    assert a == b and a["since"] == "2026-11-09"
