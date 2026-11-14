"""Webhooks (#277): signed deliveries, subscriptions, retries, SSRF guard, approver only."""

import hashlib
import hmac
import json

import pytest

from gateway import users, webhooks
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env, milk  # noqa: F401 (fixture)
from gateway.tests.test_users import people, sign_in

URL = "https://hooks.example.com/tkb"


class Receiver:
    """A local stand-in for the developer's server: keeps what it got, answers `status`."""

    def __init__(self, status=200):
        self.status, self.calls = status, []

    def __call__(self, url, body, headers):
        self.calls.append({"url": url, "body": body, "headers": headers})
        if isinstance(self.status, Exception):
            raise self.status
        return self.status

    def events(self):
        return [c["headers"]["X-TKB-Event"] for c in self.calls]


@pytest.fixture()
def receiver(monkeypatch):
    """No network and no thread in tests: the real sender and the runner are replaced."""
    r = Receiver()
    monkeypatch.setattr(webhooks, "http_send", r)
    monkeypatch.setattr(webhooks, "run_async", lambda job: job())
    monkeypatch.setattr(webhooks, "BACKOFF", (0, 0))
    return r


def make(client, events, url=URL):
    r = client.post(K + "/webhooks", headers=HUMAN, json={"url": url, "events": events})
    assert r.status_code == 200, r.text
    return r.json()


def approve(client, p, key="a1"):
    return client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                       json={"expected_total": p["expected_total"], "idempotency_key": key})


def test_secret_is_shown_once_and_the_signature_verifies(env, receiver):
    client, _, _ = env
    hook = make(client, ["proposal.ready"])
    assert hook["secret"].startswith("whsec_")
    listed = client.get(K + "/webhooks", headers=HUMAN).json()
    assert listed["webhooks"][0]["url"] == URL and "secret" not in listed["webhooks"][0]
    assert "order.placed" in listed["events"]
    p = milk(client)
    assert receiver.events() == ["proposal.ready"]
    call = receiver.calls[0]
    expected = "sha256=" + hmac.new(hook["secret"].encode(), call["body"], hashlib.sha256).hexdigest()
    assert call["headers"]["X-TKB-Signature"] == expected
    assert call["headers"]["X-TKB-Signature"] != webhooks.sign("another-secret", call["body"])
    sent = json.loads(call["body"])
    assert sent["event"] == "proposal.ready" and sent["kitchen_id"] == "demo-kitchen"
    assert sent["data"]["proposal_id"] == p["proposal_id"] and sent["id"] == call["headers"]["X-TKB-Delivery"]


def test_only_subscribed_events_are_sent(env, receiver):
    client, _, _ = env
    make(client, ["order.placed", "proposal.rejected"])
    p = milk(client)
    assert receiver.calls == []                       # proposal.ready: not subscribed
    assert approve(client, p).status_code == 200
    assert receiver.events() == ["order.placed"]      # proposal.approved: not subscribed
    q = milk(client, key="p2")
    assert client.post(f"{K}/proposals/{q['proposal_id']}/reject", headers=HUMAN,
                       json={"reason": "too much"}).status_code == 200
    assert receiver.events() == ["order.placed", "proposal.rejected"]


def test_a_second_reject_sends_no_second_rejected_event(env, receiver):
    client, _, _ = env
    make(client, ["proposal.rejected"])
    p = milk(client)
    url = f"{K}/proposals/{p['proposal_id']}/reject"
    assert client.post(url, headers=HUMAN, json={"reason": "too much"}).status_code == 200
    assert client.post(url, headers=HUMAN, json={"reason": "too much"}).status_code == 200
    assert receiver.events() == ["proposal.rejected"]


def test_approve_sends_approved_and_placed_and_a_moved_price_sends_total_mismatch(env, receiver):
    client, fake, _ = env
    make(client, list(webhooks.EVENTS))
    p = milk(client)
    # 3.57 is 2.55 times the cheapest milk: inside the certainty premium limit (engine/premium.py),
    # so the basket keeps its product and only the total moves.
    fake.bump("462775", 3.57)
    assert approve(client, p).status_code == 409
    assert receiver.events() == ["proposal.ready", "total_mismatch"]
    fresh = client.get(f"{K}/proposals/{p['proposal_id']}", headers=HUMAN).json()
    assert approve(client, fresh, key="a2").status_code == 200
    assert receiver.events()[2:] == ["proposal.approved", "order.placed"]


def test_a_failing_receiver_is_tried_three_times_and_logged_without_a_body(env, receiver):
    client, _, db = env
    hook = make(client, ["proposal.ready"])
    receiver.status = 500
    milk(client)
    assert len(receiver.calls) == 3
    assert len({c["body"] for c in receiver.calls}) == 1          # the same signed body each time
    log = client.get(f"{K}/webhooks/{hook['webhook_id']}/deliveries", headers=HUMAN).json()["deliveries"]
    assert [(d["event"], d["attempts"], d["status"], d["ok"]) for d in log] == [("proposal.ready", 3, 500, False)]
    stored = db.webhook_deliveries.find_one({})
    assert "body" not in stored and "proposal_id" not in str(stored) and hook["secret"] not in str(stored)


def test_a_receiver_that_recovers_stops_the_retries(env, receiver):
    client, _, _ = env
    hook = make(client, ["proposal.ready"])
    answers = iter([ConnectionError("down"), 204])

    def flaky(url, body, headers):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    rows = webhooks.deliver(env[2], "demo-kitchen", "proposal.ready", {"x": 1}, send=flaky, sleep=lambda s: None)
    assert [(r["attempts"], r["status"], r["ok"], r["error"]) for r in rows] == [(2, 204, True, None)]
    assert client.get(f"{K}/webhooks/{hook['webhook_id']}/deliveries", headers=HUMAN).json()["deliveries"][0]["ok"]


def test_a_webhook_failure_does_not_fail_approve(env, receiver):
    client, _, db = env
    hook = make(client, ["proposal.approved", "order.placed"])
    receiver.status = TimeoutError("receiver is down")
    p = milk(client)
    r = approve(client, p)
    assert r.status_code == 200 and r.json()["status"] == "SENT", r.text
    assert len(receiver.calls) == 6                               # 2 events, 3 attempts each
    log = client.get(f"{K}/webhooks/{hook['webhook_id']}/deliveries", headers=HUMAN).json()["deliveries"]
    assert {(d["status"], d["error"], d["ok"]) for d in log} == {(None, "TimeoutError", False)}
    # Even a broken webhook store cannot break the order path.
    db.webhooks.drop()
    assert webhooks.deliver(None, "demo-kitchen", "order.placed", {}) == []
    webhooks.dispatch(None, "demo-kitchen", "order_placed", {})


def test_delivery_runs_in_a_background_thread(env, monkeypatch):
    client, _, _ = env
    jobs = []
    monkeypatch.setattr(webhooks, "run_async", jobs.append)
    monkeypatch.setattr(webhooks, "http_send", lambda *a: pytest.fail("sent inside the request"))
    make(client, ["proposal.ready"])
    milk(client)
    assert len(jobs) == 1                                         # queued, not run by the request


@pytest.mark.parametrize("url", [
    "http://hooks.example.com/x", "ftp://hooks.example.com/x", "https://localhost/x",
    "http://localhost:9000/x", "http://127.0.0.1:9000/x", "https://127.0.0.1/x", "https://10.0.0.5/x",
    "https://192.168.1.10/x", "https://172.16.0.1/x", "https://169.254.169.254/latest/meta-data",
    "https://[::1]/x", "https://[fd00::1]/x", "https://[::ffff:10.0.0.1]/x", "https://0.0.0.0/x",
    "https://intranet/x", "https://db.internal/x", "https://printer.local/x", "https://2130706433/x",
    "https://0x7f.0.0.1/x", "https://user:pw@hooks.example.com/x", "https:///x", "", None, 42,
])
def test_non_https_private_and_internal_urls_are_refused(env, url):
    client, _, _ = env
    r = client.post(K + "/webhooks", headers=HUMAN, json={"url": url, "events": ["order.placed"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST", (url, r.text)


def test_localhost_is_allowed_only_with_the_dev_switch(env, monkeypatch):
    client, _, _ = env
    monkeypatch.setenv("GATEWAY_WEBHOOKS_DEV", "true")
    assert make(client, ["order.placed"], "http://localhost:9000/hook")["url"].startswith("http://localhost")
    make(client, ["order.placed"], "http://127.0.0.1:9000/hook")
    r = client.post(K + "/webhooks", headers=HUMAN, json={"url": "http://10.0.0.5/x", "events": ["order.placed"]})
    assert r.status_code == 422


def test_the_real_sender_refuses_a_host_that_resolves_to_a_private_address(monkeypatch):
    monkeypatch.setattr(webhooks.socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))])
    with pytest.raises(webhooks.WebhookError):
        webhooks.http_send("https://rebind.example.com/x", b"{}", {})


def test_events_are_checked_and_ten_hooks_is_the_limit(env):
    client, _, _ = env
    for bad in (["nope"], [], None, "order.placed", ["ping"], [1]):
        r = client.post(K + "/webhooks", headers=HUMAN, json={"url": URL, "events": bad})
        assert r.status_code == 422, bad
    for _ in range(10):
        make(client, ["order.placed"])
    r = client.post(K + "/webhooks", headers=HUMAN, json={"url": URL, "events": ["order.placed"]})
    assert r.status_code == 422 and "at most 10" in r.json()["error"]["message"]


def test_test_route_sends_one_signed_ping(env, receiver):
    client, _, _ = env
    hook = make(client, ["order.placed"])
    r = client.post(f"{K}/webhooks/{hook['webhook_id']}/test", headers=HUMAN)
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["event"] == "ping", r.text
    call = receiver.calls[0]
    assert call["headers"]["X-TKB-Event"] == "ping"
    assert call["headers"]["X-TKB-Signature"] == webhooks.sign(hook["secret"], call["body"])
    receiver.status = 503
    r = client.post(f"{K}/webhooks/{hook['webhook_id']}/test", headers=HUMAN)
    assert r.json()["ok"] is False and r.json()["attempts"] == 1 and r.json()["status"] == 503
    assert client.post(f"{K}/webhooks/nope/test", headers=HUMAN).status_code == 404
    assert client.get(f"{K}/webhooks/nope/deliveries", headers=HUMAN).status_code == 404


def test_create_and_delete_are_audited_and_delete_stops_deliveries(env, receiver):
    client, _, db = env
    hook = make(client, ["proposal.ready"])
    assert client.delete(f"{K}/webhooks/{hook['webhook_id']}", headers=HUMAN).status_code == 200
    events = client.get(K + "/audit", headers=HUMAN).json()["events"]
    assert [e["kind"] for e in events] == ["webhook_created", "webhook_deleted"]
    assert hook["secret"] not in json.dumps(events)
    milk(client)
    assert receiver.calls == [] and db.webhooks.count_documents({}) == 0
    assert client.delete(f"{K}/webhooks/{hook['webhook_id']}", headers=HUMAN).status_code == 404


def test_only_an_approver_manages_webhooks(env, receiver):
    client, _, db = env
    hook = make(client, ["order.placed"])
    one = f"{K}/webhooks/{hook['webhook_id']}"
    new = {"url": URL, "events": ["order.placed"]}

    def all_refused(headers):
        return [client.post(K + "/webhooks", headers=headers, json=new).status_code,
                client.get(K + "/webhooks", headers=headers).status_code,
                client.post(one + "/test", headers=headers).status_code,
                client.get(one + "/deliveries", headers=headers).status_code,
                client.delete(one, headers=headers).status_code] == [403] * 5

    assert all_refused(AGENT)
    people(db)
    for email in ("chef@example.com", "view@example.com"):
        sign_in(client, email)
        assert all_refused(None), email
    users.create_user(db, "other@example.com", "correct horse 42", name="Other", role="approver",
                      kitchen_id="other-kitchen")
    sign_in(client, "other@example.com")
    assert all_refused(None)                           # an approver of another kitchen
    assert receiver.calls == []
    sign_in(client, "aron@example.com")
    assert client.get(K + "/webhooks").json()["webhooks"][0]["webhook_id"] == hook["webhook_id"]
