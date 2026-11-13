"""Explicitly opt-in mock contract service; no live data, database or purchases."""
from copy import deepcopy
import json

import httpx


class MockGateway:
    def __init__(self):
        self.events = {}
        self.requests = []
        self.approvals = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content) if request.content else {}
        path = request.url.path
        if path == "/audit/events":
            key = body["event_id"]
            if key in self.events and self.events[key] != body:
                return httpx.Response(409, json={"error": {"code": "IDEMPOTENCY_CONFLICT"}})
            self.events[key] = deepcopy(body)
            return httpx.Response(200, json={"event_id": key, "stored": True})
        if path == "/tools/search_products":
            excluded = body.get("filters", {}).get("exclude_allergens", [])
            return httpx.Response(200, json={"products": [] if "milk" in excluded or "AM" in excluded else [
                {"product_id": "462775", "name": "Lactose-free milk 1 L", "allergens": ["milk"]}]})
        if path == "/tools/get_offer":
            if body.get("need_id") != "milk-need-1" or body.get("product_ids") != ["462775"]:
                return httpx.Response(422, json={"error": {"code": "INVALID_NEED"}})
            return httpx.Response(200, json={"offer_id": "milk-offer-1", "valid_until": "2099-01-01T00:00:00Z",
                                             "lines": self.simulation()["lines"]})
        if path in ("/tools/simulate_order", "/tools/request_approval", "/tools/place_order"):
            if body.get("offer_id") != "milk-offer-1":
                return httpx.Response(404, json={"error": {"code": "OFFER_NOT_FOUND"}})
        if path in ("/tools/request_approval", "/tools/place_order"):
            key = body.get("idempotency_key")
            if not isinstance(key, str) or not key.strip():
                return httpx.Response(422, json={"error": {"code": "MISSING_IDEMPOTENCY_KEY"}})
        if path == "/tools/simulate_order":
            return httpx.Response(200, json=self.simulation())
        if path == "/tools/request_approval":
            key = body["idempotency_key"]  # validated above
            if key in self.approvals:
                if self.approvals[key]["body"] != body:
                    return httpx.Response(409, json={"error": {"code": "IDEMPOTENCY_CONFLICT"}})
                return httpx.Response(200, json=self.approvals[key]["result"])
            self.approvals[key] = {"body": deepcopy(body),
                                   "result": {"approval_id": "milk-approval-1", "status": "PENDING"}}
            return httpx.Response(200, json=self.approvals[key]["result"])
        if path == "/tools/place_order":
            return httpx.Response(403, json={"error": {"code": "NEEDS_APPROVAL"}})
        if path == "/tools/get_order_status":
            return httpx.Response(404, json={"error": {"code": "ORDER_NOT_FOUND"}})
        if path == "/tools/get_audit_log":
            return httpx.Response(200, json={"events": [e for e in self.events.values()
                if e["run_id"] == request.url.params.get("run_id")]})
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})

    @staticmethod
    def simulation():
        return {"offer_id": "milk-offer-1", "expected_total": "149.02", "currency": "EUR",
                "mov_gap": "0.00", "delivery_fee": "0.00",
                "mandate": {"verdict": "NEEDS_APPROVAL", "reasons": [
                    "Only 51 L is confirmed for Monday; the remaining stock is unknown."]},
                "lines": [{"product_id": "462775", "quantity": "51", "unit": "ST",
                    "why": "51 one-litre units confirmed; the full 1,000 L request cannot be met.",
                    "available_date": "2026-11-16", "unknown_stock": False, "cutoff_passed": False}]}
