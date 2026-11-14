import pytest

from engine.newsvendor import (cost_over, critical_ratio, demand_quantile, interval, order_up_to, why)


def test_critical_ratio_follows_the_costs_and_stays_in_bounds():
    assert critical_ratio(9, 1) == pytest.approx(0.9)
    assert critical_ratio(1, 9) == 0.50            # never plan to run out on purpose
    assert critical_ratio(1000, 0.001) == 0.995    # never chase 100%
    assert critical_ratio(0, 0) == 0.50
    with pytest.raises(ValueError):
        critical_ratio(-1, 1)


def test_a_unit_that_expires_costs_all_of_itself_one_that_keeps_costs_little():
    assert cost_over(2.0, period_days=3, shelf_life_days=2) == 2.0
    assert cost_over(2.0, period_days=3, shelf_life_days=60) < 0.2


def test_cheap_critical_milk_orders_high_expensive_garnish_orders_near_forecast():
    milk, cr_milk = order_up_to(100, cost_short=20, cost_over_unit=0.1)
    herb, cr_herb = order_up_to(100, cost_short=1, cost_over_unit=3)
    assert cr_milk > 0.99 and cr_herb == 0.50
    assert milk > 130 and herb == pytest.approx(100)


def test_shelf_cap_limits_the_target():
    target, _ = order_up_to(100, cost_short=20, cost_over_unit=0.1, shelf_cap=110)
    assert target == 110


def test_own_forecast_errors_are_used_when_there_are_enough():
    ratios = [0.8] * 10 + [1.0] * 10 + [1.5] * 5      # a kitchen that is sometimes far too low
    assert demand_quantile(100, 0.95, ratios=ratios) == pytest.approx(150)
    assert demand_quantile(100, 0.95, ratios=ratios[:5]) == pytest.approx(124.67, abs=0.1)  # normal fallback


def test_interval_and_why():
    band = interval(100, cv=0.15)
    assert band["p10"] < band["p50"] == 100 < band["p90"]
    assert "97% demand level" in why("Milk", 0.97, 20.0, 0.62)
