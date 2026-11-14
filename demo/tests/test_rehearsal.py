"""The rehearsal check against a fake site: all green, a broken forecast is a FAIL."""

from datetime import date
import json

import httpx

from demo.rehearsal import Rehearsal

TODAY = date(2026, 11, 14)


def site(broken=()):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/":
            return httpx.Response(200, text="<html></html>")
        answers = {
            "/api/ping": {"status": "ok"},
            "/api/v1/kitchens/demo-kitchen/proposals": {"proposals": [
                {"status": "READY", "lines": [{"unknown_stock": False}]}, {"status": "READY", "lines": [{"unknown_stock": True}]}]},
            "/api/v1/kitchens/demo-kitchen/menu-plans/2026-W47": {"days": [{"date": "2026-11-16"}]},
            "/api/v1/kitchens/demo-kitchen/demand": {"rows": [{"product_id": "1", "product_name": "Milk"}]},
            "/api/v1/kitchens/demo-kitchen/stock": {"items": [{"on_hand": "1"}, {"on_hand": None}]},
            "/api/v1/kitchens/demo-kitchen/suppliers": {"suppliers": [{"name": "Valio Aimo"}]},
            "/api/v1/kitchens/demo-kitchen/forecast-accuracy": {"methods": {
                "engine": {"total": {"wape": 0.20 if "forecast" in broken else 0.045}},
                "weekday-average": {"total": {"wape": 0.067}}}},
            "/api/v1/suppliers/sup-valio/demand": {"kitchens_sharing": 16, "rows": [{"risk": "SHORT"}]},
            "/api/v1/kitchens/demo-kitchen/permissions": {"never": [1, 2, 3]},
            "/api/v1/kitchens/demo-kitchen/audit": {"events": [{"at": "x"}]},
            "/api/.well-known/jwks.json": {"keys": [{"alg": "EdDSA"}]},
            "/api/openapi.json": {"paths": {str(i): {} for i in range(30)}},
        }
        if path in answers:
            return httpx.Response(200, json=answers[path])
        return httpx.Response(404, json={})
    return httpx.Client(base_url="https://site.test", transport=httpx.MockTransport(handler))


def test_all_green_and_the_buyer_is_skipped_by_default():
    rows = Rehearsal("https://site.test", client=site(), today=TODAY).run(with_buyer=False)
    status = {name: s for name, s, _ in rows}
    assert [n for n, s in status.items() if s == "FAIL"] == []
    assert status["Buyer makes a proposal"] == "SKIP"
    assert "1 can be approved now" in dict((n, d) for n, _, d in rows)["Approval inbox"]


def test_a_forecast_worse_than_the_baseline_fails():
    rows = Rehearsal("https://site.test", client=site(broken=("forecast",)), today=TODAY).run(with_buyer=False)
    assert {name: s for name, s, _ in rows}["Forecast beats the weekday average"] == "FAIL"


def test_a_dropped_connection_is_tried_once_more():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"status": "ok"})
    check = Rehearsal("https://site.test", client=httpx.Client(base_url="https://site.test", transport=httpx.MockTransport(handler)), today=TODAY)
    check.retry_wait = 0
    check.check("Gateway answers", check.gateway)
    assert check.rows[0][1] == "OK" and calls["n"] == 2


def _buyer_site(first_error):
    posts = []

    def handler(request):
        if request.method == "POST":
            posts.append(request)
            if len(posts) == 1:
                raise first_error
            return httpx.Response(200, json={"status": "READY", "buyer_model": "nemotron", "lines": [{}]})
        return httpx.Response(404, json={})
    return posts, httpx.Client(base_url="https://site.test", transport=httpx.MockTransport(handler))


def test_a_timed_out_buyer_post_is_not_sent_again():
    posts, client = _buyer_site(httpx.ReadTimeout("slow"))
    check = Rehearsal("https://site.test", client=client, today=TODAY)
    check.retry_wait = 0
    rows = check.run(with_buyer=True)
    assert len(posts) == 1
    assert {name: s for name, s, _ in rows}["Buyer makes a proposal"] == "FAIL"


def test_a_retried_buyer_post_keeps_its_idempotency_key():
    posts, client = _buyer_site(httpx.ConnectError("refused"))
    check = Rehearsal("https://site.test", client=client, today=TODAY)
    check.retry_wait = 0
    check.check("Buyer makes a proposal", check.buyer, retry_on=httpx.ConnectError)
    keys = [json.loads(p.content)["idempotency_key"] for p in posts]
    assert len(keys) == 2 and keys[0] == keys[1]
    assert check.rows[0][1] == "OK"
