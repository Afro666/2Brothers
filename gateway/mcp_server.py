"""Seven MCP tools backed by the team gateway HTTP contract."""
from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
import os
import re
from typing import Annotated
from uuid import NAMESPACE_URL, uuid5

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

Identifier = Annotated[str, Field(min_length=1, max_length=200)]


class GatewayError(RuntimeError):
    pass


_ERROR_CODE = re.compile(r"[A-Z_]{1,40}")


def _error_code(response: httpx.Response) -> str | None:
    """Return the gateway's short error.code, or None. Never the raw body."""
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and _ERROR_CODE.fullmatch(code) else None


class GatewayClient:
    def __init__(self, base_url: str | None = None, *, transport=None, token=None):
        self.http = httpx.AsyncClient(
            base_url=(base_url or os.environ.get("GATEWAY_BASE_URL", "http://127.0.0.1:8000")).rstrip("/"),
            timeout=20, transport=transport, follow_redirects=False, trust_env=False,
            headers={"Authorization": "Bearer " + token} if token else {},
        )

    async def close(self):
        await self.http.aclose()

    async def request(self, method: str, path: str, *, payload=None, params=None, headers=None):
        try:
            response = await self.http.request(method, path, json=payload, params=params, headers=headers)
        except httpx.HTTPError:
            # No automatic retries: a mutation might have reached the gateway.
            raise GatewayError("Gateway transport failure; reconcile mutation status before retrying") from None
        if response.is_error or response.is_redirect:
            code = _error_code(response) if response.is_error else None
            status = f"{response.status_code} {code}" if code else str(response.status_code)
            raise GatewayError(f"Gateway HTTP {status}; check status before retrying mutations")
        try:
            result = response.json()
        except ValueError:
            raise GatewayError("Gateway returned invalid JSON") from None
        if not isinstance(result, dict):
            raise GatewayError("Gateway returned a non-object response")
        return result


def build_server(gateway: GatewayClient) -> FastMCP:
    server = FastMCP("2Brothers purchasing gateway")
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

    @server.tool(annotations=read)
    async def search_products(query: Annotated[str, Field(min_length=1, max_length=1000)], filters: dict) -> dict:
        """Find catalog products. Missing allergen data is unknown, never safe. Do not invent quantities."""
        return await gateway.request("POST", "/tools/search_products", payload={"query": query, "filters": filters})

    @server.tool(annotations=read)
    async def get_offer(product_ids: Annotated[list[Identifier], Field(min_length=1, max_length=1000)],
                        requested_date: date, need_id: Identifier) -> dict:
        """Get an offer for the stored need. Next call simulate_order with its offer_id before request_approval. This call is not a simulation. Never invent quantities."""
        result = await gateway.request("POST", "/tools/get_offer", payload={
            "product_ids": product_ids, "requested_date": requested_date.isoformat(), "need_id": need_id})
        return {key: result.get(key) for key in ("offer_id", "valid_until", "lines")}

    @server.tool(annotations=read)
    async def simulate_order(offer_id: Identifier) -> dict:
        """Get exact total and mandate verdict before any order. NEEDS_APPROVAL requires a human; REFUSED stops."""
        return await gateway.request("POST", "/tools/simulate_order", payload={"offer_id": offer_id})

    @server.tool(annotations=write)
    async def place_order(offer_id: Identifier, expected_total: Annotated[str, Field(pattern=r"^\d+\.\d{2}$")],
                          idempotency_key: Identifier) -> dict:
        """Place only a simulated, authorized order with its exact total. Never approve or bypass mandate checks.

        After UNCONFIRMED or SENT_READ_FAILED reconcile status; never blindly resend.
        """
        if not Decimal(expected_total).is_finite():
            raise ValueError("expected_total must be finite")
        return await gateway.request("POST", "/tools/place_order", payload={
            "offer_id": offer_id, "expected_total": expected_total, "idempotency_key": idempotency_key})

    @server.tool(annotations=write)
    async def request_approval(offer_id: Identifier) -> dict:
        """Create a pending human decision for an offer. This does not approve, cancel, or release an order."""
        key = str(uuid5(NAMESPACE_URL, "2brothers-approval:" + offer_id))
        return await gateway.request("POST", "/tools/request_approval", payload={
            "offer_id": offer_id, "idempotency_key": key})

    @server.tool(annotations=read)
    async def get_order_status(order_id: Identifier) -> dict:
        """Read an existing order's status, including ambiguous outcomes. Never resend to recover a read failure."""
        return await gateway.request("GET", "/tools/get_order_status", params={"order_id": order_id})

    @server.tool(annotations=read)
    async def get_audit_log(run_id: Identifier) -> dict:
        """Read the run's audit events. The agent cannot alter audit history or approve decisions."""
        return await gateway.request("GET", "/tools/get_audit_log", params={"run_id": run_id})

    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock", action="store_true", help="Use an isolated deterministic mock, not live orders")
    args = parser.parse_args()
    transport = None
    if args.mock:
        from gateway.mock_gateway import MockGateway
        transport = httpx.MockTransport(MockGateway())
    gateway = GatewayClient(transport=transport)
    build_server(gateway).run(transport="stdio")


if __name__ == "__main__":
    main()
