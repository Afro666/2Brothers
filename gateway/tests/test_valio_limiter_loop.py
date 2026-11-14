"""The Valio limiter's wait must not freeze the event loop (#1280).

`Gate.acquire` waits with a blocking sleep (up to MAX_WAIT). An async route that runs the
Valio-bound gateway work on the loop stops every other request for that time. Here one
request waits in a real `Gate` (fake transport, never the real Valio API) while an
unrelated GET /health must finish before that wait ends.
"""

import asyncio
import threading
import time

import pytest

mongomock = pytest.importorskip("mongomock")
pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from gateway.app import create_app  # noqa: E402
from gateway.service import Gateway  # noqa: E402
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW, RAW, FakeValio  # noqa: E402
from gateway.valio_client import Gate, ValioClient  # noqa: E402

WAIT = 0.5          # seconds the limiter makes the Valio-bound request wait


class World:
    def __init__(self, monkeypatch):
        monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
        monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
        self.db = mongomock.MongoClient(tz_aware=True)["test"]
        for pid, raw in RAW.items():
            self.db.products.insert_one({"_id": pid, "names": {"en": f"milk {pid}"}, "raw": raw})
        self.valio = ValioClient("test-not-a-real-key", transport=FakeValio().transport, ttl=0,
                                 now=lambda: NOW)

        def search(db, query, filters, limit, kitchen_id=None):
            return [{"product_id": pid} for pid in RAW] if "milk" in query else []

        self.app = create_app(Gateway(self.db, self.valio, now=lambda: NOW, search=search))
        self.client = TestClient(self.app)
        self.entered, self.waited_until = threading.Event(), None

    def slow_gate(self) -> None:
        """A real token bucket with no token left: the next Valio call waits WAIT s."""
        def sleep(seconds):
            self.entered.set()
            time.sleep(seconds)               # the blocking wait of Gate.acquire
            self.waited_until = time.monotonic()

        gate = Gate(rate=1 / WAIT, burst=1, max_wait=5, sleep=sleep)
        gate.acquire()                        # takes the only token
        self.valio._gate = gate

    def race(self, method: str, path: str, body: dict, headers: dict):
        """Send the slow request; while it waits in the limiter, GET /health."""
        async def main():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                slow = asyncio.create_task(client.request(method, path, json=body, headers=headers))
                for _ in range(300):          # until the slow request is in the wait
                    if self.entered.is_set() or slow.done():
                        break
                    await asyncio.sleep(0.01)
                health = await client.get("/health")
                health_at = time.monotonic()
                return await slow, health, health_at
        return asyncio.run(main())


def proposal_body(key: str) -> dict:
    return {"product_ids": ["462775"], "quantity": "51", "unit": "L",
            "requested_date": "2026-11-16", "idempotency_key": key}


def setup_case(w: World, case: str):
    if case == "get_offer":
        need = w.client.post(K + "/needs", headers=AGENT, json={
            "quantity": "60", "unit": "L", "requested_date": "2026-11-16"}).json()
        return "/tools/get_offer", {"need_id": need["need_id"], "product_ids": ["462775"]}, AGENT
    if case == "proposal":
        return K + "/proposals", proposal_body("loop-1"), AGENT
    made = w.client.post(K + "/proposals", headers=AGENT, json=proposal_body("loop-2"))
    assert made.status_code == 200, made.text
    p = made.json()
    return (f"{K}/proposals/{p['proposal_id']}/approve",
            {"expected_total": p["expected_total"], "idempotency_key": "loop-a"}, HUMAN)


@pytest.mark.parametrize("case", ["get_offer", "proposal", "approve"])
def test_a_request_waiting_in_the_limiter_does_not_delay_health(monkeypatch, case):
    w = World(monkeypatch)
    path, body, headers = setup_case(w, case)
    w.slow_gate()
    answer, health, health_at = w.race("POST", path, body, headers)
    assert w.entered.is_set(), "the request never reached the limiter's wait"
    assert answer.status_code == 200, answer.text
    assert health.status_code == 200, health.text
    assert health_at < w.waited_until, "GET /health waited for the limiter: the event loop was blocked"
