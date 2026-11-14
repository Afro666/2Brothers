"""The Buyer loop's model settings are explicit (#706) and the prompt asks for one offer (#882)."""
import asyncio
import json

import httpx
import pytest

from agent import runner
from agent.model import BUYER_MAX_TOKENS, BUYER_THINKING, Nemotron, buyer_settings


def sent_bodies(monkeypatch, call, **env):
    """The request bodies the client sends for `call(model)`, with `env` set."""
    monkeypatch.setenv("VERDA_INFERENCE_KEY", "not-a-real-secret")
    monkeypatch.delenv("NEMOTRON_BUYER_THINKING", raising=False)
    monkeypatch.delenv("NEMOTRON_BUYER_MAX_TOKENS", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "{}"}}]})

    async def run():
        model = Nemotron(transport=httpx.MockTransport(handler))
        try:
            await call(model)
        finally:
            await model.close()
    asyncio.run(run())
    return bodies


def test_the_live_loop_runs_with_thinking_off_and_a_2048_token_reply_budget(monkeypatch):
    # The measured choice (agent/README.md, "Buyer loop settings"). Change it only with new numbers.
    assert (BUYER_THINKING, BUYER_MAX_TOKENS) == (False, 2048)
    body = sent_bodies(monkeypatch, lambda model: model.complete([], []))[0]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == 2048
    assert body["temperature"] == 0 and body["tool_choice"] == "auto"


def test_the_server_can_set_thinking_and_the_budget(monkeypatch):
    body = sent_bodies(monkeypatch, lambda model: model.complete([], []),
                       NEMOTRON_BUYER_THINKING="on", NEMOTRON_BUYER_MAX_TOKENS="8192")[0]
    assert body["chat_template_kwargs"] == {"enable_thinking": True}
    assert body["max_tokens"] == 8192


def test_settings_reader():
    assert buyer_settings({}) == (False, 2048)
    assert buyer_settings({"NEMOTRON_BUYER_THINKING": " ON ", "NEMOTRON_BUYER_MAX_TOKENS": " 64000 "}) == (True, 64000)
    assert buyer_settings({"NEMOTRON_BUYER_THINKING": "off", "NEMOTRON_BUYER_MAX_TOKENS": ""}) == (False, 2048)


@pytest.mark.parametrize("env", [{"NEMOTRON_BUYER_THINKING": "maybe"}, {"NEMOTRON_BUYER_THINKING": "true"},
                                 {"NEMOTRON_BUYER_MAX_TOKENS": "0"}, {"NEMOTRON_BUYER_MAX_TOKENS": "100000"},
                                 {"NEMOTRON_BUYER_MAX_TOKENS": "2k"}, {"NEMOTRON_BUYER_MAX_TOKENS": "-5"}])
def test_a_setting_nobody_can_mean_is_refused(monkeypatch, env):
    with pytest.raises(ValueError):
        buyer_settings(env)
    monkeypatch.setenv("VERDA_INFERENCE_KEY", "not-a-real-secret")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        Nemotron(transport=httpx.MockTransport(lambda request: httpx.Response(500)))


def test_the_photo_readers_keep_their_own_settings(monkeypatch):
    body = sent_bodies(monkeypatch, lambda model: model.complete_json([], {"type": "object"}, "shelf_count"),
                       NEMOTRON_BUYER_THINKING="on", NEMOTRON_BUYER_MAX_TOKENS="8192")[0]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == 2048


def test_the_prompt_asks_for_one_offer_with_the_three_best_products():
    text = " ".join(runner.SYSTEM.split())
    assert "call get_offer ONCE" in text
    assert "three best matching products that have can_arrive true" in text
    assert "Do not ask for one offer per product" in text
    assert "simulate_order once" in text
