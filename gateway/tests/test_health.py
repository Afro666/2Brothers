"""GET /health (#1188): public, cheap, live or mock Valio, and how the last real call went.
Never a host, key, status code or upstream error text."""
from datetime import datetime, timezone
import json
from urllib.error import HTTPError, URLError

from types import SimpleNamespace

from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.valio_client import ValioClient, ValioError, _transport

NOW = datetime(2026, 11, 14, 13, 40, tzinfo=timezone.utc)


def client_for(valio):
    """/health reads only the gateway's Valio client: a stand-in gateway is enough."""
    return TestClient(create_app(SimpleNamespace(valio=valio)))


def test_before_any_call_the_mode_is_known_and_reachability_is_null():
    body = client_for(ValioClient("secret-test-key", transport=lambda *a: {})).get("/health").json()
    assert body == {"status": "ok", "valio_api": "mock", "valio_reachable": None, "valio_checked_at": None}
    assert ValioClient("secret-test-key").live is True                     # the real transport is live
    assert ValioClient("secret-test-key", transport=_transport).live is True


def test_a_successful_call_makes_valio_reachable_with_its_time():
    valio = ValioClient("secret-test-key", transport=lambda *a: {"ok": True}, now=lambda: NOW, ttl=0)
    valio.ping()
    body = client_for(valio).get("/health").json()
    assert body["valio_reachable"] is True and body["valio_checked_at"] == NOW.isoformat()


def test_a_failed_call_says_unreachable_and_leaks_nothing():
    def down(path, payload, headers):
        raise HTTPError("https://valio-host.example/api/ping", 503, "upstream exploded at valio-host", {}, None)
    valio = ValioClient("secret-test-key", transport=down, now=lambda: NOW, retries=0, ttl=0)
    try:
        valio.ping()
    except ValioError:
        pass
    raw = client_for(valio).get("/health").text
    body = json.loads(raw)
    assert body["valio_reachable"] is False
    for secret in ("secret-test-key", "valio-host", "503", "exploded"):
        assert secret not in raw


def test_health_needs_no_token_and_never_calls_valio():
    calls = []
    valio = ValioClient("secret-test-key", transport=lambda *a: calls.append(a) or {}, ttl=0)
    client = client_for(valio)
    for _ in range(5):
        assert client.get("/health").status_code == 200
    assert calls == []


def _last_call(transport):
    valio = ValioClient("secret-test-key", transport=transport, now=lambda: NOW, retries=0, ttl=0)
    try:
        valio.ping()
    except ValioError:
        pass
    return client_for(valio).get("/health").json()


def test_a_network_error_says_unreachable():
    def down(path, payload, headers):
        raise URLError("no route to valio-host")
    body = _last_call(down)
    assert body["valio_reachable"] is False and body["valio_checked_at"] == NOW.isoformat()


def test_invalid_json_says_reachable_with_its_time():
    def broken(path, payload, headers):
        raise ValueError("Expecting value")
    body = _last_call(broken)
    assert body["valio_reachable"] is True and body["valio_checked_at"] == NOW.isoformat()
