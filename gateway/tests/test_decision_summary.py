"""Decision record on the milk proposal (#282): plain words, gateway numbers only."""

import json
import re

import pytest

pytest.importorskip("mongomock")
pytest.importorskip("fastapi")

from gateway.decision import decision_summary  # noqa: E402
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, env, milk  # noqa: E402,F401

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def gateway_strings(proposal: dict) -> str:
    """Everything the gateway itself returned, except the summary."""
    return json.dumps({k: v for k, v in proposal.items() if k != "decision_summary"}, ensure_ascii=False)


def test_milk_proposal_shows_the_summary(env):  # noqa: F811
    client, _, _ = env
    p = milk(client, quantity="1000")
    s = p["decision_summary"]
    text = s["text"]
    assert s["asked"].startswith('Asked: "1000 L lactose-free milk by Monday"')
    assert "462775, 462921, 463335" in s["searched"]
    assert [c.split(" of ")[0] for c in s["chosen"]] == ["51 ST", "949 ST"]
    assert any(line.startswith("462921") and "left out" in line for line in s["left_out"])
    assert f"EUR {p['expected_total']}" in s["totals"]
    assert "delivery fee unknown" in s["totals"]          # terms not set: unknown, not zero
    assert any("approves the total of EUR " + p["expected_total"] in d for d in s["decide"])
    assert any("not confirmed stock for 463335" in d for d in s["decide"])
    assert "cheaper option" in text
    # The same proposal read back carries the same summary.
    assert client.get(f"{K}/proposals/{p['proposal_id']}", headers=HUMAN).json()["decision_summary"] == s


def test_no_number_in_the_summary_differs_from_the_gateway(env):  # noqa: F811
    client, _, _ = env
    p = milk(client, quantity="1000")
    source = gateway_strings(p)
    numbers = NUMBER.findall(p["decision_summary"]["text"])
    assert numbers
    missing = [n for n in numbers if n not in source]
    assert missing == [], f"numbers not from the gateway: {missing}"


def test_summary_is_an_audit_event(env):  # noqa: F811
    client, _, _ = env
    p = milk(client, quantity="1000")
    events = client.get(f"{K}/audit", headers=HUMAN).json()["events"]
    summaries = [e for e in events if e.get("kind") == "decision_summary"
                 and e.get("proposal_id") == p["proposal_id"]]
    assert len(summaries) == 1
    assert summaries[0]["summary"] == p["decision_summary"]["text"]


def test_tool_path_records_a_summary_too(env):  # noqa: F811
    client, _, _ = env
    need = client.post(K + "/needs", headers=AGENT,
                       json={"quantity": "60", "unit": "L", "requested_date": "2026-11-16"}).json()
    offer = client.post("/tools/get_offer", headers=AGENT,
                        json={"need_id": need["need_id"], "product_ids": ["462775"]}).json()
    req = client.post("/tools/request_approval", headers=AGENT,
                      json={"offer_id": offer["offer_id"], "idempotency_key": "k1"}).json()
    events = client.get(f"{K}/audit", headers=HUMAN).json()["events"]
    assert any(e.get("kind") == "decision_summary" and e.get("proposal_id") == req["proposal_id"]
               for e in events)


def test_unknown_terms_and_refusal_wording():
    sim = {"lines": [], "excluded": [{"product_id": "1", "reason": "closing time passed"}],
           "shortfall": "10", "measure": "L", "expected_total": "0.00", "total_ex_vat": "0.00",
           "vat": "0.00", "delivery_fee": None, "mandate": {"verdict": "REFUSED"}, "alternative": None}
    s = decision_summary({"product_ids": ["1"], "quantity": "10", "unit": "L",
                          "requested_date": "2026-11-16"}, sim)
    assert s["chosen"] == [] and "Chosen: nothing." in s["text"]
    assert s["decide"] == ["Nothing can be ordered: no line passed the checks."]
    assert "10 L of the request cannot be covered" in s["text"]


def test_line_without_unknown_stock_key_is_unconfirmed():
    # Same rule as the approve guard: a missing unknown_stock means stock is not confirmed.
    line = {"product_id": "7", "quantity": "5", "unit": "ST", "total": "10.00", "why": "cheapest"}
    sim = {"lines": [line, dict(line, product_id="8", unknown_stock=False)], "excluded": [],
           "shortfall": None, "expected_total": "20.00", "total_ex_vat": "20.00", "vat": "0.00",
           "delivery_fee": None, "mandate": {"verdict": "NEEDS_APPROVAL"}, "alternative": None}
    s = decision_summary({"product_ids": ["7", "8"], "quantity": "10", "unit": "ST",
                          "requested_date": "2026-11-16"}, sim)
    stock = [d for d in s["decide"] if "not confirmed stock" in d]
    assert len(stock) == 1 and "7 (5 ST)" in stock[0] and "8 (" not in stock[0]
