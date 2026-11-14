import pytest
from monitor.enrichment import evidence, SOURCE


def test_recorded_second_context_call_preserves_unknown_allergens():
    row = evidence()
    assert row['product_id'] == '475842'
    assert row['pack'] == '500g'
    assert 'Brazil' in row['origin']
    assert row['allergens'] is None
    assert row['source_url'] == SOURCE
    assert row['request_id']


def test_live_is_opt_in_and_identity_mismatch_is_refused():
    class Wrong:
        def scrape_json(self, url, schema):
            assert url == SOURCE and 'allergens' in schema['properties']
            return {'name': 'Different product', 'brand': 'Other', 'allergens': None}
    assert evidence(client=Wrong())['name'] == 'Crescendo'  # no call by default
    with pytest.raises(ValueError, match='identity'):
        evidence(live=True, client=Wrong())
