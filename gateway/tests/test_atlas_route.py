"""Atlas facts route (#1383). Contract: docs/contract.md, "Atlas facts".

The shape is `store.atlas.atlas_facts`; the gateway adds a one-minute cache and the scope check.
"""

from datetime import datetime, timezone

import pytest

mongomock = pytest.importorskip("mongomock")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from gateway import atlas_routes, tokens  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.service import Gateway  # noqa: E402

NOW = datetime(2026, 11, 14, 23, 0, tzinfo=timezone.utc)
AGENT = {"Authorization": "Bearer agent-test-token"}
URL = "/v1/kitchens/K01/atlas"
KEYS = {"mongodb_version", "data_mb", "products", "vectors", "search_indexes", "time_series",
        "audit_entries", "change_stream_collections"}


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    monkeypatch.delenv("GATEWAY_REQUIRE_LOGIN", raising=False)
    db = mongomock.MongoClient(tz_aware=True)["test"]
    db.kitchens.insert_many([{"_id": "K01"}, {"_id": "K02"}])
    return TestClient(create_app(Gateway(db, None, now=lambda: NOW))), db


def test_it_answers_the_contract_shape(env):
    client, db = env
    db.products.insert_many([
        {"_id": "1", "embedding": {"vector": b"x", "model": "voyage-4", "dimensions": 1024}},
        {"_id": "2", "embedding": {"vector": b"x", "model": "voyage-4", "dimensions": 1024}},
        {"_id": "3"}])
    r = client.get(URL, headers=AGENT)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == KEYS
    assert body["products"] == 3
    assert body["vectors"] == [{"model": "voyage-4", "dimensions": 1024, "count": 2}]
    assert body["change_stream_collections"] == ["proposals", "approvals", "audit_log"]


def test_no_address_or_key_in_the_answer(env):
    client, _ = env
    text = client.get(URL, headers=AGENT).text.lower()
    for word in ("mongodb+srv", "mongodb://", "password", "host", "uri", "key", "token"):
        assert word not in text


def test_the_answer_is_kept_for_a_minute():
    calls, clock = [], [1000.0]

    def facts(db):
        calls.append(db)
        return {"products": len(calls)}

    cache = atlas_routes.FactsCache(facts=facts, clock=lambda: clock[0])
    assert cache.get("db") == {"products": 1}
    clock[0] += 59.9
    assert cache.get("db") == {"products": 1}       # the same answer, no new read
    clock[0] += 0.2
    assert cache.get("db") == {"products": 2}       # a minute is over: read again
    assert len(calls) == 2


def test_a_failed_read_is_not_kept():
    clock = [0.0]
    answers = iter([RuntimeError("down"), {"products": 5}])

    def facts(db):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    cache = atlas_routes.FactsCache(facts=facts, clock=lambda: clock[0])
    with pytest.raises(RuntimeError):
        cache.get("db")
    assert cache.get("db") == {"products": 5}       # the next request reads again


def test_an_all_unknown_answer_is_not_kept():
    clock = [0.0]
    unknown = {part: None for part in atlas_routes.READ_PARTS}
    unknown["change_stream_collections"] = ["proposals", "approvals", "audit_log"]
    answers = iter([unknown, {**unknown, "products": 5}, {**unknown, "products": 6}])
    cache = atlas_routes.FactsCache(facts=lambda db: next(answers), clock=lambda: clock[0])
    assert cache.get("db") == unknown               # Atlas down: every read part unknown
    assert cache.get("db")["products"] == 5         # not kept: the next request reads again
    assert cache.get("db")["products"] == 5         # partly known: kept for the minute


def test_auth(env):
    client, db = env
    assert client.get(URL).status_code == 401
    made = tokens.create(db, "K01", "reader", ["kitchen:read"], "aron")
    own = {"Authorization": "Bearer " + made["token"]}
    assert client.get(URL, headers=own).status_code == 200
    other = client.get("/v1/kitchens/K02/atlas", headers=own)
    assert other.status_code == 403 and other.json()["error"]["code"] == "KITCHEN_SCOPE"
    made = tokens.create(db, "K01", "proposer", ["kitchen:propose"], "aron")
    r = client.get(URL, headers={"Authorization": "Bearer " + made["token"]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "SCOPE_REQUIRED"
