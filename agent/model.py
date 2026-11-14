"""Small OpenAI-compatible Verda inference client with bounded read retries."""
import asyncio
import os
import time
from urllib.parse import urlsplit

import httpx

from agent.usage import Meter


class ModelError(RuntimeError):
    def __init__(self, message, *, status_code=None):
        super().__init__(message)
        self.status_code = status_code


# The Buyer tool loop's model settings (#706), measured on 2026-11-14: agent/README.md,
# "Buyer loop settings". Thinking is off: with thinking on, 5 of 346 model calls spent the
# whole reply budget on reasoning and returned no tool call, so the run stopped.
BUYER_THINKING = False
BUYER_MAX_TOKENS = 2048

DEFAULT_BASE_URL = 'https://containers.datacrunch.io/nemotron-3-5-super-vl-b300/v1/'
DEFAULT_MODEL = 'nemotron-3.5-super-vl'


def provider_settings(environ=None):
    """The shared Nemotron route; operator overrides never trigger a fallback."""
    environ = os.environ if environ is None else environ
    key = environ.get('VERDA_INFERENCE_KEY', '')
    if not key:
        raise ValueError('VERDA_INFERENCE_KEY is required')
    base = (environ.get('NEMOTRON_BASE_URL') or DEFAULT_BASE_URL).strip().rstrip('/') + '/'
    model = (environ.get('NEMOTRON_MODEL') or DEFAULT_MODEL).strip()
    try:
        url = urlsplit(base)
        valid = (url.hostname and not url.username and not url.password and not url.query and not url.fragment
                 and (url.scheme == 'https' or (url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1', '::1'))))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('NEMOTRON_BASE_URL must be an HTTPS base URL without credentials, query or fragment')
    if not model or any(c.isspace() for c in model) or key in model:
        raise ValueError('NEMOTRON_MODEL must be a model identifier')
    return base, model, key


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
    def __init__(self, *, transport=None, sleep=asyncio.sleep, timeout=90, max_attempts=3):
        base, self.model, key = provider_settings()
        if max_attempts not in (1, 2, 3):
            raise ValueError('max_attempts must be 1 to 3')
        self.max_attempts = max_attempts
        # Read before the client opens, so a bad setting leaks nothing. Fail-fast on purpose:
        # a bad Buyer setting stops every reader (photo readers too) until it is fixed.
        self.thinking, self.max_tokens = buyer_settings()
        self.http = httpx.AsyncClient(
            base_url=base,
            headers={"Authorization": "Bearer " + key}, transport=transport,
            timeout=timeout, follow_redirects=False, trust_env=False)
        self.sleep = sleep
        self.meter = Meter()    # calls, tokens and seconds per role (agent/usage.py)

    async def close(self):
        await self.http.aclose()

    async def complete(self, messages, tools):
        body = {"model": self.model, "messages": messages,
                "tools": tools, "tool_choice": "auto", "temperature": 0,
                "max_tokens": self.max_tokens,
                # Always sent: the endpoint's default is thinking on (seen 2026-11-14).
                "chat_template_kwargs": {"enable_thinking": self.thinking}}
        return await self._post(body, "buyer")

    async def complete_json(self, messages, schema, name, *, max_tokens=2048, role=None):
        """One structured reply: the server constrains the output to `schema` (strict).
        Thinking is off; the caller still validates the parsed object. Metered under `role`,
        by default `vl_<name>` (the vision readers)."""
        body = {"model": self.model, "messages": messages, "temperature": 0,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": name, "schema": schema, "strict": True}},
                "chat_template_kwargs": {"enable_thinking": False}}
        return await self._post(body, role or "vl_" + name)

    async def ping(self):
        """A real minimal generation, not GET /models (absent on some containers)."""
        message = await self._post({'model': self.model, 'messages': [{'role': 'user', 'content': 'Reply with OK.'}],
                                    'temperature': 0, 'max_tokens': 16,
                                    'chat_template_kwargs': {'enable_thinking': False}}, 'health')
        if not isinstance(message.get('content'), str) or not message['content'].strip():
            raise ModelError('Nemotron returned an empty health reply')
        return message

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
        for attempt in range(self.max_attempts):
            try:
                response = await self.http.post("chat/completions", json=body)
            except httpx.HTTPError:
                if attempt == self.max_attempts - 1:
                    raise ModelError("Nemotron network request failed") from None
                await self.sleep(0.5 * 2**attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.max_attempts - 1:
                    await self.sleep(0.5 * 2**attempt)
                    continue
            if response.status_code != 200:
                raise ModelError(f"Nemotron HTTP {response.status_code}", status_code=response.status_code)
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
