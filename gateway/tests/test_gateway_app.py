"""End-to-end milk flow through the HTTP gateway: test database, recorded Valio answers."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

mongomock = pytest.importorskip("mongomock")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from gateway.app import create_app  # noqa: E402
from gateway.service import Gateway, GatewayError  # noqa: E402
from gateway.valio_client import ValioClient  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 13, 20, 10, tzinfo=timezone.utc)   # 22:10 Helsinki
HUMAN = {"Authorization": "Bearer human-test-token", "X-User": "aron"}
AGENT = {"Authorization": "Bearer agent-test-token"}
K = "/v1/kitchens/demo-kitchen"

RAW = {
    "462775": {"id": "462775", "salesUnit": "ST", "baseUnit": "ST", "allowedLotSize": 0.01,
               "units": [{"unitId": "KI", "sizeInBaseUnits": 12.0}, {"unitId": "ST", "sizeInBaseUnits": 1.0}]},
    "462921": {"id": "462921", "salesUnit": "KI", "baseUnit": "ST", "allowedLotSize": 0.01,
               "units": [{"unitId": "KI", "sizeInBaseUnits": 5.0}, {"unitId": "ST", "sizeInBaseUnits": 1.0}]},
    "463335": {"id": "463335", "salesUnit": "ST", "baseUnit": "ST", "allowedLotSize": 0.01,
               "units": [{"unitId": "KI", "sizeInBaseUnits": 5.0}, {"unitId": "ST", "sizeInBaseUnits": 1.0}]},
}


class FakeValio:
    """Serves the recorded fixtures; `bump` moves a price to test TOTAL_MISMATCH."""

    def __init__(self):
        self.price_data = json.loads((FIX / "price.json").read_text())
        self.avail_data = json.loads((FIX / "availability.json").read_text())
        self.hook = None   # called before each Valio answer (to test races)

    def transport(self, path, payload, headers):
        if self.hook:
            self.hook()
        data = self.price_data if path == "/api/price" else self.avail_data
        out = deepcopy(data)
        out["products"] = [p for p in out["products"] if p["productId"] in payload["products"]]
        return out

    def bump(self, pid, value):
        for p in self.price_data["products"]:
            if p["productId"] == pid:
                p["catalogPrice"]["value"] = value
                p["comparisonPrice"]["value"] = value


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("GATEWAY_HUMAN_TOKEN", "human-test-token")
    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    db = mongomock.MongoClient(tz_aware=True)["test"]
    for pid, raw in RAW.items():
        db.products.insert_one({"_id": pid, "names": {"en": f"milk {pid}"}, "raw": raw})
    fake = FakeValio()
    valio = ValioClient("test-not-a-real-key", transport=fake.transport, ttl=0, now=lambda: NOW)
    def search(db, query, filters, limit, kitchen_id=None):
        return [{"product_id": pid} for pid in ("462775", "462921", "463335")] if "milk" in query or "maito" in query else []

    gw = Gateway(db, valio, now=lambda: NOW, search=search)
    return TestClient(create_app(gw)), fake, db


def milk(client, key="p1", quantity="51"):
    r = client.post(K + "/proposals", headers=AGENT, json={
        "product_ids": ["462775", "462921", "463335"], "quantity": quantity, "unit": "L",
        "requested_date": "2026-11-16", "idempotency_key": key, "text": "1000 L lactose-free milk by Monday"})
    assert r.status_code == 200, r.text
    return r.json()


def test_milk_proposal_numbers_come_from_the_engine(env):
    client, _, _ = env
    p = milk(client, quantity="1000")
    assert p["status"] == "READY"
    assert [(ln["product_id"], ln["quantity"]) for ln in p["lines"]] == [("462775", "51"), ("463335", "949")]
    assert p["total_ex_vat"] == "1459.67"
    assert p["mandate"]["verdict"] == "NEEDS_APPROVAL"
    assert "CLOSING_PASSED" in p["mandate"]["reason_codes"]
    assert {e["product_id"] for e in p["excluded"]} == {"462921"}
    assert p["lines"][1]["unknown_stock"] is True
    assert p["delivery_fee"] is None and p["mov_gap"] is None   # terms not set: unknown, not zero
    assert p["alternative"]["total_ex_vat"] == "1400.00"


def test_replay_returns_same_proposal_and_reuse_is_refused(env):
    client, _, _ = env
    a, b = milk(client), milk(client)
    assert a["proposal_id"] == b["proposal_id"]
    r = client.post(K + "/proposals", headers=AGENT, json={
        "product_ids": ["462775"], "quantity": "10", "unit": "L", "requested_date": "2026-11-16",
        "idempotency_key": "p1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_agent_cannot_approve(env):
    client, _, _ = env
    p = milk(client)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=AGENT,
                    json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "HUMAN_SESSION_REQUIRED"
    r = client.post("/tools/place_order", headers=AGENT, json={
        "offer_id": p["offer_id"], "expected_total": p["expected_total"], "idempotency_key": "x"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "NEEDS_APPROVAL"


def test_non_numeric_quantity_and_total_are_422(env):
    client, _, _ = env
    r = client.post(K + "/proposals", headers=AGENT, json={
        "product_ids": ["462775"], "quantity": "abc", "unit": "L",
        "requested_date": "2026-11-16", "idempotency_key": "bad-q"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST", r.text
    p = milk(client)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": "abc", "idempotency_key": "bad-t"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST", r.text


def test_no_token_no_access(env):
    client, _, _ = env
    assert client.get(K + "/orders").status_code == 401
    assert client.get(K + "/orders", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_human_approves_order_is_placed_once(env):
    client, _, db = env
    p = milk(client, quantity="51")
    body = {"expected_total": p["expected_total"], "idempotency_key": "a1"}
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN, json=body)
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["outcome"] == "CONFIRMED" and order["status"] == "SENT"
    again = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN, json=body)
    assert again.json()["order_id"] == order["order_id"]
    assert db.orders.count_documents({}) == 1
    assert client.get(f"{K}/proposals/{p['proposal_id']}", headers=AGENT).json()["status"] == "APPROVED"
    tool = client.post("/tools/place_order", headers=AGENT, json={
        "offer_id": p["offer_id"], "expected_total": p["expected_total"], "idempotency_key": "x"})
    assert tool.status_code == 200 and tool.json()["order_id"] == order["order_id"]
    kinds = [e["kind"] for e in client.get(K + "/audit", headers=AGENT).json()["events"]]
    assert kinds == ["proposal_created", "decision_summary", "order_placed"]


def test_second_approve_with_other_key_during_first_places_one_order(env):
    client, fake, db = env
    p = milk(client)
    url = f"{K}/proposals/{p['proposal_id']}/approve"
    other_tab = Gateway(db, ValioClient("test-not-a-real-key", transport=fake.transport, ttl=0, now=lambda: NOW),
                        now=lambda: NOW)
    second = []

    def racing():
        # The first approve has claimed the proposal and is in its live re-check.
        if second:
            return
        second.append(None)
        try:
            other_tab.approve("demo-kitchen", p["proposal_id"],
                              {"expected_total": p["expected_total"], "idempotency_key": "a2"}, human="tymon")
        except GatewayError as exc:
            second[0] = exc

    fake.hook = racing
    first = client.post(url, headers=HUMAN, json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert first.status_code == 200, first.text
    assert isinstance(second[0], GatewayError), "the second approve must be refused"
    assert second[0].status == 409 and second[0].code == "NOT_PENDING"
    assert db.orders.count_documents({}) == 1
    assert db.proposals.find_one({"_id": p["proposal_id"]})["status"] == "APPROVED"


def test_price_moved_is_total_mismatch_and_nothing_is_placed(env):
    client, fake, db = env
    p = milk(client, quantity="51")
    fake.bump("462775", 3.57)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TOTAL_MISMATCH"
    assert r.json()["error"]["expected_total"] != p["expected_total"]
    assert db.orders.count_documents({}) == 0
    fresh = client.get(f"{K}/proposals/{p['proposal_id']}", headers=HUMAN).json()
    ok = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                     json={"expected_total": fresh["expected_total"], "idempotency_key": "a2"})
    assert ok.status_code == 200, ok.text


def test_expired_proposal_is_requoted_and_unchanged_basket_can_be_approved(env):
    client, _, db = env
    p = milk(client)
    db.offers.update_one({'_id': p['offer_id']}, {'$set': {'valid_until': '2000-01-01T00:00:00+00:00'}})
    result = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                        json={'expected_total': p['expected_total'], 'idempotency_key': 'expired'})
    assert result.status_code == 200, result.text
    assert result.json()['expected_total'] == p['expected_total']
    assert db.orders.count_documents({}) == 1


def test_wrong_total_from_the_client_is_refused(env):
    client, _, db = env
    p = milk(client)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": "1.00", "idempotency_key": "a1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TOTAL_MISMATCH"
    assert db.orders.count_documents({}) == 0


def test_human_approval_does_not_confirm_unknown_stock(env):
    client, _, db = env
    p = milk(client, quantity="1000")
    assert any(line['unknown_stock'] for line in p['lines'])
    response = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                           json={'expected_total': p['expected_total'], 'idempotency_key': 'a1'})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'STOCK_UNKNOWN'
    assert db.orders.count_documents({}) == 0
    assert db.approvals.find_one({})['status'] == 'PENDING'
    assert client.get(f"{K}/proposals/{p['proposal_id']}", headers=HUMAN).json()['status'] == 'READY'


def test_reject_records_reason(env):
    client, _, db = env
    p = milk(client)
    r = client.post(f"{K}/proposals/{p['proposal_id']}/reject", headers=HUMAN, json={"reason": "too much", "idempotency_key": "r1"})
    assert r.json()["status"] == "REJECTED"
    assert db.approvals.find_one({})["status"] == "REJECTED"
    r = client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN,
                    json={"expected_total": p["expected_total"], "idempotency_key": "a1"})
    assert r.status_code == 409


def test_agent_tool_flow_need_offer_simulate_request_approval(env):
    client, _, _ = env
    need = client.post(K + "/needs", headers=AGENT, json={"quantity": "60", "unit": "L", "requested_date": "2026-11-16"}).json()
    offer = client.post("/tools/get_offer", headers=AGENT, json={"need_id": need["need_id"], "product_ids": ["462775"]}).json()
    assert offer["lines"][0]["quantity"] == "51"   # the gateway sizes it from the need, not the model
    sim = client.post("/tools/simulate_order", headers=AGENT, json={"offer_id": offer["offer_id"]}).json()
    assert sim["expected_total"] == offer["expected_total"]
    req = client.post("/tools/request_approval", headers=AGENT, json={"offer_id": offer["offer_id"], "idempotency_key": "k1"})
    assert req.json()["status"] == "PENDING"
    again = client.post("/tools/request_approval", headers=AGENT, json={"offer_id": offer["offer_id"], "idempotency_key": "k1"})
    assert again.json()["approval_id"] == req.json()["approval_id"]
    bad = client.post("/tools/get_offer", headers=AGENT, json={"need_id": "nope", "product_ids": ["462775"]})
    assert bad.status_code == 422


def test_buyer_request_reaches_human_inbox_and_one_exact_order(env):
    client, _, db = env
    need = client.post(K + '/needs', headers=AGENT, json={
        'quantity': '51', 'unit': 'L', 'requested_date': '2026-11-16'}).json()
    offer = client.post('/tools/get_offer', headers=AGENT, json={
        'need_id': need['need_id'], 'product_ids': ['462775']}).json()
    simulation = client.post('/tools/simulate_order', headers=AGENT,
                             json={'offer_id': offer['offer_id']}).json()
    requested = client.post('/tools/request_approval', headers=AGENT, json={
        'offer_id': offer['offer_id'], 'idempotency_key': 'buyer-request'}).json()
    inbox = client.get(K + '/proposals', headers=HUMAN).json()['proposals']
    pending = next(p for p in inbox if p['approval_id'] == requested['approval_id'])
    assert pending['status'] == 'READY'
    assert db.orders.count_documents({}) == 0
    path = f"{K}/proposals/{pending['proposal_id']}/approve"
    decision = {'expected_total': simulation['expected_total'], 'idempotency_key': 'human-decision'}
    denied = client.post(path, headers=AGENT, json=decision)
    assert denied.status_code == 403
    placed = client.post(path, headers=HUMAN, json=decision)
    assert placed.status_code == 200, placed.text
    order = placed.json()
    assert order['expected_total'] == simulation['expected_total']
    assert order['outcome'] == 'CONFIRMED'
    replay = client.post(path, headers=HUMAN, json=decision)
    assert replay.json()['order_id'] == order['order_id']
    assert db.orders.count_documents({}) == 1
    approval = db.approvals.find_one({'_id': requested['approval_id']})
    assert approval['status'] == 'APPROVED' and approval['decided_by'] == 'aron'
    assert approval['decided_at'] is not None
    listed = client.get(K + '/orders', headers=HUMAN).json()['orders']
    assert [row['order_id'] for row in listed] == [order['order_id']]
    events = client.get(K + '/audit', headers=HUMAN).json()['events']
    assert any(e['kind'] == 'order_placed' and e['actor'] == 'aron'
               and e['order_id'] == order['order_id'] for e in events)


def test_free_text_uses_the_parser_and_the_engine(env):
    client, _, _ = env
    r = client.post(K + "/proposals", headers=AGENT, json={
        "text": "1000 l laktoositonta maitoa maanantaiksi", "idempotency_key": "t1"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["request"]["made_by"] == "parser" and p["request"]["requested_date"] == "2026-11-16"
    assert p["total_ex_vat"] == "1459.67"
    again = client.post(K + "/proposals", headers=AGENT, json={
        "text": "1000 l laktoositonta maitoa maanantaiksi", "idempotency_key": "t1"})
    assert again.json()["proposal_id"] == p["proposal_id"]


def test_unreadable_text_is_refused_with_a_reason(env):
    client, _, _ = env
    r = client.post(K + "/proposals", headers=AGENT, json={"text": "some milk please", "idempotency_key": "t2"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CANNOT_READ_REQUEST"
    r = client.post(K + "/proposals", headers=AGENT, json={"text": "10 kg unicorn by Monday", "idempotency_key": "t3"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NO_PRODUCTS_FOUND"


def test_parser_is_not_used_after_an_ambiguous_buyer_failure(monkeypatch):
    """The Buyer may already have made a proposal: no second one from the parser."""
    from gateway.service import GatewayError

    async def ambiguous(kitchen_id, body):
        raise GatewayError(503, "BUYER_RECONCILIATION_REQUIRED", "check first")

    async def safe(kitchen_id, body):
        raise GatewayError(504, "BUYER_TIMEOUT", "timed out before any write", fallback_safe=True)

    monkeypatch.setenv("GATEWAY_AGENT_TOKEN", "agent-test-token")
    db = mongomock.MongoClient(tz_aware=True)["test"]
    for pid, raw in RAW.items():
        db.products.insert_one({"_id": pid, "names": {"en": f"milk {pid}"}, "raw": raw})
    fake = FakeValio()
    gw = Gateway(db, ValioClient("k", transport=fake.transport, ttl=0, now=lambda: NOW), now=lambda: NOW,
                 search=lambda db, q, f, n, kitchen_id=None: [{"product_id": "462775"}])
    body = {"text": "60 l milk by Monday", "idempotency_key": "b1"}
    r = TestClient(create_app(gw, buyer_worker=ambiguous)).post(K + "/proposals", headers=AGENT, json=body)
    assert r.status_code == 503 and db.proposals.count_documents({}) == 0
    r = TestClient(create_app(gw, buyer_worker=safe)).post(K + "/proposals", headers=AGENT, json=body)
    assert r.status_code == 200 and r.json()["request"]["made_by"] == "parser"


def test_a_structured_body_cannot_claim_the_parser_made_it(env):
    """made_by and query are set by the gateway, never by the client."""
    client, _, _ = env
    r = client.post(K + "/proposals", headers=AGENT, json={
        "product_ids": ["462775"], "quantity": "51", "unit": "L", "requested_date": "2026-11-16",
        "idempotency_key": "spoof", "made_by": "parser", "query": "milk"})
    assert r.status_code == 200, r.text
    assert r.json()["request"]["made_by"] == "structured"
    assert "query" not in r.json()["request"]


def test_failed_attempt_without_a_write_releases_commit_claim(env, monkeypatch):
    from store import orders
    client, _, db = env
    p = milk(client)
    real = orders.record_attempt
    def fail(**kwargs):
        raise RuntimeError('write failed')
    monkeypatch.setattr(orders, 'record_attempt', lambda *a, **kw: fail(**kw))
    body = {'expected_total': p['expected_total'], 'idempotency_key': 'recovery'}
    with pytest.raises(RuntimeError):
        client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN, json=body)
    assert db.proposals.find_one({'_id': p['proposal_id']})['status'] == 'READY'
    monkeypatch.setattr(orders, 'record_attempt', real)
    assert client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN, json=body).status_code == 200
    assert db.orders.count_documents({}) == 1


def test_lost_attempt_response_retains_claim_for_reconciliation(env, monkeypatch):
    from store import orders
    client, _, db = env
    p = milk(client)
    real = orders.record_attempt
    def write_then_fail(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError('response lost')
    monkeypatch.setattr(orders, 'record_attempt', write_then_fail)
    body = {'expected_total': p['expected_total'], 'idempotency_key': 'ambiguous'}
    with pytest.raises(RuntimeError):
        client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN, json=body)
    assert db.proposals.find_one({'_id': p['proposal_id']})['status'] == 'COMMITTING'
    body['idempotency_key'] = 'different-key'
    assert client.post(f"{K}/proposals/{p['proposal_id']}/approve", headers=HUMAN, json=body).status_code == 409
    assert db.orders.count_documents({}) == 1
