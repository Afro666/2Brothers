"""GET /recalls and POST /recalls/check (#358): thin views over monitor.proposals.

No network: every test replaces the Context.dev client. The default has no key, so a
check answers from the recording and says so.
"""

import json
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("mongomock")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from gateway import recalls_view, tokens, users  # noqa: E402
from gateway.app import create_app  # noqa: E402
from monitor.recalls import LIST_SCHEMA, LIST_URL  # noqa: E402
from monitor.tests.test_proposals import NOTICES, NOW, setup  # noqa: E402
from store.audit import list_events, verify_chain  # noqa: E402

HUMAN = {"Authorization": "Bearer human-test-token", "X-User": "chef"}
AGENT = {"Authorization": "Bearer agent-test-token"}
K = "/v1/kitchens/hotel"
COFFEE, REPLACEMENT = "461332", "475842"


class NoKey:
    def __init__(self):
        raise RuntimeError("CONTEXT_DEV_API_KEY is not set")


def client_class(answer, calls):
    """A Context.dev client that records each call and answers (or raises) `answer`."""
    class Fake:
        def scrape_json(self, url, schema, **options):
            calls.append((url, schema, options))
            if isinstance(answer, Exception):
                raise answer
            return answer
    return Fake


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    monkeypatch.delenv("GATEWAY_REQUIRE_LOGIN", raising=False)
    monkeypatch.delenv("RECALL_CHECK_TIMEOUT_S", raising=False)
    monkeypatch.delenv("RECALL_CHECK_COOLDOWN_S", raising=False)
    monkeypatch.delenv("RECALL_CHECK_LOCK_WAIT_S", raising=False)
    monkeypatch.setattr(recalls_view, "ContextDev", NoKey)
    db, gw, proposal = setup()
    return TestClient(create_app(gw)), db, gw, proposal


def check(client, key="check-1", headers=HUMAN):
    return client.post(K + "/recalls/check", headers=headers, json={"idempotency_key": key})


def kinds(db):
    return [e["event"].get("kind") or e["event"].get("type") for e in list_events(db, kitchen_id="hotel")]


def test_before_any_check_recalls_are_unknown_not_empty(env):
    client, *_ = env
    r = client.get(K + "/recalls", headers=AGENT)
    assert r.status_code == 200, r.text
    assert r.json() == {"last_check": None, "alerts": []}


def test_check_without_a_key_uses_the_recording_and_says_so(env):
    client, db, gw, proposal = env
    r = check(client)
    assert r.status_code == 200, r.text
    out = r.json()
    last = out["last_check"]
    assert last["source"] == "recording" and last["live_error"] == "NO_KEY"
    assert last["checked_at"] == NOW.isoformat() and last["checked_by"] == "chef"
    assert last["notices_scanned"] == len(NOTICES) == 38
    assert last["notices_listed"] is None and last["notices_unread"] is None
    assert last["scanned_since"] == "2026-03-02"
    assert last["fetched_at"] == last["details_fetched_at"] == "2026-11-13T22:17:51+00:00"
    assert "Context.dev" in last["via"]

    [alert] = out["alerts"]
    assert alert["product_id"] == COFFEE and alert["match"] == "possible" and alert["status"] == "active"
    assert alert["type"] == "recall.alert" and alert["kitchen_id"] == "hotel"
    assert alert["recall"]["url"].startswith("https://www.ruokavirasto.fi/") and alert["recall"]["lot"]
    # The exact fields of docs/recall-contract.md, as the proposal carries them, plus the view's.
    on_proposal = gw.get_proposal("hotel", proposal["proposal_id"])["recall_alerts"][0]
    assert {k: v for k, v in alert.items() if k != "proposals"} == on_proposal
    [held] = alert["proposals"]
    assert held["proposal_id"] == proposal["proposal_id"] and held["status"] == "BLOCKED_BY_RECALL"
    assert held["recall_replan_error"] is None
    replacement = held["replacement"]
    assert replacement["proposal_id"] == held["replacement_proposal_id"] != proposal["proposal_id"]
    assert replacement["status"] == "READY" and replacement["currency"] == "EUR"
    assert replacement["expected_total"] == gw.get_proposal("hotel", replacement["proposal_id"])["expected_total"]
    assert replacement["lines"] == [{"product_id": REPLACEMENT, "product_name": "Löfbergs coffee",
                                     "quantity": "5", "unit": "ST"}]

    assert client.get(K + "/recalls", headers=AGENT).json() == out
    assert db.orders.count_documents({}) == 0          # a check never orders
    approve = client.post(f"{K}/proposals/{proposal['proposal_id']}/approve", headers=HUMAN,
                          json={"expected_total": proposal["expected_total"], "idempotency_key": "a"})
    assert approve.status_code == 409 and approve.json()["error"]["code"] == "BLOCKED_BY_RECALL"
    seen = kinds(db)
    assert seen.count("recall_check") == 1 and "recall.alert" in seen
    assert "recall_proposal_blocked" in seen and "recall_replacement_proposed" in seen
    assert verify_chain(db)["ok"]


def test_recall_check_audit_entry_names_source_and_alerts(env):
    client, db, *_ = env
    out = check(client).json()
    [entry] = [e for e in list_events(db, kitchen_id="hotel") if e["event"].get("kind") == "recall_check"]
    event = entry["event"]
    assert event["actor"] == "chef" and event["source"] == "recording" and event["live_error"] == "NO_KEY"
    assert event["notices_scanned"] == 38 and event["alerts"] == [out["alerts"][0]["event_id"]]
    assert entry["server"]["at"] == NOW.isoformat()


def test_repeat_key_scrapes_nothing_and_applies_nothing(env, monkeypatch):
    client, db, *_ = env
    calls = []
    listing = {"recalls": [{"url": n["url"], "title": n["title"], "date": n["date"]} for n in NOTICES]}
    monkeypatch.setattr(recalls_view, "ContextDev", client_class(listing, calls))
    first = check(client, "same").json()
    events, proposals = len(list_events(db, kitchen_id="hotel")), db.proposals.count_documents({})
    again = check(client, "same")
    assert again.status_code == 200 and again.json() == first
    assert len(calls) == 1
    assert len(list_events(db, kitchen_id="hotel")) == events
    assert db.proposals.count_documents({}) == proposals


def test_new_key_checks_again_but_plans_no_second_replacement(env, monkeypatch):
    client, db, *_ = env
    monkeypatch.setenv("RECALL_CHECK_COOLDOWN_S", "0")      # the clock stands still here (#652)
    check(client, "one")
    check(client, "two")
    assert kinds(db).count("recall_check") == 2
    assert db.proposals.count_documents({}) == 2      # the held one and one replacement
    assert kinds(db).count("recall_replacement_proposed") == 1


def test_live_list_is_one_call_and_unread_notices_are_counted(env, monkeypatch):
    client, *_ = env
    calls = []
    listing = {"recalls": [{"url": n["url"].rstrip("/"), "title": n["title"], "date": n["date"]} for n in NOTICES]
               + [{"url": "https://www.ruokavirasto.fi/takaisinvedot/uusi-1/", "title": "Uusi", "date": "2026-11-13"},
                  {"url": "/takaisinvedot/uusi-2/", "title": "Uusi 2"},                    # no date: may be new
                  {"url": "/takaisinvedot/vanha/", "title": "Vanha", "date": "2025-12-01"},   # before the recording
                  {"url": "/takaisinvedot/vanha-2/", "title": "Vanha", "date": "1. helmikuuta 2026"}]}
    monkeypatch.setattr(recalls_view, "ContextDev", client_class(listing, calls))
    last = check(client).json()["last_check"]
    assert last["source"] == "live" and last["live_error"] is None
    assert last["fetched_at"] == NOW.isoformat()                          # the list: now
    assert last["details_fetched_at"] == "2026-11-13T22:17:51+00:00"      # the pages: the recording
    assert last["notices_scanned"] == 38 and last["scanned_since"] == "2026-03-02"
    assert last["notices_listed"] == 42 and last["notices_unread"] == 2
    [(url, schema, options)] = calls
    assert url == LIST_URL and schema == LIST_SCHEMA
    assert options == {"attempts": 1, "timeout": 45.0}


@pytest.mark.parametrize("answer, code", [
    (TimeoutError("timed out"), "TIMEOUT"),
    (RuntimeError("Context.dev HTTP 429 for https://..."), "UPSTREAM_ERROR"),
    (OSError("network is unreachable"), "UPSTREAM_ERROR"),
    ({"recalls": []}, "BAD_ANSWER"),
    ({"recalls": [{"title": "no url"}]}, "BAD_ANSWER"),
    ({"something": "else"}, "BAD_ANSWER"),
])
def test_slow_down_or_wrong_context_dev_falls_back_to_the_recording(env, monkeypatch, answer, code):
    client, *_ = env
    calls = []
    monkeypatch.setattr(recalls_view, "ContextDev", client_class(answer, calls))
    out = check(client).json()
    assert out["last_check"]["source"] == "recording" and out["last_check"]["live_error"] == code
    assert out["last_check"]["notices_listed"] is None
    assert len(calls) == 1                                  # never a retry
    assert out["alerts"][0]["proposals"][0]["status"] == "BLOCKED_BY_RECALL"


def test_timeout_comes_from_the_environment_and_is_bounded(env, monkeypatch):
    client, *_ = env
    calls = []
    monkeypatch.setattr(recalls_view, "ContextDev", client_class(TimeoutError(), calls))
    monkeypatch.setenv("RECALL_CHECK_COOLDOWN_S", "0")      # four checks in one instant (#652)
    for key, (value, expected) in enumerate([("7.5", 7.5), ("900", 120.0), ("0", 45.0), ("abc", 45.0)]):
        monkeypatch.setenv("RECALL_CHECK_TIMEOUT_S", value)
        check(client, f"k{key}")
        assert calls[-1][2]["timeout"] == expected, value


def test_no_recording_is_502_and_nothing_is_recorded(env, monkeypatch, tmp_path):
    client, db, *_ = env
    monkeypatch.setattr(recalls_view, "RECORDING", tmp_path / "missing.json")
    r = check(client)
    assert r.status_code == 502 and r.json()["error"]["code"] == "RECALL_CHECK_UNAVAILABLE"
    assert "recall_check" not in kinds(db)
    assert client.get(K + "/recalls", headers=HUMAN).json()["last_check"] is None
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"notices": "none"}), encoding="utf-8")
    monkeypatch.setattr(recalls_view, "RECORDING", bad)
    assert check(client, "other").status_code == 502


def test_check_needs_a_key_and_a_person_who_may_write(env):
    client, db, *_ = env
    for body in ({}, {"idempotency_key": ""}, {"idempotency_key": 7}, {"idempotency_key": "x" * 201}):
        r = client.post(K + "/recalls/check", headers=HUMAN, json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST", body
    r = check(client, headers=AGENT)
    assert r.status_code == 403 and r.json()["error"]["code"] == "SCOPE_REQUIRED"
    made = tokens.create(db, "hotel", "reader", ["kitchen:read", "kitchen:propose"], "chef")
    bearer = {"Authorization": "Bearer " + made["token"]}
    assert check(client, headers=bearer).status_code == 403
    assert client.get(K + "/recalls", headers=bearer).status_code == 200
    assert client.get("/v1/kitchens/other/recalls", headers=bearer).status_code == 403
    assert client.get(K + "/recalls").status_code == 401
    assert "recall_check" not in kinds(db)


def test_viewer_cannot_run_a_check_but_a_chef_can(env):
    client, db, *_ = env
    password = "correct horse battery staple"
    users.create_user(db, "view@example.com", password, name="Viewer", role="viewer", kitchen_id="hotel")
    users.create_user(db, "chef@example.com", password, name="Chef", role="chef", kitchen_id="hotel")
    client.post("/v1/auth/login", json={"email": "view@example.com", "password": password})
    r = client.post(K + "/recalls/check", json={"idempotency_key": "v"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "ROLE_REQUIRED"
    assert client.get(K + "/recalls").status_code == 200
    client.cookies.clear()
    client.post("/v1/auth/login", json={"email": "chef@example.com", "password": password})
    r = client.post(K + "/recalls/check", json={"idempotency_key": "c"})
    assert r.status_code == 200 and r.json()["last_check"]["checked_by"] == "chef@example.com"


def test_another_kitchen_sees_no_alert_and_no_check(env):
    client, *_ = env
    check(client)
    assert client.get("/v1/kitchens/other/recalls", headers=HUMAN).json() == {"last_check": None, "alerts": []}


def test_dismissed_alert_stays_listed_as_dismissed(env):
    client, *_ = env
    event_id = check(client).json()["alerts"][0]["event_id"]
    reason = "Checked the packs: affected lot is not held here"
    assert client.post(f"{K}/recalls/{event_id}/dismiss", headers=HUMAN, json={"reason": reason}).status_code == 200
    [alert] = client.get(K + "/recalls", headers=HUMAN).json()["alerts"]
    assert alert["status"] == "dismissed" and alert["dismissed_by"] == "chef" and alert["dismiss_reason"] == reason
    assert alert["proposals"][0]["status"] == "BLOCKED_BY_RECALL"      # a held basket stays held


def test_failed_replan_keeps_the_hold_and_shows_the_reason(env):
    client, db, *_ = env
    db.kitchen_settings.delete_many({})
    [held] = check(client).json()["alerts"][0]["proposals"]
    assert held["status"] == "BLOCKED_BY_RECALL" and held["recall_replan_error"] == "KITCHEN_POLICY_UNKNOWN"
    assert held["replacement_proposal_id"] is None and held["replacement"] is None


def test_recording_is_the_monitor_fixture():
    assert recalls_view.RECORDING == Path(recalls_view.__file__).parents[1] / "monitor/fixtures/ruokavirasto.json"
    assert recalls_view.RECORDING.exists()


def test_context_dev_client_makes_one_bounded_call_when_asked(monkeypatch):
    """monitor.recalls.ContextDev: `attempts=1` never sleeps and never calls twice (additive, #358)."""
    import urllib.error

    import monitor.recalls as monitor
    seen = []

    def busy(request, timeout):
        seen.append(timeout)
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {"Retry-After": "30"}, None)

    monkeypatch.setattr(monitor.urllib.request, "urlopen", busy)
    monkeypatch.setattr(monitor.time, "sleep", lambda seconds: pytest.fail("a single attempt must not wait"))
    with pytest.raises(RuntimeError, match="HTTP 429"):
        monitor.ContextDev(key="test-key").scrape_json(LIST_URL, LIST_SCHEMA, attempts=1, timeout=3)
    assert seen == [3]


# ---- one check at a time and a cooldown per kitchen (#652) --------------------------

def listing_client(monkeypatch):
    calls = []
    listing = {"recalls": [{"url": n["url"], "title": n["title"], "date": n["date"]} for n in NOTICES]}
    monkeypatch.setattr(recalls_view, "ContextDev", client_class(listing, calls))
    return calls


def test_new_key_inside_the_cooldown_reuses_the_newest_check_and_only_reads(env, monkeypatch):
    client, db, gw, _ = env
    calls = listing_client(monkeypatch)
    first = check(client, "one").json()
    assert "reused" not in first
    events, proposals = len(list_events(db, kitchen_id="hotel")), db.proposals.count_documents({})
    import monitor.proposals
    monkeypatch.setattr(monitor.proposals, "apply_notices",
                        lambda *a, **k: pytest.fail("a cooldown answer must not re-run the matching"))
    gw.now = lambda: NOW + timedelta(seconds=59)
    again = check(client, "two")
    assert again.status_code == 200, again.text
    assert again.json() == {**first, "reused": True}
    assert again.json()["last_check"]["checked_at"] == NOW.isoformat()      # the real check's own time
    assert len(calls) == 1
    assert len(list_events(db, kitchen_id="hotel")) == events          # no audit entry for the reuse
    assert db.proposals.count_documents({}) == proposals


def test_after_the_cooldown_a_new_key_scrapes_again(env, monkeypatch):
    client, db, gw, _ = env
    calls = listing_client(monkeypatch)
    check(client, "one")
    gw.now = lambda: NOW + timedelta(seconds=30)
    assert check(client, "two").json()["reused"] is True
    gw.now = lambda: NOW + timedelta(seconds=60)
    later = check(client, "two").json()      # the reused key was not recorded: now it runs
    assert "reused" not in later and later["last_check"]["checked_at"] == gw.now().isoformat()
    assert len(calls) == 2 and kinds(db).count("recall_check") == 2
    assert "reused" not in check(client, "two").json()      # and now it is a plain replay
    assert len(calls) == 2


def test_cooldown_seconds_come_from_the_environment(env, monkeypatch):
    client, db, gw, _ = env
    calls = listing_client(monkeypatch)
    monkeypatch.setenv("RECALL_CHECK_COOLDOWN_S", "10")
    check(client, "one")
    gw.now = lambda: NOW + timedelta(seconds=9)
    assert check(client, "two").json()["reused"] is True
    gw.now = lambda: NOW + timedelta(seconds=10)
    assert "reused" not in check(client, "three").json()
    monkeypatch.setenv("RECALL_CHECK_COOLDOWN_S", "0")      # off
    assert "reused" not in check(client, "four").json()
    assert len(calls) == 3


def test_cooldown_of_one_kitchen_does_not_touch_another(env, monkeypatch):
    client, db, gw, _ = env
    calls = listing_client(monkeypatch)
    hotel = check(client, "one").json()
    other = client.post("/v1/kitchens/other/recalls/check", headers=HUMAN, json={"idempotency_key": "one"})
    assert other.status_code == 200, other.text
    out = other.json()
    assert "reused" not in out and len(calls) == 2          # its own check, not the hotel's
    assert out["alerts"] == [] and hotel["alerts"]          # and none of the hotel's alerts
    assert out["last_check"]["source"] == "live"
    checked = [e["server"]["kitchen_id"] for e in list_events(db) if e["event"].get("kind") == "recall_check"]
    assert sorted(checked) == ["hotel", "other"]
    # The hotel's cooldown is still its own.
    assert check(client, "two").json() == {**hotel, "reused": True}
    assert len(calls) == 2


def test_two_checks_at_once_make_one_scrape(env, monkeypatch):
    """The second check waits for the first, then reads its result. No sleeping: events only."""
    import threading
    _, db, gw, _ = env
    scraping, release, second_waits = threading.Event(), threading.Event(), threading.Event()
    calls, results = [], {}

    class Slow:
        def scrape_json(self, url, schema, **options):
            calls.append(url)
            scraping.set()
            assert release.wait(10)
            return {"recalls": [{"url": n["url"], "title": n["title"], "date": n["date"]} for n in NOTICES]}

    class Watched(type(recalls_view._LOCKS)):
        def hold(self, key, wait):
            if scraping.is_set():           # the first check holds the lock: this one will wait
                second_waits.set()
            return super().hold(key, wait)

    monkeypatch.setattr(recalls_view, "ContextDev", Slow)
    monkeypatch.setattr(recalls_view, "_LOCKS", Watched())

    def run(key):
        results[key] = recalls_view.run_check(gw, "hotel", {"idempotency_key": key}, "chef")

    first = threading.Thread(target=run, args=("one",))
    second = threading.Thread(target=run, args=("two",))
    first.start()
    assert scraping.wait(10)
    second.start()
    assert second_waits.wait(10)
    assert "two" not in results             # it did not answer early with "no recalls"
    release.set()
    first.join(10)
    second.join(10)
    assert len(calls) == 1
    assert "reused" not in results["one"] and results["two"] == {**results["one"], "reused": True}
    assert kinds(db).count("recall_check") == 1 and kinds(db).count("recall_replacement_proposed") == 1
    assert recalls_view._LOCKS._rows == {}  # nobody holds the kitchen: the lock is forgotten


def test_check_that_cannot_start_in_time_is_429_not_no_recalls(env, monkeypatch):
    client, db, *_ = env
    calls = listing_client(monkeypatch)
    monkeypatch.setenv("RECALL_CHECK_LOCK_WAIT_S", "0")
    with recalls_view._LOCKS.hold("hotel", 0) as held:      # a check that is still running
        assert held
        r = check(client)
        assert r.status_code == 429, r.text
        assert r.json()["error"]["code"] == "RECALL_CHECK_BUSY" and r.json()["error"]["retry_after_s"] == 10
        assert r.headers["retry-after"] == "10"
        assert "alerts" not in r.json() and "last_check" not in r.json()
        other = client.post("/v1/kitchens/other/recalls/check", headers=HUMAN, json={"idempotency_key": "x"})
        assert other.status_code == 200                     # another kitchen is not held up
    assert "recall_check" not in kinds(db)
    assert client.get(K + "/recalls", headers=HUMAN).json()["last_check"] is None   # still unknown
    assert check(client).status_code == 200 and len(calls) == 2
