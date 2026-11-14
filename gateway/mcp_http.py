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

Stateless JSON responses: no server-side MCP session, so any worker can answer.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from contextvars import ContextVar

import httpx
from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from gateway.mcp_server import GatewayClient, build_server

PATH = "/mcp"
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
                body = b'{"error":{"code":"UNAUTHENTICATED","message":"the agent bearer token is required"}}'
                await send({"type": "http.response.start", "status": 401, "headers": [
                    (b"content-type", b"application/json"), (b"www-authenticate", b'Bearer realm="mcp"')]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


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
