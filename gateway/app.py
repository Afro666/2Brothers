"""HTTP gateway (FastAPI). Routes from docs/contract.md; logic lives in gateway/service.py.

Auth (demo): two bearer tokens from the server's environment.
- GATEWAY_AGENT_TOKEN: the Buyer agent and other services. Can read, propose and use the
  /tools routes. Can never approve.
- GATEWAY_HUMAN_TOKEN: the web app's signed-in person; `X-User` names who. Only this
  token may approve or reject (403 HUMAN_SESSION_REQUIRED otherwise).
Run: `two-brothers-gateway` (uvicorn on 0.0.0.0:8000). Never logs keys or bodies.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from gateway.service import Gateway, GatewayError

DEFAULT_KITCHEN = "demo-kitchen"


class Principal:
    def __init__(self, kind: str, name: str):
        self.kind, self.name = kind, name

    @property
    def human(self) -> str | None:
        return self.name if self.kind == "human" else None


def _token_matches(given: str, env: str) -> bool:
    expected = os.environ.get(env, "")
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def principal(request: Request) -> Principal:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else ""
    if token and _token_matches(token, "GATEWAY_HUMAN_TOKEN"):
        user = (request.headers.get("x-user") or "").strip()[:100]
        if not user:
            raise GatewayError(401, "UNAUTHENTICATED", "X-User names the person")
        return Principal("human", user)
    if token and _token_matches(token, "GATEWAY_AGENT_TOKEN"):
        return Principal("agent", "buyer-agent")
    raise GatewayError(401, "UNAUTHENTICATED", "a valid bearer token is required")


def create_app(gateway: Gateway | None = None, *, buyer_worker=None) -> FastAPI:
    app = FastAPI(title="Trusted Kitchen Buyer gateway", version="0.1.0")
    state: dict[str, Gateway] = {}

    def gw() -> Gateway:
        if gateway is not None:
            return gateway
        if "gw" not in state:
            from gateway.valio_client import ValioClient
            from store.db import get_db
            state["gw"] = Gateway(get_db(), ValioClient())
        return state["gw"]

    @app.exception_handler(GatewayError)
    async def _error(_: Request, exc: GatewayError) -> JSONResponse:
        return JSONResponse(status_code=exc.status,
                            content={"error": {"code": exc.code, "message": exc.message, **exc.extra}})

    @app.exception_handler(ValueError)
    async def _invalid(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": {"code": "INVALID_REQUEST", "message": str(exc)[:200]}})

    async def body(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except ValueError:
            raise GatewayError(422, "INVALID_JSON", "body must be a JSON object") from None
        if not isinstance(data, dict):
            raise GatewayError(422, "INVALID_JSON", "body must be a JSON object")
        return data

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # ---- kitchen side -------------------------------------------------------------
    k = "/v1/kitchens/{kitchen_id}"

    @app.post(k + "/proposals")
    async def create_proposal(kitchen_id: str, request: Request, who: Principal = Depends(principal)):
        data = await body(request)
        if 'text' in data and 'product_ids' not in data:
            from gateway.buyer_worker import run_buyer
            return await (buyer_worker or run_buyer)(kitchen_id, data)
        return gw().create_proposal(kitchen_id, data, who.name)

    @app.get(k + "/proposals")
    def list_proposals(kitchen_id: str, who: Principal = Depends(principal)):
        return {"proposals": gw().list_proposals(kitchen_id)}

    @app.get(k + "/proposals/{proposal_id}")
    def get_proposal(kitchen_id: str, proposal_id: str, who: Principal = Depends(principal)):
        return gw().get_proposal(kitchen_id, proposal_id)

    @app.get(k + "/proposals/{proposal_id}/addable")
    def addable(kitchen_id: str, proposal_id: str, who: Principal = Depends(principal)):
        return gw().addable(kitchen_id, proposal_id)

    @app.post(k + "/proposals/{proposal_id}/approve")
    async def approve(kitchen_id: str, proposal_id: str, request: Request, who: Principal = Depends(principal)):
        return gw().approve(kitchen_id, proposal_id, await body(request), human=who.human)

    @app.post(k + "/proposals/{proposal_id}/reject")
    async def reject(kitchen_id: str, proposal_id: str, request: Request, who: Principal = Depends(principal)):
        return gw().reject(kitchen_id, proposal_id, await body(request), human=who.human)

    @app.post(k + "/needs")
    async def create_need(kitchen_id: str, request: Request, who: Principal = Depends(principal)):
        return gw().create_need(kitchen_id, await body(request), who.name)

    @app.get(k + "/orders")
    def list_orders(kitchen_id: str, who: Principal = Depends(principal)):
        return {"orders": gw().list_orders(kitchen_id)}

    @app.get(k + "/orders/{order_id}")
    def get_order(kitchen_id: str, order_id: str, who: Principal = Depends(principal)):
        return gw().get_order(kitchen_id, order_id)

    @app.get(k + "/audit")
    def audit(kitchen_id: str, who: Principal = Depends(principal)):
        return {"events": gw().audit_log(kitchen_id)}

    # ---- Buyer agent tools (one kitchen per agent token in the demo) ----------------
    def kitchen() -> str:
        return os.environ.get("GATEWAY_KITCHEN_ID", DEFAULT_KITCHEN)

    @app.post("/tools/search_products")
    async def search(request: Request, who: Principal = Depends(principal)):
        from store.search import search_products
        data = await body(request)
        limit = data.get("limit", 20)
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            raise GatewayError(422, "INVALID_REQUEST", "limit: 1 to 50")
        return {"products": search_products(gw().db, data.get("query") or "", data.get("filters") or {}, limit)}

    @app.post("/tools/get_offer")
    async def get_offer(request: Request, who: Principal = Depends(principal)):
        return gw().tool_get_offer(kitchen(), await body(request))

    @app.post("/tools/simulate_order")
    async def simulate(request: Request, who: Principal = Depends(principal)):
        return gw().tool_simulate(kitchen(), await body(request))

    @app.post("/tools/request_approval")
    async def request_approval(request: Request, who: Principal = Depends(principal)):
        return gw().tool_request_approval(kitchen(), await body(request), who.name)

    @app.post("/tools/place_order")
    async def place_order(request: Request, who: Principal = Depends(principal)):
        return gw().tool_place_order(kitchen(), await body(request))

    @app.get("/tools/get_order_status")
    def order_status(order_id: str, who: Principal = Depends(principal)):
        order = gw().get_order(kitchen(), order_id)
        return {"order_id": order["order_id"], "status": order["status"], "outcome": order["outcome"]}

    @app.get("/tools/get_audit_log")
    def audit_tool(run_id: str, who: Principal = Depends(principal)):
        from store.audit import list_events
        return {"events": [e["event"] for e in list_events(gw().db, run_id=run_id)]}

    @app.post("/audit/events")
    async def audit_ingest(request: Request, who: Principal = Depends(principal)):
        from store.audit import AuditConflict, append_event
        event = await body(request)
        try:
            entry = append_event(gw().db, event, {"kitchen_id": kitchen(), "principal": who.name})
        except AuditConflict:
            raise GatewayError(409, "IDEMPOTENCY_CONFLICT", "event_id reused with other content") from None
        return {"event_id": entry["event"]["event_id"], "stored": True}

    # Remote MCP (#280): the same Buyer tools over HTTP at /mcp, agent token only.
    from gateway.mcp_http import mount_mcp
    mount_mcp(app)
    return app


def main() -> None:
    import uvicorn
    uvicorn.run("gateway.app:create_app", factory=True, host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")), access_log=False)
