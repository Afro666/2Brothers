import json
import sys
import unittest

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from gateway.mcp_server import GatewayClient, GatewayError, build_server
from gateway.mock_gateway import MockGateway


def unpack(result):
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_lists_exact_tools_and_runs_milk_case_over_http(self):
        mock = MockGateway()
        gateway = GatewayClient(transport=httpx.MockTransport(mock))
        try:
            async with create_connected_server_and_client_session(build_server(gateway)) as session:
                tools = (await session.list_tools()).tools
                self.assertEqual({t.name for t in tools}, {
                    "search_products", "get_offer", "simulate_order", "place_order",
                    "request_approval", "get_order_status", "get_audit_log"})
                products = unpack(await session.call_tool("search_products", {"query": "lactose free milk 1 l", "filters": {}}))
                self.assertEqual(products["products"][0]["product_id"], "462775")
                offer = unpack(await session.call_tool("get_offer", {
                    "product_ids": ["462775"], "requested_date": "2026-11-16", "need_id": "milk-need-1"}))
                simulation = unpack(await session.call_tool("simulate_order", {"offer_id": offer["offer_id"]}))
                self.assertEqual(simulation["mandate"]["verdict"], "NEEDS_APPROVAL")
                approval = unpack(await session.call_tool("request_approval", {"offer_id": offer["offer_id"]}))
                self.assertEqual(approval["status"], "PENDING")
                await session.call_tool("request_approval", {"offer_id": offer["offer_id"]})
                self.assertEqual(len(mock.approvals), 1)
                refused = await session.call_tool("place_order", {
                    "offer_id": offer["offer_id"], "expected_total": "149.02", "idempotency_key": "test-order"})
                self.assertTrue(refused.isError)
        finally:
            await gateway.close()

    async def test_request_approval_key_reuse(self):
        mock = MockGateway()
        async with httpx.AsyncClient(transport=httpx.MockTransport(mock), base_url="http://mock") as client:
            headers = {"Idempotency-Key": "approval-key-1"}
            first = await client.post("/tools/request_approval", json={"offer_id": "milk-offer-1"}, headers=headers)
            replay = await client.post("/tools/request_approval", json={"offer_id": "milk-offer-1"}, headers=headers)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(replay.json(), first.json())
            conflict = await client.post("/tools/request_approval",
                                         json={"offer_id": "milk-offer-1", "note": "different"}, headers=headers)
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.json()["error"]["code"], "IDEMPOTENCY_CONFLICT")
            self.assertEqual(len(mock.approvals), 1)

    async def test_invalid_date_rejected_before_http(self):
        mock = MockGateway()
        gateway = GatewayClient(transport=httpx.MockTransport(mock))
        try:
            async with create_connected_server_and_client_session(build_server(gateway)) as session:
                result = await session.call_tool("get_offer", {
                    "product_ids": ["462775"], "requested_date": "bad", "need_id": "milk-need-1"})
                self.assertTrue(result.isError)
                self.assertEqual(mock.requests, [])
        finally:
            await gateway.close()

    async def test_mutation_transport_failure_is_not_retried_or_leaked(self):
        calls = []
        def fail(request):
            calls.append(request)
            raise httpx.ReadTimeout("secret-from-upstream", request=request)
        gateway = GatewayClient(transport=httpx.MockTransport(fail))
        try:
            with self.assertRaises(GatewayError) as caught:
                await gateway.request("POST", "/tools/place_order", payload={})
            self.assertNotIn("secret-from-upstream", str(caught.exception))
            self.assertEqual(len(calls), 1)
        finally:
            await gateway.close()

    async def test_stdio_entrypoint(self):
        params = StdioServerParameters(command=sys.executable, args=["-m", "gateway.mcp_server", "--mock"])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self.assertEqual(len((await session.list_tools()).tools), 7)
                result = unpack(await session.call_tool("simulate_order", {"offer_id": "milk-offer-1"}))
                self.assertEqual(result["expected_total"], "149.02")
