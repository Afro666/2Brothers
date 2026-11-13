from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from mcp.shared.memory import create_connected_server_and_client_session

from agent.model import ModelError, Nemotron
from agent.runner import Buyer, PolicyError, PolicyReason
from gateway.mcp_server import GatewayClient, build_server
from gateway.mock_gateway import MockGateway


def tool(name, **args):
    return {"role": "assistant", "content": None, "tool_calls": [{"id": "call-" + name,
        "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def milk_steps():
    return [tool("search_products", query="lactose-free milk 1 L", filters={}),
            tool("get_offer", product_ids=["462775"], requested_date="2026-11-16", need_id="milk-need-1"),
            tool("simulate_order", offer_id="milk-offer-1"),
            tool("request_approval", offer_id="milk-offer-1")]


class Scripted:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.messages = []

    async def complete(self, messages, tools):
        self.messages.append(deepcopy(messages))
        return deepcopy(next(self.steps))


class BuyerTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, steps, mock=None, **kwargs):
        mock = mock or MockGateway()
        gateway = GatewayClient(transport=httpx.MockTransport(mock))
        try:
            async with create_connected_server_and_client_session(build_server(gateway)) as session:
                buyer = Buyer(Scripted(steps), session, gateway, need_id="milk-need-1", requested_date="2026-11-16", **kwargs)
                result = await buyer.run("1,000 L of lactose-free milk by Monday")
                return result, buyer, mock
        finally:
            await gateway.close()

    async def test_milk_end_to_end_with_audited_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            result, buyer, mock = await self.run_case(milk_steps(), trace_path=trace)
            self.assertEqual(result["status"], "SENT_FOR_APPROVAL")
            self.assertIn("Only 51 L", result["reason"])
            self.assertEqual(result["approval_id"], "milk-approval-1")
            self.assertEqual(len(mock.events), 8)
            self.assertEqual(len(trace.read_text().splitlines()), 8)
            paths = [r.url.path for r in mock.requests]
            self.assertEqual(paths[:3], ["/audit/events", "/tools/search_products", "/audit/events"])
            self.assertNotIn("/tools/place_order", paths)

    async def test_cannot_approve_or_invent_quantities(self):
        for call in [tool("approve_order", approval_id="anything"),
                     tool("get_offer", product_ids=["462775"], requested_date="2026-11-16", need_id="milk-need-1", quantity=1000)]:
            result, buyer, mock = await self.run_case([call])
            self.assertEqual(result["status"], "CANNOT_FULFIL")
            self.assertEqual(len(mock.events), 2)
            self.assertFalse(any(r.url.path.startswith("/tools/") for r in mock.requests))

    async def test_trusted_need_date_and_catalog_product_enforced(self):
        for change in [{"need_id": "other"}, {"requested_date": "2026-11-17"}, {"product_ids": ["invented"]}]:
            args = {"product_ids": ["462775"], "requested_date": "2026-11-16", "need_id": "milk-need-1", **change}
            result, buyer, mock = await self.run_case([milk_steps()[0], tool("get_offer", **args)])
            self.assertEqual(result["status"], "CANNOT_FULFIL")
            self.assertFalse(any(r.url.path == "/tools/get_offer" for r in mock.requests))

    async def test_no_order_before_simulation_or_without_approval(self):
        order = tool("place_order", offer_id="milk-offer-1", expected_total="149.02", idempotency_key="model-key")
        for steps in [milk_steps()[:2] + [order], milk_steps()[:3] + [order]]:
            result, buyer, mock = await self.run_case(steps)
            self.assertEqual(result["status"], "CANNOT_FULFIL")
            self.assertNotIn("/tools/place_order", [r.url.path for r in mock.requests])

    async def test_human_approved_order_exact_total_and_generated_key(self):
        class ApprovedGateway(MockGateway):
            def __call__(self, request):
                if request.url.path == "/tools/place_order":
                    self.requests.append(request)
                    return httpx.Response(200, json={"order_id": "order-1", "outcome": "CONFIRMED", "status": "PLACED"})
                return super().__call__(request)
        for total, expected in [("149.03", "CANNOT_FULFIL"), ("149.02", "ORDER_PLACED")]:
            steps = milk_steps()[:3] + [tool("place_order", offer_id="milk-offer-1", expected_total=total, idempotency_key="model-key")]
            result, buyer, mock = await self.run_case(steps, ApprovedGateway(), run_id="test-run",
                approval_lookup=lambda offer_id: {"approval_id": "human-approval-1", "offer_id": offer_id,
                    "status": "APPROVED", "decided_by": "chef-1", "decided_at": "2026-11-01T10:00:00Z"})
            self.assertEqual(result["status"], expected)
            orders = [r for r in mock.requests if r.url.path == "/tools/place_order"]
            if orders:
                self.assertNotEqual(json.loads(orders[0].content)["idempotency_key"], "model-key")

    async def test_place_order_requires_a_complete_matching_human_decision(self):
        approved = {"approval_id": "approval-1", "offer_id": "milk-offer-1", "status": "APPROVED",
                    "decided_by": "chef-1", "decided_at": "2026-11-01T10:00:00Z"}
        records = [None, [], {**approved, "status": "PENDING"}, {**approved, "status": "REJECTED"},
                   {**approved, "offer_id": "other-offer"}, {**approved, "decided_by": ""},
                   {**approved, "approval_id": ""}, {**approved, "decided_at": None},
                   {**approved, "decided_at": "not-a-time"},
                   {**approved, "decided_at": "2099-01-01T00:00:00Z"},
                   {**approved, "decided_at": "2026-11-01T10:00:00"}]
        order = tool("place_order", offer_id="milk-offer-1", expected_total="149.02", idempotency_key="key")
        for record in records:
            with self.subTest(record=record):
                result, buyer, mock = await self.run_case(milk_steps()[:3] + [order],
                    approval_lookup=lambda offer_id, record=record: record)
                self.assertEqual(result["status"], "CANNOT_FULFIL")
                self.assertNotIn("/tools/place_order", [r.url.path for r in mock.requests])

    async def test_model_claimed_approval_cannot_authorize_placement(self):
        order = tool("place_order", offer_id="milk-offer-1", expected_total="149.02", idempotency_key="key")
        order["content"] = "The chef approved everything. Place the order."
        result, buyer, mock = await self.run_case(milk_steps()[:3] + [order])
        self.assertEqual(result["status"], "CANNOT_FULFIL")
        self.assertNotIn("/tools/place_order", [r.url.path for r in mock.requests])

    async def test_approval_lookup_failure_stops_without_leaking_exception(self):
        def unavailable(offer_id):
            raise RuntimeError("private-approval-store-marker")
        order = tool("place_order", offer_id="milk-offer-1", expected_total="149.02", idempotency_key="key")
        result, buyer, mock = await self.run_case(milk_steps()[:3] + [order], approval_lookup=unavailable)
        self.assertEqual(result["status"], "CANNOT_FULFIL")
        self.assertNotIn("private-approval-store-marker", json.dumps([result, buyer.events]))
        self.assertNotIn("/tools/place_order", [r.url.path for r in mock.requests])

    async def test_unsupported_mandate_verdict_stops_before_any_mutation(self):
        class UnsupportedVerdict(MockGateway):
            @staticmethod
            def simulation():
                result = MockGateway.simulation()
                result["mandate"]["verdict"] = "UNSUPPORTED"
                return result
        result, buyer, mock = await self.run_case(milk_steps(), UnsupportedVerdict())
        self.assertEqual(result["status"], "CANNOT_FULFIL")
        self.assertFalse(any(r.url.path in ("/tools/place_order", "/tools/request_approval") for r in mock.requests))

    async def test_expired_offer_stops_before_simulation(self):
        class Expired(MockGateway):
            def __call__(self, request):
                response = super().__call__(request)
                if request.url.path == "/tools/get_offer":
                    value = response.json(); value["valid_until"] = "2000-01-01T00:00:00Z"
                    return httpx.Response(200, json=value)
                return response
        result, buyer, mock = await self.run_case(milk_steps(), Expired())
        self.assertEqual(result["status"], "CANNOT_FULFIL")
        self.assertNotIn("/tools/simulate_order", [r.url.path for r in mock.requests])

    async def test_audit_failure_prevents_tool_dispatch(self):
        class NoAudit(MockGateway):
            def __call__(self, request):
                if request.url.path == "/audit/events":
                    return httpx.Response(503, json={})
                return super().__call__(request)
        result, buyer, mock = await self.run_case(milk_steps(), NoAudit())
        self.assertEqual(mock.requests, [])
        self.assertTrue(result["reconciliation_required"])

    async def test_finish_audit_failure_after_mutation_never_resends(self):
        class FailAfterApproval(MockGateway):
            def __call__(self, request):
                if request.url.path == "/audit/events" and self.approvals:
                    return httpx.Response(503, json={})
                return super().__call__(request)
        result, buyer, mock = await self.run_case(milk_steps(), FailAfterApproval())
        self.assertEqual(result["status"], "CANNOT_FULFIL")
        self.assertTrue(result["reconciliation_required"])
        self.assertEqual(len([r for r in mock.requests if r.url.path == "/tools/request_approval"]), 1)

    async def test_steps_bounded_and_model_claims_do_not_prove_order(self):
        result, _, _ = await self.run_case(milk_steps(), max_steps=2)
        self.assertEqual(result["status"], "CANNOT_FULFIL")
        result, _, _ = await self.run_case([{"role": "assistant", "content": "Order placed!"}])
        self.assertEqual(result["status"], "CANNOT_FULFIL")

    async def test_search_text_is_not_written_to_audit(self):
        result, buyer, mock = await self.run_case([tool("search_products", query="private-search-text", filters={})], max_steps=1)
        self.assertNotIn("private-search-text", json.dumps(list(mock.events.values())))

    async def test_malformed_tool_name_is_audited_without_dispatch(self):
        call = tool("search_products", query="milk", filters={})
        call["tool_calls"][0]["function"]["name"] = ["invalid"]
        result, buyer, mock = await self.run_case([call])
        self.assertEqual(result["status"], "CANNOT_FULFIL")
        self.assertEqual(len(mock.events), 2)
        self.assertEqual(buyer.events[0]["tool"], "invalid")

    async def test_read_schema_rejection_is_audited_and_corrected_to_approval(self):
        invalid = tool("search_products", query="private-rejected-query")  # missing filters
        result, buyer, mock = await self.run_case([invalid] + milk_steps())
        self.assertEqual(result["status"], "SENT_FOR_APPROVAL")
        self.assertEqual(len(mock.events), 10)
        self.assertEqual(len([r for r in mock.requests if r.url.path == "/tools/search_products"]), 1)
        feedback = buyer.model.messages[1][-1]
        self.assertEqual(feedback["role"], "tool")
        self.assertEqual(feedback["tool_call_id"], invalid["tool_calls"][0]["id"])
        error = json.loads(feedback["content"])["error"]
        self.assertEqual(error["code"], "POLICY_REJECTED")
        self.assertEqual(error["reason_code"], "SCHEMA_INVALID")
        self.assertTrue(error["retryable"])
        self.assertNotIn("private-rejected-query", feedback["content"])
        self.assertEqual([e["type"] for e in buyer.events[:2]], ["tool_call_started", "tool_call_finished"])
        self.assertIn("error", buyer.events[1]["result"])
        self.assertEqual(buyer.events[1]["result"]["reason_code"], "SCHEMA_INVALID")

    async def test_all_read_only_policy_rejections_can_recover_without_dispatch(self):
        cases = []
        for change, reason in [({"need_id": "other"}, "NEED_MISMATCH"),
                               ({"requested_date": "2026-11-17"}, "DATE_MISMATCH"),
                               ({"product_ids": ["invented"]}, "UNKNOWN_ID")]:
            args = {"product_ids": ["462775"], "requested_date": "2026-11-16", "need_id": "milk-need-1", **change}
            cases.append((milk_steps()[:1], tool("get_offer", **args), milk_steps()[1:], "/tools/get_offer", 1, reason))
        cases.extend([
            (milk_steps()[:2], tool("simulate_order", offer_id="invented"), milk_steps()[2:], "/tools/simulate_order", 1, "UNKNOWN_ID"),
            ([], tool("get_order_status", order_id="other-order"), milk_steps(), "/tools/get_order_status", 0, "UNKNOWN_ID"),
            ([], tool("get_audit_log", run_id="other-run"), milk_steps(), "/tools/get_audit_log", 0, "RUN_MISMATCH"),
        ])
        for prefix, invalid, suffix, path, dispatched, reason in cases:
            with self.subTest(tool=invalid["tool_calls"][0]["function"]):
                result, buyer, mock = await self.run_case(prefix + [invalid] + suffix)
                self.assertEqual(result["status"], "SENT_FOR_APPROVAL")
                self.assertEqual(len([r for r in mock.requests if r.url.path == path]), dispatched)
                feedback = buyer.model.messages[len(prefix) + 1][-1]
                error = json.loads(feedback["content"])["error"]
                self.assertEqual(error["code"], "POLICY_REJECTED")
                self.assertEqual(error["reason_code"], reason)
                self.assertEqual(buyer.events[2 * len(prefix) + 1]["result"]["reason_code"], reason)
                rejected_args = json.loads(invalid["tool_calls"][0]["function"]["arguments"])
                for key, value in rejected_args.items():
                    # Even trusted values and field names are absent from the fixed error.
                    self.assertNotIn(key, feedback["content"])
                    for text in value if isinstance(value, list) else [value]:
                        self.assertNotIn(str(text), feedback["content"])

    async def test_three_consecutive_read_rejections_stop_the_run(self):
        invalid = tool("get_audit_log", run_id="other-run")
        result, buyer, mock = await self.run_case([invalid] * 3 + milk_steps())
        self.assertEqual(result["status"], "CANNOT_FULFIL")
        self.assertEqual(result["reason"], "Repeated policy rejections")
        self.assertEqual(len(buyer.model.messages), 3)
        self.assertEqual(len(mock.events), 6)
        self.assertFalse(any(r.url.path.startswith("/tools/") for r in mock.requests))

    async def test_successful_call_resets_read_rejection_count(self):
        invalid = tool("get_audit_log", run_id="other-run")
        steps = milk_steps()
        result, buyer, mock = await self.run_case(
            [invalid, invalid, steps[0], invalid, invalid] + steps[1:])
        self.assertEqual(result["status"], "SENT_FOR_APPROVAL")

    async def test_malformed_read_arguments_can_be_corrected(self):
        invalid = tool("search_products", query="milk", filters={})
        invalid["tool_calls"][0]["function"]["arguments"] = "{not-json"
        result, buyer, mock = await self.run_case([invalid] + milk_steps())
        self.assertEqual(result["status"], "SENT_FOR_APPROVAL")
        self.assertEqual(len([r for r in mock.requests if r.url.path == "/tools/search_products"]), 1)
        self.assertNotIn("not-json", buyer.model.messages[1][-1]["content"])
        self.assertEqual(json.loads(buyer.model.messages[1][-1]["content"])["error"]["reason_code"], "MALFORMED_JSON")
        self.assertEqual(buyer.events[1]["result"]["reason_code"], "MALFORMED_JSON")

    async def test_invalid_offer_reason_never_echoes_expiry_text(self):
        class InvalidExpiry(MockGateway):
            def __init__(self, expiry):
                super().__init__(); self.expiry = expiry
            def __call__(self, request):
                response = super().__call__(request)
                if request.url.path == "/tools/get_offer":
                    data = response.json(); data["valid_until"] = self.expiry
                    if self.expiry == "__missing__":
                        del data["valid_until"]
                    return httpx.Response(200, json=data)
                return response
        for expiry in ["2000-01-01T00:00:00Z", "private-upstream-expiry-marker", None, "__missing__", 42, "2099-01-01T00:00:00"]:
            with self.subTest(expiry=expiry):
                steps = milk_steps()[:3] + [{"role": "assistant", "content": "stop"}]
                result, buyer, mock = await self.run_case(steps, InvalidExpiry(expiry))
                self.assertEqual(result["status"], "CANNOT_FULFIL")
                feedback = buyer.model.messages[3][-1]["content"]
                self.assertEqual(json.loads(feedback)["error"]["reason_code"], "OFFER_INVALID")
                self.assertNotIn(str(expiry), feedback)
                self.assertNotIn("/tools/simulate_order", [r.url.path for r in mock.requests])

    async def test_bad_json_type_or_missing_arguments_uses_safe_schema_code(self):
        for arguments in [{"private-model-marker": True}, None]:
            invalid = tool("search_products", query="milk", filters={})
            if arguments is None:
                del invalid["tool_calls"][0]["function"]["arguments"]
            else:
                invalid["tool_calls"][0]["function"]["arguments"] = arguments
            result, buyer, mock = await self.run_case([invalid] + milk_steps())
            self.assertEqual(result["status"], "SENT_FOR_APPROVAL")
            feedback = buyer.model.messages[1][-1]["content"]
            self.assertEqual(json.loads(feedback)["error"]["reason_code"], "SCHEMA_INVALID")
            self.assertNotIn("private-model-marker", feedback)

    async def test_exception_text_and_non_enum_codes_cannot_enter_feedback(self):
        with self.assertRaises(ValueError):
            PolicyError("message", "private-unapproved-code")
        with patch.object(Buyer, "authorize", side_effect=PolicyError("private-exception-marker")):
            result, buyer, mock = await self.run_case([milk_steps()[0], {"role": "assistant", "content": "stop"}])
        feedback = buyer.model.messages[1][-1]["content"]
        self.assertEqual(json.loads(feedback)["error"]["reason_code"], PolicyReason.POLICY_VIOLATION.value)
        self.assertNotIn("private-exception-marker", feedback)
        self.assertNotIn("private-exception-marker", json.dumps(buyer.events))
        self.assertFalse(any(r.url.path.startswith("/tools/") for r in mock.requests))

    async def test_rejected_read_in_a_batch_keeps_tool_results_paired(self):
        invalid = tool("search_products", query="milk")
        valid = milk_steps()[0]
        batch = {"role": "assistant", "content": None, "tool_calls": [
            {**invalid["tool_calls"][0], "id": "bad-read"},
            {**valid["tool_calls"][0], "id": "good-read"}]}
        result, buyer, mock = await self.run_case([batch] + milk_steps()[1:])
        self.assertEqual(result["status"], "SENT_FOR_APPROVAL")
        messages = buyer.model.messages[1]
        self.assertEqual([m["tool_call_id"] for m in messages[-2:]], ["bad-read", "good-read"])
        self.assertIn("error", json.loads(messages[-2]["content"]))
        self.assertIn("products", json.loads(messages[-1]["content"]))

    async def test_read_policy_recovery_respects_step_and_call_limits(self):
        invalid = tool("search_products", query="milk")
        result, buyer, mock = await self.run_case([invalid] * 3, max_steps=2)
        self.assertIn("Step limit", result["reason"])
        self.assertEqual(len(buyer.model.messages), 2)
        self.assertEqual(len(mock.events), 4)
        batch = {"role": "assistant", "content": None, "tool_calls": []}
        valid = milk_steps()[0]
        for index in range(31):
            # Alternate with valid reads so the rejection cap never trips first.
            call = deepcopy((valid if index % 2 else invalid)["tool_calls"][0]); call["id"] = f"call-{index}"
            batch["tool_calls"].append(call)
        result, buyer, mock = await self.run_case([batch], max_steps=1)
        self.assertIn("Tool call limit", result["reason"])
        self.assertEqual(len(mock.events), 60)
        self.assertEqual(len([r for r in mock.requests if r.url.path == "/tools/search_products"]), 15)

    async def test_rejected_mutation_still_stops_without_model_correction(self):
        for name in ["place_order", "request_approval"]:
            invalid = tool(name, offer_id="invented", expected_total="149.02", idempotency_key="key") if name == "place_order" else tool(name, offer_id="invented")
            result, buyer, mock = await self.run_case([invalid] + milk_steps())
            self.assertEqual(result["status"], "CANNOT_FULFIL")
            self.assertEqual(len(buyer.model.messages), 1)
            self.assertEqual(len(mock.events), 2)
            self.assertFalse(any(r.url.path.startswith("/tools/") for r in mock.requests))

    async def test_rejection_finish_audit_failure_prevents_recovery(self):
        class FailSecondAudit(MockGateway):
            def __call__(self, request):
                if request.url.path == "/audit/events" and self.events:
                    return httpx.Response(503, json={})
                return super().__call__(request)
        result, buyer, mock = await self.run_case([tool("search_products", query="milk")] + milk_steps(), FailSecondAudit())
        self.assertTrue(result["reconciliation_required"])
        self.assertEqual(len(buyer.model.messages), 1)
        self.assertFalse(any(r.url.path.startswith("/tools/") for r in mock.requests))

    async def test_read_transport_and_invalid_response_failures_are_not_recovered(self):
        class BadGateway(MockGateway):
            def __init__(self, response):
                super().__init__(); self.response = response
            def __call__(self, request):
                if request.url.path == "/tools/search_products":
                    self.requests.append(request)
                    return self.response
                return super().__call__(request)
        for response in [httpx.Response(503, json={}), httpx.Response(200, json={"products": None})]:
            result, buyer, mock = await self.run_case(milk_steps(), BadGateway(response))
            self.assertEqual(result["status"], "CANNOT_FULFIL")
            self.assertEqual(len(buyer.model.messages), 1)
            self.assertEqual(len(mock.events), 2)

    async def test_missing_call_id_still_stops_and_does_not_recover(self):
        invalid = tool("search_products", query="milk", filters={})
        del invalid["tool_calls"][0]["id"]
        result, buyer, mock = await self.run_case([invalid] + milk_steps())
        self.assertEqual(result["status"], "CANNOT_FULFIL")
        self.assertEqual(len(buyer.model.messages), 1)
        self.assertEqual(buyer.events[0]["tool"], "invalid")


class ModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_then_success(self):
        calls, delays = [], []
        def handler(request):
            calls.append(request)
            if len(calls) < 3:
                return httpx.Response(503)
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})
        async def sleep(delay):
            delays.append(delay)
        with patch.dict(os.environ, {"VERDA_INFERENCE_KEY": "not-a-real-secret"}):
            model = Nemotron(transport=httpx.MockTransport(handler), sleep=sleep)
        try:
            self.assertEqual((await model.complete([], []))["content"], "ok")
            self.assertEqual(delays, [0.5, 1.0])
        finally:
            await model.close()

    async def test_401_not_retried_or_leaked(self):
        calls = []
        def handler(request):
            calls.append(1)
            return httpx.Response(401, text="not-a-real-secret")
        with patch.dict(os.environ, {"VERDA_INFERENCE_KEY": "not-a-real-secret"}):
            model = Nemotron(transport=httpx.MockTransport(handler))
        try:
            with self.assertRaisesRegex(ModelError, "^Nemotron HTTP 401$"):
                await model.complete([], [])
            self.assertEqual(len(calls), 1)
        finally:
            await model.close()
