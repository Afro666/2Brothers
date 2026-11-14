"""Short and waste per kitchen unit, never one sum over kg, l and pieces (#1618)."""
from datetime import date
from decimal import Decimal

from engine.forecast import accuracy, accuracy_by_week

MON, TUE = date(2026, 11, 2), date(2026, 11, 3)
PAIRS = [("milk", MON, 10.0, 12.0), ("milk", TUE, 10.0, 10.0),   # week: 20 vs 22 -> short 2 L
         ("flour", MON, 5.0, 4.0),                               # 5 vs 4 -> waste 1 KG
         ("buns", MON, 100.0, 90.0)]                             # 100 vs 90 -> waste 10 PCS
UNITS = {"milk": "L", "flour": "KG", "buns": "PCS"}


def test_mixed_units_give_no_single_sum_and_one_row_per_unit():
    total = accuracy(PAIRS, units=UNITS, prices={"milk": Decimal("1.40")})
    assert total["under"] is None and total["over"] is None
    rows = {row["unit"]: row for row in total["by_unit"]}
    assert [row["unit"] for row in total["by_unit"]] == ["KG", "L", "PCS"]
    assert rows["L"]["under"] == 2.0 and rows["L"]["over"] == 0.0 and rows["L"]["series"] == 1
    assert rows["KG"]["over"] == 1.0 and rows["PCS"]["over"] == 10.0
    # Only milk has a price: its short is valued, the rest is counted as unpriced.
    assert rows["L"]["under_eur"] == "2.80" and rows["L"]["over_eur"] == "0.00"
    assert rows["KG"]["under_eur"] is None and rows["PCS"]["over_eur"] is None
    assert total["under_eur"] == "2.80" and total["over_eur"] == "0.00"
    assert total["unpriced_series"] == 2


def test_one_unit_keeps_the_sums():
    total = accuracy([p for p in PAIRS if p[0] == "milk"], units=UNITS)
    assert total["under"] == 2.0 and total["over"] == 0.0
    assert [row["unit"] for row in total["by_unit"]] == ["L"]
    assert total["under_eur"] is None and total["unpriced_series"] == 1


def test_without_units_the_old_shape_still_holds():
    total = accuracy(PAIRS)
    assert total["under"] == 2.0 and total["over"] == 11.0 and total["series"] == 3


def test_week_rows_carry_the_unit_rows_too():
    (week,) = accuracy_by_week(PAIRS, units=UNITS, prices={"flour": Decimal("1.365")})
    assert week["over"] is None
    assert {row["unit"]: row["over_eur"] for row in week["by_unit"]} == {"KG": "1.37", "L": None, "PCS": None}


def test_empty_pairs():
    total = accuracy([], units={})
    assert total["by_unit"] == [] and total["under_eur"] is None and total["series"] == 0
