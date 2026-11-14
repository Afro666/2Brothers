"""What the model did (#1197): the Buyer run records its steps, the run keeps them, the
gateway serves them on the proposal. Fakes only: no model endpoint."""
import asyncio
import json

import pytest

pytest.importorskip("mongomock")

from agent.service import BuyerWorker  # noqa: E402
from agent.tests.test_service import NOW, ScriptedBuyer, environment, tool  # noqa: E402
from agent.usage import Meter  # noqa: E402


class MeteredBuyer(ScriptedBuyer):
    thinking = False

    def __init__(self):
        super().__init__()
        self.meter = Meter()

    async def complete(self, messages, definitions):
        self.meter.record("buyer", {"prompt_tokens": 100, "completion_tokens": 10}, 1.5)
        return await super().complete(messages, definitions)


def run_worker(monkeypatch, model, key="trace-1"):
    async def go():
        db, gateway = environment(monkeypatch)
        worker = BuyerWorker(db, gateway, strategy="loop", model_factory=lambda: model, now=lambda: NOW)
        body = {"text": "51 L milk", "requested_date": "2026-11-16", "idempotency_key": key}
        try:
            proposal = await worker.run("demo-kitchen", body)
            replay = await worker.run("demo-kitchen", body)
            listed = await gateway.request("GET", "/v1/kitchens/demo-kitchen/proposals")
            one = await gateway.request("GET", f"/v1/kitchens/demo-kitchen/proposals/{proposal['proposal_id']}")
            return db, proposal, replay, listed, one
        finally:
            await gateway.close()
    return asyncio.run(go())


def test_the_buyer_answer_carries_what_the_model_did(monkeypatch):
    db, proposal, replay, listed, one = run_worker(monkeypatch, MeteredBuyer())
    trace = proposal["model_trace"]
    assert (trace["made_by"], trace["reader"], trace["model"]) == ("model", "buyer", "nemotron-3.5-super-vl")
    assert (trace["calls"], trace["prompt_tokens"], trace["completion_tokens"]) == (4, 400, 40)
    assert trace["seconds"] == 6.0 and trace["thinking"] is False and trace["attempts"] == 1
    tools = [s["tool"] for s in trace["steps"]]
    assert tools == ["search_products", "get_offer", "simulate_order", "request_approval"]
    search, offer, simulate, approval = trace["steps"]
    assert search["query"] == "lactose-free milk" and search["count"] == 1 and search["by"] == "model"
    assert offer["products"] == 1
    assert simulate["code"] == "NEEDS_APPROVAL"
    assert approval["code"] == "PENDING"
    assert replay["model_trace"] == trace
    # Stored with the run, through store/ (db.agent_runs), and served on the proposal later.
    row = db.agent_runs.find_one({})
    assert row["result"]["model_trace"] == trace
    served = next(p for p in listed["proposals"] if p["proposal_id"] == proposal["proposal_id"])
    assert served["model_trace"] == trace and one["model_trace"] == trace


def test_the_trace_holds_no_prompt_no_model_text_and_no_key(monkeypatch):
    monkeypatch.setenv("VERDA_INFERENCE_KEY", "not-a-real-secret-key")
    _, proposal, *_ = run_worker(monkeypatch, MeteredBuyer())
    text = json.dumps(proposal["model_trace"])
    assert "not-a-real-secret" not in text and "test-agent-only" not in text
    assert "restaurant buyer" not in text and "51 L" not in text
    assert "offer_id" not in text and "price" not in text


class StopsFirstTime(MeteredBuyer):
    """The first attempt stops without a tool call; the second one finishes (#735)."""

    def __init__(self):
        super().__init__()
        self.stopped = False

    async def complete(self, messages, definitions):
        if not self.stopped:
            self.stopped = True
            self.meter.record("buyer", {"prompt_tokens": 50, "completion_tokens": 5}, 0.5)
            return {"role": "assistant", "content": "done"}
        return await super().complete(messages, definitions)


def test_a_run_started_again_counts_both_attempts(monkeypatch):
    _, proposal, *_ = run_worker(monkeypatch, StopsFirstTime(), key="trace-2")
    trace = proposal["model_trace"]
    assert trace["attempts"] == 2 and trace["calls"] == 5
    assert {s["attempt"] for s in trace["steps"]} == {2}


class RejectedFirst(MeteredBuyer):
    """A first call the policy refuses (wrong need): the step shows its reason code."""

    def __init__(self):
        super().__init__()
        self.bad = True

    async def complete(self, messages, definitions):
        if self.bad:
            self.bad = False
            self.meter.record("buyer", {}, 0.1)
            return tool("get_offer", product_ids=["462775"], requested_date="2026-11-16", need_id="other")
        return await super().complete(messages, definitions)


def test_a_policy_rejection_is_a_step_with_its_reason_code(monkeypatch):
    _, proposal, *_ = run_worker(monkeypatch, RejectedFirst(), key="trace-3")
    first = proposal["model_trace"]["steps"][0]
    assert first["tool"] == "get_offer" and first["code"] in ("NEED_MISMATCH", "UNKNOWN_ID")


def test_a_model_without_a_meter_still_gets_a_trace_with_zero_counts(monkeypatch):
    _, proposal, *_ = run_worker(monkeypatch, ScriptedBuyer(), key="trace-4")
    trace = proposal["model_trace"]
    assert trace["calls"] == 0 and trace["thinking"] is None and len(trace["steps"]) == 4


def test_a_search_found_by_meaning_is_marked_in_the_trace():
    """#1384: the gateway answered search "meaning-fallback"; the step says so with a code."""
    from agent.runner import Buyer
    buyer = Buyer(None, None, None, need_id="n1", requested_date="2026-11-16")
    buyer.record_step("search_products", {"query": "talon maito"},
                      {"products": [{"product_id": "462775"}], "search": "meaning-fallback"})
    buyer.record_step("search_products", {"query": "lactose-free milk"},
                      {"products": [{"product_id": "462775"}], "search": "text"})
    assert buyer.trace[0]["code"] == "MEANING_FALLBACK" and buyer.trace[0]["count"] == 1
    assert "code" not in buyer.trace[1]
