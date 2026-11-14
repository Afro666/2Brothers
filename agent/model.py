"""Small OpenAI-compatible Verda inference client with bounded read retries."""
import asyncio
import os
import time

import httpx

from agent.usage import Meter


class ModelError(RuntimeError):
    pass


# The Buyer tool loop's model settings (#706), measured on 2026-11-14: agent/README.md,
# "Buyer loop settings". Thinking is off: with thinking on, 5 of 346 model calls spent the
# whole reply budget on reasoning and returned no tool call, so the run stopped.
BUYER_THINKING = False
BUYER_MAX_TOKENS = 2048


def buyer_settings(environ=None) -> tuple[bool, int]:
    """(thinking, reply budget) for the Buyer loop. The server can override the constants
    with NEMOTRON_BUYER_THINKING (on/off) and NEMOTRON_BUYER_MAX_TOKENS (256 to 65536).
    A value outside those is an error: the loop never runs on a setting nobody chose."""
    environ = os.environ if environ is None else environ
    thinking = (environ.get("NEMOTRON_BUYER_THINKING") or "").strip().lower()
    if thinking not in ("", "on", "off"):
        raise ValueError("NEMOTRON_BUYER_THINKING must be on or off")
    budget = (environ.get("NEMOTRON_BUYER_MAX_TOKENS") or "").strip()
    if budget and not (budget.isdecimal() and 256 <= int(budget) <= 65536):
        raise ValueError("NEMOTRON_BUYER_MAX_TOKENS must be a whole number from 256 to 65536")
    return (thinking == "on" if thinking else BUYER_THINKING,
            int(budget) if budget else BUYER_MAX_TOKENS)


class Nemotron:
    def __init__(self, *, transport=None, sleep=asyncio.sleep):
        key = os.environ.get("VERDA_INFERENCE_KEY", "")
        if not key:
            raise ValueError("VERDA_INFERENCE_KEY is required")
        self.http = httpx.AsyncClient(
            base_url="https://containers.datacrunch.io/nemotron-3-5-super-vl-b300/v1/",
            headers={"Authorization": "Bearer " + key}, transport=transport,
            timeout=90, follow_redirects=False, trust_env=False)
        self.sleep = sleep
        self.thinking, self.max_tokens = buyer_settings()
        self.meter = Meter()    # calls, tokens and seconds per role (agent/usage.py)

    async def close(self):
        await self.http.aclose()

    async def complete(self, messages, tools):
        body = {"model": "nemotron-3.5-super-vl", "messages": messages,
                "tools": tools, "tool_choice": "auto", "temperature": 0,
                "max_tokens": self.max_tokens,
                # Always sent: the endpoint's default is thinking on (seen 2026-11-14).
                "chat_template_kwargs": {"enable_thinking": self.thinking}}
        return await self._post(body, "buyer")

    async def complete_json(self, messages, schema, name, *, max_tokens=2048, role=None):
        """One structured reply: the server constrains the output to `schema` (strict).
        Thinking is off; the caller still validates the parsed object. Metered under `role`,
        by default `vl_<name>` (the vision readers)."""
        body = {"model": "nemotron-3.5-super-vl", "messages": messages, "temperature": 0,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": name, "schema": schema, "strict": True}},
                "chat_template_kwargs": {"enable_thinking": False}}
        return await self._post(body, role or "vl_" + name)

    async def _post(self, body, role):
        """One model call for `role`, metered: a failed call counts too, with no tokens."""
        started, usage, ok = time.monotonic(), None, False
        try:
            message, usage = await self._send(body)
            ok = True
            return message
        finally:
            self.meter.record(role, usage, time.monotonic() - started, ok=ok)

    async def _send(self, body):
        for attempt in range(3):
            try:
                response = await self.http.post("chat/completions", json=body)
            except httpx.HTTPError:
                if attempt == 2:
                    raise ModelError("Nemotron network request failed") from None
                await self.sleep(0.5 * 2**attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    await self.sleep(0.5 * 2**attempt)
                    continue
            if response.status_code != 200:
                raise ModelError(f"Nemotron HTTP {response.status_code}")
            try:
                reply = response.json()
                message = reply["choices"][0]["message"]
                if not isinstance(message, dict):
                    raise ValueError()
                return ({k: v for k, v in message.items() if k in ("role", "content", "tool_calls")},
                        reply.get("usage"))
            except (ValueError, KeyError, IndexError, TypeError):
                raise ModelError("Nemotron returned an invalid completion") from None
        raise AssertionError("unreachable")
