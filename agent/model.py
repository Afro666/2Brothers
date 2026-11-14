"""Small OpenAI-compatible Verda inference client with bounded read retries."""
import asyncio
import os

import httpx


class ModelError(RuntimeError):
    pass


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

    async def close(self):
        await self.http.aclose()

    async def complete(self, messages, tools):
        body = {"model": "nemotron-3.5-super-vl", "messages": messages,
                "tools": tools, "tool_choice": "auto", "temperature": 0,
                "max_tokens": 2048}
        return await self._post(body)

    async def complete_json(self, messages, schema, name, *, max_tokens=2048):
        """One structured reply: the server constrains the output to `schema` (strict).
        Thinking is off; the caller still validates the parsed object."""
        body = {"model": "nemotron-3.5-super-vl", "messages": messages, "temperature": 0,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": name, "schema": schema, "strict": True}},
                "chat_template_kwargs": {"enable_thinking": False}}
        return await self._post(body)

    async def _post(self, body):
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
                message = response.json()["choices"][0]["message"]
                if not isinstance(message, dict):
                    raise ValueError()
                return {k: v for k, v in message.items() if k in ("role", "content", "tool_calls")}
            except (ValueError, KeyError, IndexError, TypeError):
                raise ModelError("Nemotron returned an invalid completion") from None
        raise AssertionError("unreachable")
