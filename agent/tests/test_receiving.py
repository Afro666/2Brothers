import asyncio
from copy import deepcopy
import json

import httpx
import pytest

from agent.model import Nemotron
from agent.receiving import FIXTURES, NOTE_SCHEMA, RecordedModel, main, match_delivery, receive
from agent.vision import VisionError, image_part, parse_reply

ORDER = json.loads((FIXTURES / "order.json").read_text(encoding="utf-8"))


def recorded(name):
    return json.loads((FIXTURES / f"{name}.reply.json").read_text(encoding="utf-8"))


def note(name):
    return parse_reply(recorded(name), NOTE_SCHEMA)


def run(name, reply=None):
    model = RecordedModel(reply or recorded(name))
    return asyncio.run(receive(FIXTURES / f"{name}.png", ORDER, model)), model


def test_short_note_gives_missing_quantity_and_changes_next_milk_proposal():
    full, _ = run("complete")
    short, model = run("short")
    assert full["complete"] and full["lines"][0]["status"] == "RECEIVED"
    [line] = short["lines"]
    assert (line["status"], line["ordered"], line["received"], line["missing"]) == ("SHORT", "51", "36", "15")
    [sub] = short["not_ordered"]
    assert (sub["status"], sub["product_id"], sub["replaces"], sub["received"]) == ("SUBSTITUTE", "462921", "462775", "10")
    assert sub["needs_approval"] is True
    assert (full["stock"]["462775"], short["stock"]["462775"]) == ("51", "36")
    assert (full["next"]["462775"]["quantity"], short["next"]["462775"]["quantity"]) == ("0", "4")
    # The photo and the strict schema went to the model.
    [request] = model.requests
    image = request["messages"][1]["content"][1]["image_url"]["url"]
    assert image.startswith("data:image/png;base64,") and request["schema"] is NOTE_SCHEMA


def test_unreadable_best_before_stays_unknown():
    full, _ = run("complete")
    lots = full["lines"][0]["lots"]
    assert [lot["best_before"] for lot in lots] == ["2026-11-28", "unknown"]


def test_unknown_quantity_is_never_guessed():
    reply = deepcopy(note("short"))
    reply["lines"][0]["quantity"] = "unknown"
    result, _ = run("short", {"role": "assistant", "content": json.dumps(reply)})
    line = result["lines"][0]
    assert line["status"] == "UNKNOWN" and line["missing"] is None and line["received"] is None
    assert result["stock"]["462775"] is None
    assert "STOCK_COUNT_MISSING" in result["next"]["462775"]["reason_codes"]


def test_unreadable_code_makes_an_absent_line_unknown_not_missing():
    reply = deepcopy(note("complete"))
    for line in reply["lines"]:
        line["product_code"] = "unknown"
    result = match_delivery(ORDER, reply)
    assert result["lines"][0]["status"] == "UNKNOWN"
    assert {row["status"] for row in result["not_ordered"]} == {"UNREADABLE"}
    reply["lines"] = []
    assert match_delivery(ORDER, reply)["lines"][0]["status"] == "MISSING"


@pytest.mark.parametrize("content", [
    "not json",
    json.dumps({"order_ref": "x", "delivery_date": "2026-11-16"}),
    json.dumps({**note("short"), "approve": True}),
    json.dumps({**note("short"), "lines": [{**note("short")["lines"][0], "quantity": "about 40"}]}),
])
def test_reply_outside_the_schema_is_refused_whole(content):
    with pytest.raises(VisionError):
        run("short", {"role": "assistant", "content": content})


def test_only_png_or_jpeg_photos():
    with pytest.raises(VisionError):
        image_part(b"%PDF-1.7")
    with pytest.raises(VisionError):
        image_part(b"")


def test_nemotron_request_is_strict_json_with_thinking_off(monkeypatch):
    monkeypatch.setenv("VERDA_INFERENCE_KEY", "test-only-key")
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": recorded("short")}]})

    async def go():
        model = Nemotron(transport=httpx.MockTransport(handler))
        try:
            return await receive(FIXTURES / "short.png", ORDER, model)
        finally:
            await model.close()
    result = asyncio.run(go())
    assert result["lines"][0]["missing"] == "15"
    assert seen["response_format"]["type"] == "json_schema"
    assert seen["response_format"]["json_schema"]["strict"] is True
    assert seen["chat_template_kwargs"] == {"enable_thinking": False}
    assert "tools" not in seen


def test_cli_offline(capsys):
    assert main([str(FIXTURES / "short.png")]) == 0
    out = capsys.readouterr().out
    assert "SHORT      462775" in out and "missing 15" in out and "next suggestion: 4 ST" in out
