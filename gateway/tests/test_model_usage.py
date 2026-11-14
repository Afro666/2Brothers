"""Model usage route (#365): the contract shape, the empty kitchen, scopes."""

from datetime import datetime, timezone

import pytest

mongomock = pytest.importorskip("mongomock")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from gateway import model_usage, tokens  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.service import Gateway  # noqa: E402

NOW = datetime(2026, 11, 14, 23, 0, tzinfo=timezone.utc)
AGENT = {"Authorization": "Bearer agent-test-token"}
URL = "/v1/kitchens/K01/model-usage"
EMPTY = {"model": "nemotron-3.5-super-vl", "since": None, "runs": 0, "finished_runs": 0,
         "runs_without_usage": 0, "model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
         "reasoning_tokens": 0, "model_seconds": "0.0", "last_run_at": None}


def run(db, run_id, *, kitchen="K01", state="READY", usage=None, hour=18):
    result = None if state != "READY" else {"proposal_id": run_id, **({"buyer_usage": usage} if usage else {})}
    db.agent_runs.insert_one({"_id": run_id, "kitchen_id": kitchen, "state": state, "result": result,
                              "created_at": datetime(2026, 11, 14, hour, 2, 11, 250000, tzinfo=timezone.utc),
                              "finished_at": datetime(2026, 11, 14, hour, 3, 0, tzinfo=timezone.utc)})


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    monkeypatch.delenv("GATEWAY_REQUIRE_LOGIN", raising=False)
    db = mongomock.MongoClient(tz_aware=True)["test"]
    db.kitchens.insert_many([{"_id": "K01"}, {"_id": "K02"}])
    return TestClient(create_app(Gateway(db, None, now=lambda: NOW))), db


def test_a_kitchen_without_runs_gets_zeros(env):
    client, _ = env
    r = client.get(URL, headers=AGENT)
    assert r.status_code == 200, r.text
    assert r.json() == EMPTY


def test_it_answers_the_contract_shape(env):
    client, db = env
    run(db, "a", usage={"calls": 7, "failed": 0, "prompt_tokens": 41250, "completion_tokens": 1830,
                        "reasoning_tokens": 0, "seconds": 38.412})
    run(db, "b", hour=20, usage={"calls": 5, "failed": 1, "prompt_tokens": 30000, "completion_tokens": 1000,
                                 "reasoning_tokens": 40, "seconds": 20.25})
    run(db, "old")                                  # from before the meter
    run(db, "failed", state="RECONCILE", hour=22)   # ended without a proposal
    run(db, "other", kitchen="K02", usage={"calls": 99, "prompt_tokens": 99, "completion_tokens": 99, "seconds": 99})
    assert client.get(URL, headers=AGENT).json() == {
        "model": "nemotron-3.5-super-vl", "since": "2026-11-14T18:02:11+00:00",
        "runs": 4, "finished_runs": 3, "runs_without_usage": 2,
        "model_calls": 12, "prompt_tokens": 71250, "completion_tokens": 2830, "reasoning_tokens": 40,
        "model_seconds": "58.7", "last_run_at": "2026-11-14T20:03:00+00:00"}


def test_only_runs_without_usage_shows_no_counts(env):
    client, db = env
    run(db, "old")
    assert client.get(URL, headers=AGENT).json() == {**EMPTY, "runs": 1, "finished_runs": 1, "runs_without_usage": 1}


def test_a_naive_time_is_read_as_utc():
    assert model_usage._iso(datetime(2026, 11, 14, 18, 2, 11)) == "2026-11-14T18:02:11+00:00"
    assert model_usage._iso(None) is None


def test_auth(env):
    client, db = env
    assert client.get(URL).status_code == 401
    made = tokens.create(db, "K01", "reader", ["kitchen:read"], "aron")
    own = {"Authorization": "Bearer " + made["token"]}
    assert client.get(URL, headers=own).status_code == 200
    other = client.get("/v1/kitchens/K02/model-usage", headers=own)
    assert other.status_code == 403 and other.json()["error"]["code"] == "KITCHEN_SCOPE"
    made = tokens.create(db, "K01", "proposer", ["kitchen:propose"], "aron")
    r = client.get(URL, headers={"Authorization": "Bearer " + made["token"]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "SCOPE_REQUIRED"
