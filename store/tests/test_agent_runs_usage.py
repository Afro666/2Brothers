"""Model usage (#365): the sum of `result.buyer_usage` over the Buyer runs of a kitchen."""

from datetime import datetime, timezone

import pytest

mongomock = pytest.importorskip("mongomock")

from store import agent_runs  # noqa: E402

T1 = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 11, 14, 19, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 11, 14, 20, 0, tzinfo=timezone.utc)
USAGE = {"calls": 7, "failed": 1, "prompt_tokens": 41250, "completion_tokens": 1830,
         "reasoning_tokens": 12, "seconds": 38.412}


def run(db, run_id, kitchen="K01", *, state="READY", usage=None, created=T1, finished=T2, result=True):
    doc = {"_id": run_id, "kitchen_id": kitchen, "payload_hash": "h", "state": state, "created_at": created}
    if state != "RUNNING":
        doc["finished_at"] = finished
        doc["result"] = ({"proposal_id": "p-" + run_id, **({"buyer_usage": usage} if usage is not None else {})}
                         if result else None)
    db.agent_runs.insert_one(doc)


@pytest.fixture()
def db():
    return mongomock.MongoClient(tz_aware=True)["test"]


def test_no_runs_is_all_zero(db):
    assert agent_runs.usage_totals(db, "K01") == {
        "runs": 0, "finished_runs": 0, "runs_without_usage": 0, "calls": 0, "prompt_tokens": 0,
        "completion_tokens": 0, "reasoning_tokens": 0, "seconds": 0.0, "since": None, "last_run_at": None}


def test_sums_the_runs_that_carry_usage(db):
    run(db, "a", usage=USAGE, created=T2, finished=T3)
    run(db, "b", usage={**USAGE, "calls": 3, "seconds": 1.5}, created=T1, finished=T2)
    totals = agent_runs.usage_totals(db, "K01")
    assert totals["runs"] == totals["finished_runs"] == 2 and totals["runs_without_usage"] == 0
    assert (totals["calls"], totals["prompt_tokens"], totals["completion_tokens"], totals["reasoning_tokens"]) \
        == (10, 82500, 3660, 24)
    assert totals["seconds"] == pytest.approx(39.912)
    assert (totals["since"], totals["last_run_at"]) == (T1, T3)


def test_runs_without_usage_are_counted_apart(db):
    run(db, "counted", usage=USAGE)
    run(db, "before-the-meter", created=datetime(2026, 11, 1, tzinfo=timezone.utc))   # READY, no buyer_usage
    run(db, "reconcile", state="RECONCILE", result=False, finished=T3)                 # result is None
    run(db, "running", state="RUNNING")
    totals = agent_runs.usage_totals(db, "K01")
    assert (totals["runs"], totals["finished_runs"], totals["runs_without_usage"]) == (4, 2, 3)
    assert totals["calls"] == 7 and totals["prompt_tokens"] == 41250
    # The times are those of the counted run only, not of the older or newer uncounted ones.
    assert (totals["since"], totals["last_run_at"]) == (T1, T2)


def test_the_runs_of_another_kitchen_are_not_counted(db):
    run(db, "mine", usage=USAGE)
    run(db, "theirs", kitchen="K02", usage=USAGE)
    assert agent_runs.usage_totals(db, "K01")["calls"] == 7
    assert agent_runs.usage_totals(db, "K03")["runs"] == 0


def test_a_malformed_count_adds_zero(db):
    run(db, "bad", usage={"calls": "7", "prompt_tokens": -5, "completion_tokens": True,
                          "reasoning_tokens": 1.5, "seconds": float("nan")})
    run(db, "not-a-dict", usage="lots")
    totals = agent_runs.usage_totals(db, "K01")
    assert (totals["calls"], totals["prompt_tokens"], totals["completion_tokens"],
            totals["reasoning_tokens"], totals["seconds"]) == (0, 0, 0, 0, 0.0)
    assert (totals["runs"], totals["runs_without_usage"]) == (2, 1)


def test_it_reads_what_the_worker_stores(db):
    row, created = agent_runs.claim(db, "K01", "key-1", {"text": "milk"})
    assert created
    agent_runs.finish(db, row["_id"], state="READY", result={"proposal_id": "p1", "buyer_usage": USAGE})
    totals = agent_runs.usage_totals(db, "K01")
    assert (totals["runs"], totals["finished_runs"], totals["calls"]) == (1, 1, 7)
    assert totals["since"] is not None and totals["last_run_at"] >= totals["since"]
