"""Remote MCP: the Buyer tools over streamable HTTP at /mcp (issue #280).

    claude mcp add --transport http kitchen-buyer https://<host>/mcp \
        --header "Authorization: Bearer $GATEWAY_AGENT_TOKEN"

The same tools as the stdio server (gateway/mcp_server.py), with the same descriptions
and guards. Who may use /mcp: the agent token, a kitchen API token with kitchen:propose,
and a personal approval token (one person's own chat, decision 2026-11-14). The shared
human token and a session cookie are refused. `tools/list` depends on the caller: the
agent and kitchen tokens see the eight Buyer tools and no approve, reject or cancel tool;
a personal approval token sees the read tools plus approve_proposal and reject_proposal,
and not the tools that propose. Each tool call goes through the gateway's own routes
in-process with the caller's token, so every refusal, the principal and the audit trail
are exactly those of the HTTP API.

Connector link (decision 2026-11-14 19:00 UTC, #1693): `/mcp/t/<token>` is the same MCP with
the path token as the bearer, for a personal approval token only, so a person pastes one
link into Claude's "Add custom connector" and edits no config file. Anything else there is
one identical 401. The token is in the URL, so every uvicorn log line masks it to its prefix.

Stateless JSON responses: no server-side MCP session, so any worker can answer.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from contextvars import ContextVar

import httpx
from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from gateway.mcp_server import GatewayClient, build_server

PATH = "/mcp"
TOKEN_PATH = PATH + "/t/"          # /mcp/t/<personal approval token>: the connector link (#1693)
SHOWN = 8                          # characters of a path token a log line keeps: the stored prefix
_IN_PATH = re.compile(r"(/mcp/t/)([^/\s?#\"']*)")
_UNAUTHENTICATED = b'{"error":{"code":"UNAUTHENTICATED","message":"the agent bearer token is required"}}'


def mask_path_token(text: str) -> str:
    """`/mcp/t/tka_abcdefgh...` -> `/mcp/t/tka_abcd...`: never the whole token in a log line."""
    return _IN_PATH.sub(lambda m: m.group(1) + m.group(2)[:SHOWN] + ("..." if len(m.group(2)) > SHOWN else ""), text)


class MaskPathToken(logging.Filter):
    """Masks /mcp/t/<token> in a record's message and its args (uvicorn's access formatter
    reads the args tuple, so the args stay a tuple of the same length). An arg that is not a
    str but prints the path (httpx passes a URL object) becomes its masked text."""

    @staticmethod
    def _arg(value):
        if isinstance(value, (int, float)) or value is None:
            return value
        text = value if isinstance(value, str) else str(value)
        return mask_path_token(text) if TOKEN_PATH in text else value

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_path_token(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self._arg(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: self._arg(v) for k, v in record.args.items()}
        return True


LOGGERS = ("uvicorn", "uvicorn.access", "uvicorn.error", "gateway", "httpx")


def install_log_mask() -> None:
    for name in LOGGERS:
        log = logging.getLogger(name)
        if not any(isinstance(f, MaskPathToken) for f in log.filters):
            log.addFilter(MaskPathToken())
# The caller's own token for this request: a kitchen API token keeps its kitchen and scopes
# all the way through the /tools routes (#271). Empty = the server agent token.
_CALLER: ContextVar[str] = ContextVar("mcp_caller_token", default="")
# True only while a verified personal approval token is the caller.
_PERSON: ContextVar[bool] = ContextVar("mcp_caller_is_person", default=False)


class AgentTokenGatewayClient(GatewayClient):
    """Calls the gateway app in-process with the agent token (never logged)."""

    def __init__(self, app: ASGIApp):
        super().__init__("http://gateway.internal", transport=httpx.ASGITransport(app=app))

    async def request(self, method, path, *, payload=None, params=None, headers=None):
        token = _CALLER.get() or os.environ.get("GATEWAY_AGENT_TOKEN", "")
        return await super().request(method, path, payload=payload, params=params,
                                     headers={**(headers or {}), "Authorization": "Bearer " + token})


class RequireAgentToken:
    """ASGI guard in front of the MCP endpoint: 401 without the agent bearer token."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith(TOKEN_PATH):
            await self._path_token(scope, receive, send)
            return
        if scope["type"] == "http" and scope["path"].rstrip("/") == PATH:
            from gateway.app import _token_matches  # one token check for the whole gateway
            auth = dict(scope.get("headers") or []).get(b"authorization", b"").decode("latin-1")
            token = auth[7:] if auth.lower().startswith("bearer ") else ""
            allowed = bool(token) and _token_matches(token, "GATEWAY_AGENT_TOKEN")
            state = getattr(scope.get("app"), "state", None)
            if not allowed and token.startswith("tka_"):
                # A personal approval token: one person's own chat (gateway/approval_tokens.py).
                verify_person = getattr(state, "verify_approval_token", None)
                if verify_person is not None and verify_person(token) is not None:
                    reset, person = _CALLER.set(token), _PERSON.set(True)
                    try:
                        await self.app(scope, receive, send)
                    finally:
                        _PERSON.reset(person)
                        _CALLER.reset(reset)
                    return
            elif not allowed and token:
                # A kitchen API token with kitchen:propose may drive the Buyer tools (#271).
                verify = getattr(state, "verify_token", None)
                doc = verify(token) if verify else None
                if doc is not None and "kitchen:propose" in doc["scopes"]:
                    allowed = True
                    reset = _CALLER.set(token)
                    try:
                        await self.app(scope, receive, send)
                    finally:
                        _CALLER.reset(reset)
                    return
            if not allowed:
                await _unauthenticated(send, _UNAUTHENTICATED)
                return
        await self.app(scope, receive, send)

    async def _path_token(self, scope: Scope, receive: Receive, send: Send) -> None:
        """/mcp/t/<token>: a personal approval token only; any other caller, the same 401."""
        token = scope["path"][len(TOKEN_PATH):].rstrip("/")
        state = getattr(scope.get("app"), "state", None)
        verify_person = getattr(state, "verify_approval_token", None)
        if ("/" in token or not token.startswith("tka_") or verify_person is None
                or verify_person(token) is None):
            await _unauthenticated(send, b'{"error":{"code":"UNAUTHENTICATED","message":"unauthenticated"}}',
                                   challenge=False)
            return
        # The MCP app below sees a plain /mcp request; a header token never overrides the path's.
        inner = {**scope, "path": PATH, "raw_path": PATH.encode(),
                 "headers": [(k, v) for k, v in scope.get("headers") or [] if k.lower() != b"authorization"]}
        reset, person = _CALLER.set(token), _PERSON.set(True)
        try:
            await self.app(inner, receive, send)
        finally:
            _PERSON.reset(person)
            _CALLER.reset(reset)


async def _unauthenticated(send: Send, body: bytes, challenge: bool = True) -> None:
    headers = [(b"content-type", b"application/json")]
    if challenge:
        headers.append((b"www-authenticate", b'Bearer realm="mcp"'))
    await send({"type": "http.response.start", "status": 401, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def mount_mcp(app: FastAPI) -> None:
    """Add /mcp to the gateway app and run the MCP session manager in its lifespan."""
    server = build_server(AgentTokenGatewayClient(app), is_person=_PERSON.get)
    server.settings.streamable_http_path = PATH
    server.settings.stateless_http = True
    server.settings.json_response = True
    server.settings.transport_security = None  # the gateway's own host/TLS settings apply
    mcp_app = server.streamable_http_app()
    app.router.routes.extend(mcp_app.routes)
    app.state.mcp = server

    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a):
        async with server.session_manager.run():
            async with previous(a) as state:
                yield state

    app.router.lifespan_context = lifespan
    app.add_middleware(RequireAgentToken)
    install_log_mask()
