import asyncio
import json

import httpx
import pytest

from agent.model import Nemotron, provider_settings
from agent.ping import check


def test_operator_can_correct_the_endpoint_and_model_without_changing_the_key():
    base, model, key = provider_settings({'NEMOTRON_BASE_URL': 'https://nemotron.example/v1',
                                          'NEMOTRON_MODEL': 'nemotron-serving-alias', 'VERDA_INFERENCE_KEY': 'private-verda'})
    assert (base, model, key) == ('https://nemotron.example/v1/', 'nemotron-serving-alias', 'private-verda')
    with pytest.raises(ValueError, match='VERDA_INFERENCE_KEY is required'):
        provider_settings({})


@pytest.mark.parametrize('url', ['http://public.example/v1', 'https://user:secret@example.test/v1',
                                 'https://example.test/v1?key=private', 'https://example.test/v1#private'])
def test_invalid_endpoint_never_opens_a_client(url, monkeypatch):
    monkeypatch.setenv('VERDA_INFERENCE_KEY', 'private-key')
    monkeypatch.setenv('NEMOTRON_BASE_URL', url)
    with pytest.raises(ValueError, match='HTTPS base URL'):
        Nemotron()


def test_ping_uses_real_chat_with_tiny_budget_and_no_content_logging(monkeypatch):
    monkeypatch.setenv('VERDA_INFERENCE_KEY', 'private-key')
    monkeypatch.setenv('NEMOTRON_BASE_URL', 'https://endpoint.example/v1')
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'private-key'}}],
                                        'usage': {'prompt_tokens': 5, 'completion_tokens': 1}})
    result = asyncio.run(check(transport=httpx.MockTransport(reply)))
    assert result['status'] == 'OK' and result['endpoint_host'] == 'endpoint.example'
    assert 'private-key' not in json.dumps(result)
    assert result['usage']['calls'] == 1
    assert len(requests) == 1 and requests[0].url.path == '/v1/chat/completions'
    assert json.loads(requests[0].content)['max_tokens'] == 16


def test_ping_does_not_retry_errors_or_expose_their_contents(monkeypatch):
    monkeypatch.setenv('VERDA_INFERENCE_KEY', 'private-key')
    requests = []
    def unavailable(request):
        requests.append(request)
        return httpx.Response(503, text='private-key upstream details')
    result = asyncio.run(check(transport=httpx.MockTransport(unavailable)))
    assert result['status'] == 'ERROR' and result['error'] == 'ModelError'
    assert result['http_status'] == 503
    assert len(requests) == 1 and 'private-key' not in json.dumps(result)


def test_ping_rejects_empty_completion(monkeypatch):
    monkeypatch.setenv('VERDA_INFERENCE_KEY', 'private-key')
    result = asyncio.run(check(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'choices': [{'message': {'content': ''}}]}))))
    assert result['status'] == 'ERROR'
