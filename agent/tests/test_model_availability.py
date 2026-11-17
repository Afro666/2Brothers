import asyncio
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from agent.model import provider_settings
from agent.service import create_app
from gateway.buyer_worker import run_buyer, run_split
from gateway.model_availability import capabilities
from gateway.service import GatewayError


def test_disabled_model_stops_before_opening_any_client(monkeypatch):
    monkeypatch.setenv('NEMOTRON_ENABLED', 'false')
    with pytest.raises(ValueError, match='disabled'):
        provider_settings({'NEMOTRON_ENABLED': 'false', 'VERDA_INFERENCE_KEY': 'fixture-only'})
    async def check():
        with patch('gateway.buyer_worker.httpx.AsyncClient', side_effect=AssertionError('must not connect')):
            assert await run_split('k', '10 L milk') is None
            with pytest.raises(GatewayError) as caught:
                await run_buyer('k', {})
            assert caught.value.code == 'BUYER_UNAVAILABLE'
            assert caught.value.extra['fallback_safe'] is True
    asyncio.run(check())


def test_health_distinguishes_configuration_from_reachability(monkeypatch):
    monkeypatch.setenv('NEMOTRON_ENABLED', 'false')
    monkeypatch.setenv('VERDA_INFERENCE_KEY', 'fixture-only')
    response = TestClient(create_app()).get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok', 'model_enabled': False,
                               'model_configured': False, 'model_reachable': None}
    assert 'fixture-only' not in response.text
    assert capabilities({'VERDA_INFERENCE_KEY': 'fixture-only'})['model_reachable'] is None
