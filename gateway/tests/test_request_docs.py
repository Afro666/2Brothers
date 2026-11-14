"""An outside client can discover payloads without reading llms.txt prose."""
import json

from jsonschema import Draft202012Validator
import pytest

from gateway.tests.test_gateway_app import AGENT, K, env  # noqa: F401

PAYLOADS = {
    K.replace('demo-kitchen', '{kitchen_id}') + '/needs':
        {'quantity': '1000', 'unit': 'L', 'requested_date': '2026-11-16'},
    '/tools/search_products': {'query': 'milk', 'filters': {'pack_size': {'value': 1, 'unit': 'L'}}, 'limit': 5},
    '/tools/get_offer': {'product_ids': ['462775'], 'requested_date': '2026-11-16', 'need_id': 'need'},
    '/tools/simulate_order': {'offer_id': 'offer'},
    '/tools/request_approval': {'offer_id': 'offer', 'idempotency_key': 'request'},
    '/tools/place_order': {'offer_id': 'offer', 'expected_total': '10.00', 'idempotency_key': 'place'},
}


@pytest.mark.parametrize('path,payload', PAYLOADS.items())
def test_workflow_request_schema_is_public_and_self_contained(env, path, payload):
    client, *_ = env
    spec = client.get('/openapi.json').json()
    body = spec['paths'][path]['post']['requestBody']
    assert body['required'] is True
    schema = body['content']['application/json']['schema']
    assert '$ref' not in json.dumps(schema)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(payload)
    for required in schema.get('required', []):
        assert not validator.is_valid({k: v for k, v in payload.items() if k != required})


def test_documentation_does_not_change_auth_or_error_envelopes(env):
    client, *_ = env
    unauthenticated = client.post('/tools/get_offer', content='{')
    assert unauthenticated.status_code == 401
    malformed = client.post('/tools/get_offer', headers=AGENT, content='{')
    assert malformed.status_code == 422
    assert malformed.json()['error']['code'] == 'INVALID_JSON'
    missing = client.post('/tools/request_approval', headers=AGENT, json={'offer_id': 'no-offer'})
    assert missing.json()['error']['code'] == 'MISSING_IDEMPOTENCY_KEY'
