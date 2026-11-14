import pytest

from env.quantities import forecast_quantity


@pytest.mark.parametrize('unit', ['PCS', 'ST', 'pcs', 'st'])
def test_counted_forecast_needs_whole_pieces(unit):
    assert forecast_quantity(0, unit) == 0
    assert forecast_quantity(1, unit) == 1
    assert forecast_quantity(1.01, unit) == 2
    assert forecast_quantity(6024.083, unit) == 6025
    assert forecast_quantity(3.0000000000000004, unit) == 3
    assert forecast_quantity(3.0001, unit) == 4


@pytest.mark.parametrize('unit', ['KG', 'L'])
def test_measured_forecasts_keep_their_precision(unit):
    assert forecast_quantity(1.23456, unit) == 1.235
    assert forecast_quantity(0, unit) == 0
