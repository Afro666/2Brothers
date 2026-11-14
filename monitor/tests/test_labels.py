from copy import deepcopy
from datetime import datetime, timezone
import pytest
from monitor.labels import verify, LABEL, recording

NOW = datetime(2026, 11, 14, 2, tzinfo=timezone.utc)


@pytest.mark.parametrize('pid', ['462535', '462576', '462775'])
def test_three_catalog_claims_verify_exact_registered_producer(pid):
    result = verify({'product_id': pid, 'vendor': 'ARLA OY'}, LABEL, now=NOW)
    assert result['label_verified'] is True
    assert result['scope'] == 'producer'
    assert result['source_url'].startswith('https://ruokatieto.fi/')
    assert 'SKU certification is unverified' in result['reason']


def test_negative_control_is_not_found_and_brand_is_not_producer():
    assert verify({'vendor': 'Synthetic Unregistered Demo Producer Oy'}, LABEL, now=NOW)['label_verified'] == 'not_found'
    assert verify({'brand': 'Arla'}, LABEL, now=NOW)['label_verified'] == 'unknown'
    assert verify({'vendor': 'Arla'}, LABEL, now=NOW)['label_verified'] == 'not_found'


@pytest.mark.parametrize('change', [{'complete': False}, {'producers': ['Arla Oy']}, {'register_date': '2025-01-01'},
    {'checked_at': '2099-01-01T00:00:00Z'}, {'source_url': 'https://example.com'}])
def test_partial_stale_or_untrusted_data_never_verifies(change):
    register = {**deepcopy(recording()), **change}
    assert verify({'vendor': 'Arla Oy'}, LABEL, register=register, now=NOW)['label_verified'] == 'unknown'


def test_unsupported_scheme_is_unknown():
    assert verify({'vendor': 'Arla Oy'}, 'EU_ORGANIC', now=NOW)['label_verified'] == 'unknown'
