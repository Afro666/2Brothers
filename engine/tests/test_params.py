"""KitchenParams.from_dict enforces the kitchen settings rules of docs/contract.md (#348)."""

from decimal import Decimal

import pytest

from engine.params import KitchenParams


def test_valid_settings_load():
    p = KitchenParams.from_dict({"service_level": {"A": "0.99"}, "max_cover_days": {"dry": 14},
                                 "stockout_cap": "3"})
    assert p.service_level["A"] == Decimal("0.99")
    assert p.service_level["B"] == Decimal("0.95")
    assert p.max_cover_days["dry"] == 14
    assert p.stockout_cap == 3.0


@pytest.mark.parametrize("level", ["97.5", "0", "1", "-0.5"])
def test_service_level_outside_zero_one_is_refused(level):
    with pytest.raises(ValueError, match="service_level"):
        KitchenParams.from_dict({"service_level": {"A": level}})


def test_unknown_cover_category_is_refused():
    with pytest.raises(ValueError, match="Dairy"):
        KitchenParams.from_dict({"max_cover_days": {"Dairy": 4}})


def test_cover_days_below_one_is_refused():
    with pytest.raises(ValueError, match="at least 1"):
        KitchenParams.from_dict({"max_cover_days": {"meat": 0}})


@pytest.mark.parametrize("cap", [0.5, 3.5])
def test_stockout_cap_outside_one_to_three_is_refused(cap):
    with pytest.raises(ValueError, match="stockout_cap"):
        KitchenParams.from_dict({"stockout_cap": cap})
