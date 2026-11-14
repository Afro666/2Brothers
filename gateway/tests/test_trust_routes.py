"""Trust routes (#711): audit verify, the tamper demo, the event stream.

Verify, tamper and restore run on the real `store.trust` (mongomock). A change stream
needs a replica set, so the stream tests replace `store.trust.watch_kitchen` with an
iterator of the same shape (`KitchenEvents`: items or None, `close()`).
"""

import json
import socket
import threading
import time
from datetime import datetime, timezone

import pytest

mongomock = pytest.importorskip("mongomock")
pytest.importorskip("fastapi")
import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pymongo.errors import OperationFailure  # noqa: E402

from gateway import tokens, trust_routes  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.service import Gateway  # noqa: E402
from store import audit, trust  # noqa: E402

NOW = datetime(2026, 11, 14, 9, 0, tzinfo=timezone.utc)
HUMAN = {"Authorization": "Bearer human-test-token", "X-User": "aron"}
AGENT = {"Authorization": "Bearer agent-test-token"}
DEMO = "/v1/kitchens/demo-kitchen"


class FakeEvents:
    """What `store.trust.watch_kitchen` returns: items or None; `forever` keeps it open."""

    def __init__(self, items=(), forever=False):
        self.items, self.forever, self.closed = list(items), forever, threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed.is_set():
            raise StopIteration
        if self.items:
            return self.items.pop(0)
        if not self.forever:
            raise StopIteration
        time.sleep(0.02)
        return None

    def close(self):
        self.closed.set()


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    monkeypatch.delenv("GATEWAY_REQUIRE_LOGIN", raising=False)
    db = mongomock.MongoClient(tz_aware=True)["test"]
    db.kitchens.insert_one({"_id": "demo-kitchen", "synthetic": True})
    db.kitchens.insert_one({"_id": "real-kitchen"})
    for n, kitchen in enumerate(["demo-kitchen", "real-kitchen", "demo-kitchen"]):
        audit.append_event(db, {"event_id": f"e{n}", "kind": "proposal_created", "actor": "buyer"},
                           {"kitchen_id": kitchen, "at": NOW.isoformat()})
    app = create_app(Gateway(db, None, now=lambda: NOW))
    return TestClient(app), db, app


def code(response) -> str:
    return response.json()["error"]["code"]


# ---- verify ---------------------------------------------------------------------------

def test_verify_answers_the_contract_shape(env):
    client, *_ = env
    r = client.get(DEMO + "/audit/verify", headers=AGENT)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "length": 3, "broken_at": None, "broken_kitchen_id": None,
                        "kitchen_entries": 2}
    assert client.get("/v1/kitchens/real-kitchen/audit/verify", headers=AGENT).json()["kitchen_entries"] == 1


def test_verify_auth(env):
    client, db, _ = env
    assert client.get(DEMO + "/audit/verify").status_code == 401
    made = tokens.create(db, "real-kitchen", "reader", ["kitchen:read"], "aron")
    own = {"Authorization": "Bearer " + made["token"]}
    assert client.get("/v1/kitchens/real-kitchen/audit/verify", headers=own).status_code == 200
    other = client.get(DEMO + "/audit/verify", headers=own)
    assert other.status_code == 403 and code(other) == "KITCHEN_SCOPE"
    made = tokens.create(db, "real-kitchen", "proposer", ["kitchen:propose"], "aron")
    r = client.get("/v1/kitchens/real-kitchen/audit/verify", headers={"Authorization": "Bearer " + made["token"]})
    assert r.status_code == 403 and code(r) == "SCOPE_REQUIRED"


# ---- the newest entries with their hashes ----------------------------------------------

def test_chain_rows_are_this_kitchens_newest_entries_oldest_first(env):
    client, db, _ = env
    r = client.get(DEMO + "/audit/chain?limit=5", headers=AGENT)
    assert r.status_code == 200, r.text
    entries = r.json()["entries"]
    assert [entry["seq"] for entry in entries] == [1, 3]             # seq 2 is another kitchen's
    stored = db.audit_log.find_one({"_id": 3})
    assert entries[1] == {"seq": 3, "prev_hash": stored["prev_hash"], "hash": stored["hash"],
                          "event": {"seq": 3, "event_id": "e2", "kind": "proposal_created",
                                    "actor": "buyer", "at": NOW.isoformat()}}
    # The events are the ones GET /audit answers.
    assert [entry["event"] for entry in entries] == client.get(DEMO + "/audit", headers=AGENT).json()["events"]
    assert [e["seq"] for e in client.get(DEMO + "/audit/chain?limit=1", headers=AGENT).json()["entries"]] == [3]
    assert len(client.get(DEMO + "/audit/chain", headers=AGENT).json()["entries"]) == 2


def test_chain_rows_show_the_tampered_entry_with_its_old_hash(env):
    client, _, _ = env
    before = client.get(DEMO + "/audit/chain", headers=AGENT).json()["entries"][-1]
    client.post(DEMO + "/audit/demo-tamper", headers=HUMAN, json={"idempotency_key": "t1"})
    entries = client.get(DEMO + "/audit/chain", headers=AGENT).json()["entries"]
    assert [entry["seq"] for entry in entries] == [1, 3, 4]
    assert entries[1]["hash"] == before["hash"] and entries[1]["event"]["tampered"] == trust.TAMPER_NOTE
    assert entries[2]["event"]["kind"] == "audit_demo_tamper" and entries[2]["prev_hash"] == before["hash"]


def test_chain_rows_limit_and_auth(env):
    client, db, _ = env
    for bad in ("0", "101", "-1", "abc", "1.5", ""):
        r = client.get(DEMO + "/audit/chain?limit=" + bad, headers=AGENT)
        assert r.status_code == 422 and code(r) == "INVALID_REQUEST", bad
    assert client.get(DEMO + "/audit/chain").status_code == 401
    made = tokens.create(db, "real-kitchen", "reader", ["kitchen:read"], "aron")
    r = client.get(DEMO + "/audit/chain", headers={"Authorization": "Bearer " + made["token"]})
    assert r.status_code == 403 and code(r) == "KITCHEN_SCOPE"


# ---- tamper and restore ---------------------------------------------------------------

def test_tamper_then_restore_round_trip(env):
    client, db, _ = env
    before = db.audit_log.find_one({"_id": 3})
    r = client.post(DEMO + "/audit/demo-tamper", headers=HUMAN, json={"idempotency_key": "t1"})
    assert r.status_code == 200, r.text
    assert r.json() == {"seq": 3, "tampered": True}

    broken = client.get(DEMO + "/audit/verify", headers=AGENT).json()
    assert (broken["ok"], broken["broken_at"], broken["broken_kitchen_id"]) == (False, 3, "demo-kitchen")
    other = client.get("/v1/kitchens/real-kitchen/audit/verify", headers=AGENT).json()
    assert (other["ok"], other["broken_kitchen_id"]) == (False, "demo-kitchen")

    r = client.post(DEMO + "/audit/demo-restore", headers=HUMAN, json={"idempotency_key": "r1"})
    assert r.status_code == 200, r.text
    assert r.json() == {"seq": 3, "restored": True}
    assert db.audit_log.find_one({"_id": 3}) == before
    assert client.get(DEMO + "/audit/verify", headers=AGENT).json()["ok"] is True

    again = client.post(DEMO + "/audit/demo-restore", headers=HUMAN, json={"idempotency_key": "r2"})
    assert again.json() == {"seq": None, "restored": False}


def test_tamper_and_restore_are_audit_entries_that_name_the_person(env):
    client, _, _ = env
    client.post(DEMO + "/audit/demo-tamper", headers=HUMAN, json={"idempotency_key": "t1"})
    client.post(DEMO + "/audit/demo-restore", headers=HUMAN, json={"idempotency_key": "r1"})
    client.post(DEMO + "/audit/demo-restore", headers=HUMAN, json={"idempotency_key": "r2"})   # nothing to restore
    events = client.get(DEMO + "/audit", headers=AGENT).json()["events"]
    assert [(e["kind"], e["actor"], e.get("tampered_seq")) for e in events[-2:]] == [
        ("audit_demo_tamper", "aron", 3), ("audit_demo_restore", "aron", 3)]
    assert events[-1]["at"] == NOW.isoformat()
    assert client.get(DEMO + "/audit/verify", headers=AGENT).json() == {
        "ok": True, "length": 5, "broken_at": None, "broken_kitchen_id": None, "kitchen_entries": 4}


def test_tamper_replay_returns_the_stored_answer(env):
    client, db, _ = env
    first = client.post(DEMO + "/audit/demo-tamper", headers=HUMAN, json={"idempotency_key": "t1"})
    replay = client.post(DEMO + "/audit/demo-tamper", headers=HUMAN, json={"idempotency_key": "t1"})
    assert replay.status_code == 200 and replay.json() == first.json() == {"seq": 3, "tampered": True}
    second = client.post(DEMO + "/audit/demo-tamper", headers=HUMAN, json={"idempotency_key": "t2"})
    assert second.status_code == 409 and code(second) == "ALREADY_TAMPERED"
    assert db.audit_log.count_documents({"event.kind": "audit_demo_tamper"}) == 1

    done = client.post(DEMO + "/audit/demo-restore", headers=HUMAN, json={"idempotency_key": "r1"})
    replay = client.post(DEMO + "/audit/demo-restore", headers=HUMAN, json={"idempotency_key": "r1"})
    assert replay.json() == done.json() == {"seq": 3, "restored": True}
    assert db.audit_log.count_documents({"event.kind": "audit_demo_restore"}) == 1


def test_tamper_without_audit_entries_is_409(env):
    client, db, _ = env
    db.audit_log.delete_many({"server.kitchen_id": "demo-kitchen"})
    r = client.post(DEMO + "/audit/demo-tamper", headers=HUMAN, json={"idempotency_key": "t1"})
    assert r.status_code == 409 and code(r) == "NOTHING_TO_TAMPER"


@pytest.mark.parametrize("route", ["/audit/demo-tamper", "/audit/demo-restore"])
def test_demo_routes_refuse_other_kitchens_agents_and_missing_keys(env, route):
    client, db, _ = env
    count = db.audit_log.count_documents({})
    r = client.post("/v1/kitchens/real-kitchen" + route, headers=HUMAN, json={"idempotency_key": "k"})
    assert r.status_code == 403 and code(r) == "DEMO_ONLY"
    db.kitchens.insert_one({"_id": "other-demo", "synthetic": True})
    r = client.post("/v1/kitchens/other-demo" + route, headers=HUMAN, json={"idempotency_key": "k"})
    assert r.status_code == 403 and code(r) == "DEMO_ONLY"

    r = client.post(DEMO + route, headers=AGENT, json={"idempotency_key": "k"})
    assert r.status_code == 403 and code(r) == "HUMAN_SESSION_REQUIRED"
    made = tokens.create(db, "demo-kitchen", "reader", ["kitchen:read", "kitchen:propose"], "aron")
    r = client.post(DEMO + route, headers={"Authorization": "Bearer " + made["token"]}, json={"idempotency_key": "k"})
    assert r.status_code == 403 and code(r) == "HUMAN_SESSION_REQUIRED"

    for bad in ({}, {"idempotency_key": ""}, {"idempotency_key": "  "}, {"idempotency_key": 7}):
        r = client.post(DEMO + route, headers=HUMAN, json=bad)
        assert r.status_code == 422 and code(r) == "INVALID_REQUEST", bad
    assert client.post(DEMO + route, headers=HUMAN, content=b"not json").status_code == 422
    assert db.audit_log.count_documents({}) == count
    assert db.audit_tamper_demo.count_documents({}) == 0


def test_demo_kitchen_that_is_not_synthetic_is_refused(env):
    client, db, _ = env
    db.kitchens.update_one({"_id": "demo-kitchen"}, {"$set": {"synthetic": False}})
    r = client.post(DEMO + "/audit/demo-tamper", headers=HUMAN, json={"idempotency_key": "k"})
    assert r.status_code == 403 and code(r) == "DEMO_ONLY"


# ---- the event stream -----------------------------------------------------------------

def frames(text: str) -> list[str]:
    return [frame for frame in text.split("\n\n") if frame]


def test_events_is_503_without_change_streams(env, monkeypatch):
    client, _, app = env
    r = client.get(DEMO + "/events", headers=AGENT)          # mongomock has no db.watch
    assert r.status_code == 503 and code(r) == "EVENTS_UNAVAILABLE"

    def standalone(*_, **__):
        raise OperationFailure("The $changeStream stage is only supported on replica sets", 40573)

    monkeypatch.setattr(trust, "watch_kitchen", standalone)
    r = client.get(DEMO + "/events", headers=AGENT)
    assert r.status_code == 503 and code(r) == "EVENTS_UNAVAILABLE"
    assert "$changeStream" not in r.text and "40573" not in r.text      # never the driver's message
    assert app.state.trust_streams.open == 0


def test_events_sends_each_change_in_the_contract_shape(env, monkeypatch):
    client, db, app = env
    entry = db.audit_log.find_one({"_id": 3})
    approval = {"_id": "ap1", "kitchen_id": "demo-kitchen", "status": "PENDING", "requested_at": NOW,
                "decided_by": None}
    proposal = {"_id": "p1", "kitchen_id": "demo-kitchen", "status": "READY", "offer_id": "gone"}
    fake = FakeEvents([None,
                       {"collection": "audit_log", "operation": "insert", "document": entry},
                       {"collection": "approvals", "operation": "update", "document": approval},
                       {"collection": "proposals", "operation": "replace", "document": proposal}])
    seen = []
    monkeypatch.setattr(trust, "watch_kitchen", lambda db_, kitchen_id, **kw: seen.append(kitchen_id) or fake)
    monkeypatch.setattr(trust_routes, "PING_SECONDS", 0)

    r = client.get(DEMO + "/events", headers=AGENT)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert seen == ["demo-kitchen"]
    got = frames(r.text)
    assert got[0] == ": connected" and got[1] == ": ping"
    messages = [(frame.split("\n")[0], json.loads(frame.split("\n")[1].removeprefix("data: "))) for frame in got[2:]]
    assert [event for event, _ in messages] == ["event: audit", "event: approval", "event: proposal"]
    assert messages[0][1] == {"operation": "insert", "document": {
        "seq": 3, "event_id": "e2", "kind": "proposal_created", "actor": "buyer", "at": NOW.isoformat()}}
    assert messages[1][1] == {"operation": "update", "document": {
        "approval_id": "ap1", "kitchen_id": "demo-kitchen", "status": "PENDING",
        "requested_at": NOW.isoformat(), "decided_by": None}}
    # The offer of this proposal is gone: the row still arrives, with what is certain.
    assert messages[2][1] == {"operation": "replace", "document": {"proposal_id": "p1", "status": "READY"}}
    assert fake.closed.is_set()
    assert app.state.trust_streams.open == 0


def test_events_closes_after_its_lifetime(env, monkeypatch):
    client, _, app = env
    fake = FakeEvents(forever=True)
    monkeypatch.setattr(trust, "watch_kitchen", lambda *_, **__: fake)
    monkeypatch.setattr(trust_routes, "MAX_SECONDS", 0.2)
    started = time.monotonic()
    r = client.get(DEMO + "/events", headers=AGENT)
    assert r.status_code == 200 and time.monotonic() - started < 5
    assert frames(r.text)[0] == ": connected"
    assert fake.closed.is_set() and app.state.trust_streams.open == 0


def test_events_auth_is_checked_before_a_stream_is_opened(env, monkeypatch):
    client, db, _ = env
    opened = []
    monkeypatch.setattr(trust, "watch_kitchen", lambda *_, **__: opened.append(1) or FakeEvents())
    assert client.get(DEMO + "/events").status_code == 401
    made = tokens.create(db, "real-kitchen", "reader", ["kitchen:read"], "aron")
    r = client.get(DEMO + "/events", headers={"Authorization": "Bearer " + made["token"]})
    assert r.status_code == 403 and code(r) == "KITCHEN_SCOPE"
    assert opened == []


def test_events_refuses_more_streams_than_the_cap(env, monkeypatch):
    client, _, app = env
    opened = []
    monkeypatch.setattr(trust, "watch_kitchen", lambda *_, **__: opened.append(1) or FakeEvents())
    app.state.trust_streams.open = trust_routes.MAX_STREAMS      # as if that many tabs were open
    r = client.get(DEMO + "/events", headers=AGENT)
    assert r.status_code == 503 and code(r) == "EVENTS_UNAVAILABLE"
    assert opened == [] and app.state.trust_streams.open == trust_routes.MAX_STREAMS


def _serve(app):
    """The app on a real socket (uvicorn in a thread), so a client can hang up."""
    import uvicorn
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    return server, thread, f"http://127.0.0.1:{sock.getsockname()[1]}"


def test_events_closes_the_change_stream_when_the_client_disconnects(env, monkeypatch):
    _, _, app = env
    fake = FakeEvents(forever=True)
    monkeypatch.setattr(trust, "watch_kitchen", lambda *_, **__: fake)
    monkeypatch.setattr(trust_routes, "PING_SECONDS", 0.05)
    server, thread, base = _serve(app)
    try:
        with httpx.Client(timeout=10) as http:
            with http.stream("GET", base + DEMO + "/events", headers=AGENT) as r:
                assert r.status_code == 200
                lines = r.iter_lines()
                assert next(lines) == ": connected"
                # Another request is answered while the stream is open: the loop is not blocked.
                assert httpx.get(base + "/health", timeout=10).status_code == 200
                assert app.state.trust_streams.open == 1 and not fake.closed.is_set()
        assert fake.closed.wait(10), "the change stream stayed open after the client left"
        deadline = time.monotonic() + 5
        while app.state.trust_streams.open and time.monotonic() < deadline:
            time.sleep(0.02)
        assert app.state.trust_streams.open == 0
    finally:
        server.should_exit = True
        thread.join(10)
