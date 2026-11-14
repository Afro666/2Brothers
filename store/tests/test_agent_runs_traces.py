"""What the model did (#1197): the trace is kept with the run and read per proposal."""

import pytest

mongomock = pytest.importorskip("mongomock")

from store import agent_runs  # noqa: E402

TRACE = {"made_by": "model", "reader": "buyer", "steps": []}


@pytest.fixture()
def db():
    return mongomock.MongoClient(tz_aware=True)["test"]


def add(db, run_id, kitchen="K01", state="READY", result=None):
    db.agent_runs.insert_one({"_id": run_id, "kitchen_id": kitchen, "state": state, "result": result})


def test_traces_reads_finished_runs_of_this_kitchen_only(db):
    add(db, "a", result={"proposal_id": "p1", "model_trace": TRACE})
    add(db, "b", kitchen="K02", result={"proposal_id": "p2", "model_trace": TRACE})
    add(db, "c", state="RECONCILE", result={"proposal_id": "p3", "model_trace": TRACE})
    add(db, "d", result={"proposal_id": "p4"})                     # a run from before #1197
    add(db, "e", result=None)
    assert agent_runs.traces(db, "K01", ["p1", "p2", "p3", "p4", "p5"]) == {"p1": TRACE}


def test_traces_of_no_proposals_reads_nothing(db):
    assert agent_runs.traces(db, "K01", []) == {}
    assert agent_runs.traces(db, "K01", [None, 3]) == {}


def test_startup_indexes_cover_the_trace_read(db):
    from store.db import ensure_indexes

    ensure_indexes(db)
    keys = [spec["key"] for spec in db.agent_runs.index_information().values()]
    assert [("kitchen_id", 1), ("result.proposal_id", 1)] in keys
