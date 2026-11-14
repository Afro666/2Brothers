"""The live conformance kit (#286), run against the in-process gateway."""

from gateway.conformance import Kit, table
from gateway.tests.test_gateway_app import HUMAN, K, env  # noqa: F401 (fixture)


def test_kit_passes_against_our_own_gateway_with_the_agent_token(env):
    client, _, db = env
    with client:
        results = Kit("http://testserver", "agent-test-token", "demo-kitchen", client=client).run()
    by_id = {r.id: r for r in results}
    assert [r.id for r in results if r.status == "FAIL"] == [], table(results)
    assert by_id["C06"].status == "PASS" and by_id["C07"].status == "PASS"
    assert by_id["C10"].status == "SKIP"            # a server agent token is not kitchen-bound
    assert db.orders.count_documents({}) == 0 and db.proposals.count_documents({}) == 0


def test_kitchen_token_proves_the_kitchen_boundary(env):
    client, _, _ = env
    token = client.post(K + "/tokens", headers=HUMAN, json={"name": "kit", "scopes": ["kitchen:read", "kitchen:propose"]}).json()["token"]
    with client:
        results = Kit("http://testserver", token, "demo-kitchen", client=client).run()
    assert [r.id for r in results if r.status == "FAIL"] == [], table(results)
    assert {r.id: r.status for r in results}["C10"] == "PASS"


def test_a_gateway_that_lets_the_agent_approve_fails_the_kit(env, monkeypatch):
    client, _, _ = env
    from gateway.service import Gateway
    monkeypatch.setattr(Gateway, "approve", lambda self, *a, **k: {"order_id": "x"})
    with client:
        results = Kit("http://testserver", "agent-test-token", "demo-kitchen", client=client).run()
    assert {r.id: r.status for r in results}["C07"] == "FAIL"
