"""Token meter (#365): counts come from the endpoint's `usage`, per role, with a fake transport."""
import asyncio
import json

import httpx
import pytest

from agent.model import ModelError, Nemotron
from agent.service import BuyerWorker
from agent.tests.test_service import NOW, ScriptedBuyer, environment
from agent.usage import MARK, Meter, collect, emit, main, read_usage, table

USAGE = {"prompt_tokens": 272, "total_tokens": 381, "completion_tokens": 109,
         "prompt_tokens_details": None, "completion_tokens_details": {"reasoning_tokens": 79}}


def nemotron(monkeypatch, handler):
    monkeypatch.setenv("VERDA_INFERENCE_KEY", "not-a-real-secret")
    async def no_sleep(delay):
        pass
    return Nemotron(transport=httpx.MockTransport(handler), sleep=no_sleep)


def reply(message=None, usage=USAGE):
    body = {"choices": [{"message": message or {"role": "assistant", "content": "ok"}}]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def test_read_usage_takes_the_endpoint_fields_and_never_guesses():
    assert read_usage(USAGE) == {"prompt_tokens": 272, "completion_tokens": 109, "reasoning_tokens": 79}
    assert read_usage({"prompt_tokens": 5, "completion_tokens": 2}) == {
        "prompt_tokens": 5, "completion_tokens": 2, "reasoning_tokens": 0}
    for bad in (None, "x", [], {"prompt_tokens": "9", "completion_tokens": -1, "completion_tokens_details": 3},
                {"prompt_tokens": True}):
        assert read_usage(bad) == {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0}


def test_model_meters_each_role_from_the_reply_usage(monkeypatch):
    async def run():
        model = nemotron(monkeypatch, lambda request: reply())
        try:
            await model.complete([], [])
            await model.complete([], [])
            await model.complete_json([], {"type": "object"}, "shelf_count")
        finally:
            await model.close()
        return model.meter
    meter = asyncio.run(run())
    assert set(meter.roles) == {"buyer", "vl_shelf_count"}
    buyer = meter.roles["buyer"]
    assert (buyer["calls"], buyer["failed"]) == (2, 0)
    assert (buyer["prompt_tokens"], buyer["completion_tokens"], buyer["reasoning_tokens"]) == (544, 218, 158)
    assert buyer["seconds"] >= 0
    assert meter.roles["vl_shelf_count"]["calls"] == 1
    total = meter.total()
    assert (total["calls"], total["prompt_tokens"], total["completion_tokens"]) == (3, 816, 327)


def test_failed_call_is_counted_without_tokens_and_reply_without_usage_counts_zero(monkeypatch):
    async def run():
        replies = [httpx.Response(401), reply(usage=None)]
        model = nemotron(monkeypatch, lambda request: replies.pop(0))
        try:
            with pytest.raises(ModelError):
                await model.complete([], [])
            assert (await model.complete([], []))["content"] == "ok"
        finally:
            await model.close()
        return model.meter.roles["buyer"]
    row = asyncio.run(run())
    assert (row["calls"], row["failed"]) == (2, 1)
    assert (row["prompt_tokens"], row["completion_tokens"], row["reasoning_tokens"]) == (0, 0, 0)


def test_retried_call_is_one_call(monkeypatch):
    async def run():
        replies = [httpx.Response(503), reply()]
        model = nemotron(monkeypatch, lambda request: replies.pop(0))
        try:
            await model.complete([], [])
        finally:
            await model.close()
        return model.meter.roles["buyer"]
    row = asyncio.run(run())
    assert (row["calls"], row["failed"], row["prompt_tokens"]) == (1, 0, 272)


def test_worker_proposal_carries_the_run_usage_and_writes_one_usage_line(monkeypatch, tmp_path, capsys):
    log = tmp_path / "logs" / "usage.jsonl"
    monkeypatch.setenv("NEMOTRON_USAGE_LOG", str(log))
    script = ScriptedBuyer()

    async def handler(request):
        sent = json.loads(request.content)
        return reply(await script.complete(sent["messages"], sent["tools"]))

    async def run():
        db, gateway = environment(monkeypatch)
        worker = BuyerWorker(db, gateway, model_factory=lambda: nemotron(monkeypatch, handler), now=lambda: NOW)
        body = {"text": "51 L milk", "requested_date": "2026-11-16", "idempotency_key": "usage-1"}
        try:
            proposal = await worker.run("demo-kitchen", body)
            assert await worker.run("demo-kitchen", body) == proposal    # a replay calls no model
            return proposal
        finally:
            await gateway.close()
    proposal = asyncio.run(run())
    usage = proposal["buyer_usage"]
    assert (usage["calls"], usage["failed"]) == (4, 0)
    assert (usage["prompt_tokens"], usage["completion_tokens"], usage["reasoning_tokens"]) == (1088, 436, 316)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].startswith(MARK)
    record = json.loads(lines[0][len(MARK):])
    assert (record["run"], record["status"]) == ("buyer", "READY")
    assert (record["thinking"], record["max_tokens"]) == (False, 2048)    # the settings the run used (#706)
    assert record["roles"]["buyer"]["calls"] == 4
    assert "not-a-real-secret" not in lines[0] and "milk" not in lines[0]
    assert capsys.readouterr().err.count(MARK) == 1


def test_emit_skips_an_empty_meter_and_a_model_without_one(capsys):
    emit(Meter(), run="buyer")
    emit(None, run="buyer")
    assert capsys.readouterr().err == ""


def test_emit_never_raises_on_a_value_json_cannot_write(capsys):
    meter = Meter()
    meter.record("buyer", USAGE, 1.0)
    emit(meter, run=object())
    err = capsys.readouterr().err
    assert err.startswith(MARK) and json.loads(err[len(MARK):])["roles"]["buyer"]["calls"] == 1


def test_collect_sums_usage_lines_and_skips_other_log_lines():
    meter = Meter()
    meter.record("buyer", USAGE, 1.5)
    meter.record("vl_shelf_count", {"prompt_tokens": 2000, "completion_tokens": 150}, 2.25)
    line = MARK + json.dumps({"run": "buyer", "roles": meter.roles})
    roles, runs = collect(["INFO: started", "buyer-1  | " + line, line, MARK + "{not json", MARK + '{"roles": 3}'])
    assert runs == 2
    assert roles["buyer"] == {"calls": 2, "failed": 0, "prompt_tokens": 544, "completion_tokens": 218,
                              "reasoning_tokens": 158, "seconds": 3.0}
    text = table(roles, runs)
    assert "| buyer | 2 | 0 | 544 | 218 | 158 | 3.0 |" in text
    assert "| all | 4 | 0 | 4544 | 518 | 158 | 7.5 |" in text
    assert "2 run(s), 5062 tokens in all." in text


def test_cli_reads_files(tmp_path, capsys):
    meter = Meter()
    meter.record("buyer", USAGE, 1.0)
    path = tmp_path / "usage.jsonl"
    path.write_text(MARK + json.dumps({"roles": meter.roles}) + "\n", encoding="utf-8")
    assert main([str(path), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["runs"] == 1 and out["roles"]["buyer"]["prompt_tokens"] == 272
