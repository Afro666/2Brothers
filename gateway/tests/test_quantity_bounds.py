"""Reject pathological quantities before quotes, planning or persistence."""
from unittest.mock import Mock

import pytest

from gateway.service import Gateway, GatewayError
from gateway.tests.test_gateway_app import env  # noqa: F401


@pytest.mark.parametrize('quantity', ['1e50000000', '1000000.000000001', 'NaN', 'Infinity', '-Infinity', '0', '-1', '1e-50000000'])
@pytest.mark.parametrize('path', ['single', 'basket', 'need'])
def test_invalid_quantity_stops_before_side_effects(env, monkeypatch, quantity, path):
    _, _, db = env
    gateway = Gateway(db, None)
    sentinel = Mock(side_effect=AssertionError('quantity reached downstream work'))
    monkeypatch.setattr(gateway, '_offers', sentinel)
    monkeypatch.setattr(db.needs, 'insert_one', sentinel)
    request = {'quantity': quantity, 'unit': 'L', 'requested_date': '2026-11-20',
               'product_ids': ['462775'], 'product_id': '462775'}
    with pytest.raises(GatewayError) as error:
        if path == 'single':
            gateway._plan_one('demo-kitchen', request)
        elif path == 'basket':
            gateway._basket('demo-kitchen', {**request, 'needs': [request]})
        else:
            gateway.create_need('demo-kitchen', request, 'chef')
    assert error.value.code == 'INVALID_REQUEST'
    if path == 'basket':
        assert error.value.message.startswith('462775: quantity ')
    sentinel.assert_not_called()


@pytest.mark.parametrize('quantity', ['1000000', '999999.999999999', '0.000000001'])
def test_valid_quantity_boundaries_can_be_stored(env, quantity):
    _, _, db = env
    result = Gateway(db, None).create_need('demo-kitchen', {
        'quantity': quantity, 'unit': 'L', 'requested_date': '2026-11-20'}, 'chef')
    assert result['quantity'] == quantity
    assert db.needs.count_documents({}) == 1
