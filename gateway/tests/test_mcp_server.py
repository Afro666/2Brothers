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
                self.assertIn("NEEDS_APPROVAL", refused.content[0].text)
        finally:
            await gateway.close()

    async def test_request_approval_key_reuse(self):
        mock = MockGateway()
        async with httpx.AsyncClient(transport=httpx.MockTransport(mock), base_url="http://mock") as client:
            body = {"offer_id": "milk-offer-1", "idempotency_key": "approval-key-1"}
            first = await client.post("/tools/request_approval", json=body)
            replay = await client.post("/tools/request_approval", json=body)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(replay.json(), first.json())
            conflict = await client.post("/tools/request_approval",
                                         json={**body, "note": "different"})
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

    async def test_mutations_use_json_keys_without_changing_mcp_signatures(self):
        mock = MockGateway()
        gateway = GatewayClient(transport=httpx.MockTransport(mock))
        try:
            async with create_connected_server_and_client_session(build_server(gateway)) as session:
                tools = {t.name: t for t in (await session.list_tools()).tools}
                self.assertNotIn("idempotency_key", tools["request_approval"].inputSchema["properties"])
                for _ in range(2):
                    result = await session.call_tool("request_approval", {"offer_id": "milk-offer-1"})
                    self.assertFalse(result.isError)
                await session.call_tool("place_order", {
                    "offer_id": "milk-offer-1", "expected_total": "149.02", "idempotency_key": "order-key"})
                approvals = [r for r in mock.requests if r.url.path == "/tools/request_approval"]
                self.assertEqual(json.loads(approvals[0].content), json.loads(approvals[1].content))
                self.assertEqual(len(mock.approvals), 1)
                for request in mock.requests:
                    payload = json.loads(request.content)
                    self.assertIsInstance(payload["idempotency_key"], str)
                    self.assertTrue(payload["idempotency_key"])
                    self.assertNotIn("Idempotency-Key", request.headers)
                self.assertEqual(json.loads(mock.requests[-1].content)["idempotency_key"], "order-key")
        finally:
            await gateway.close()

    async def test_mock_rejects_missing_or_header_only_keys_for_both_mutations(self):
        mock = MockGateway()
        for path in ["/tools/request_approval", "/tools/place_order"]:
            for value in [None, "", "  ", 123]:
                with self.subTest(path=path, value=value):
                    body = {"offer_id": "milk-offer-1", "expected_total": "149.02"}
                    if value is not None:
                        body["idempotency_key"] = value
                    response = mock(httpx.Request("POST", "http://mock" + path,
                        json=body, headers={"Idempotency-Key": "legacy-header"}))
                    self.assertEqual(response.status_code, 422)
        self.assertEqual(mock.approvals, {})

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

    async def test_unknown_or_non_json_error_bodies_give_generic_message(self):
        bodies = [
            httpx.Response(500, text="secret <html>"),
            httpx.Response(500, json={"error": {"code": "lower-case secret"}}),
            httpx.Response(500, json={"error": "NEEDS_APPROVAL"}),
            httpx.Response(500, json=["NEEDS_APPROVAL"]),
        ]
        for response in bodies:
            gateway = GatewayClient(transport=httpx.MockTransport(lambda request, r=response: r))
            try:
                with self.assertRaises(GatewayError) as caught:
                    await gateway.request("POST", "/tools/place_order", payload={})
                self.assertEqual(str(caught.exception),
                                 "Gateway HTTP 500; check status before retrying mutations")
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
