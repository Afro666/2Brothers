"""Remote MCP: the Buyer tools over streamable HTTP at /mcp (issue #280).

    claude mcp add --transport http kitchen-buyer https://<host>/mcp \
        --header "Authorization: Bearer $GATEWAY_AGENT_TOKEN"

The same seven tools as the stdio server (gateway/mcp_server.py), with the same
descriptions and guards; approve, reject and cancel are never exposed. Only the
agent token may use /mcp: a human token is refused, because the Buyer is an agent
and a person approves in the inbox, not through MCP. Each tool call goes through the
gateway's own /tools routes in-process with the agent token, so every refusal, the
principal and the audit trail are exactly those of the HTTP API.

Stateless JSON responses: no server-side MCP session, so any worker can answer.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from gateway.mcp_server import GatewayClient, build_server

PATH = "/mcp"


class AgentTokenGatewayClient(GatewayClient):
    """Calls the gateway app in-process with the agent token (never logged)."""

    def __init__(self, app: ASGIApp):
        super().__init__("http://gateway.internal", transport=httpx.ASGITransport(app=app))

    async def request(self, method, path, *, payload=None, params=None, headers=None):
        token = os.environ.get("GATEWAY_AGENT_TOKEN", "")
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
            if not (token and _token_matches(token, "GATEWAY_AGENT_TOKEN")):
                body = b'{"error":{"code":"UNAUTHENTICATED","message":"the agent bearer token is required"}}'
                await send({"type": "http.response.start", "status": 401, "headers": [
                    (b"content-type", b"application/json"), (b"www-authenticate", b'Bearer realm="mcp"')]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


def mount_mcp(app: FastAPI) -> None:
    """Add /mcp to the gateway app and run the MCP session manager in its lifespan."""
    server = build_server(AgentTokenGatewayClient(app))
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
