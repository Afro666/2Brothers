"""The recall demo's seed: an open coffee proposal the check can block, never an order."""

from datetime import date

import pytest

pytest.importorskip("mongomock")

from demo.recall_demo import COFFEE, next_monday, seed  # noqa: E402
from gateway import recalls_view  # noqa: E402
from monitor.tests.test_proposals import setup  # noqa: E402

TODAY = date(2026, 11, 14)      # a Saturday


class NoKey:
    def __init__(self):
        raise RuntimeError("CONTEXT_DEV_API_KEY is not set")


def test_next_monday_is_always_ahead():
    assert next_monday(TODAY) == date(2026, 11, 16)
    assert next_monday(date(2026, 11, 16)) == date(2026, 11, 23)


def test_seed_makes_one_open_coffee_proposal_and_the_check_blocks_it(monkeypatch):
    monkeypatch.setattr(recalls_view, "ContextDev", NoKey)
    db, gw, _ = setup()
    out = seed(gw, today=TODAY, kitchen_id="hotel")
    assert out["status"] == "READY" and out["lines"] == [COFFEE] and out["has_coffee"]
    assert seed(gw, today=TODAY, kitchen_id="hotel")["proposal_id"] == out["proposal_id"]     # a replay
    view = recalls_view.run_check(gw, "hotel", {"idempotency_key": "demo"}, "chef")
    held = {row["proposal_id"]: row["status"] for row in view["alerts"][0]["proposals"]}
    assert held[out["proposal_id"]] == "BLOCKED_BY_RECALL"
    assert db.orders.count_documents({}) == 0


def test_seed_after_a_check_says_the_coffee_is_left_out(monkeypatch):
    monkeypatch.setattr(recalls_view, "ContextDev", NoKey)
    _, gw, _ = setup()
    recalls_view.run_check(gw, "hotel", {"idempotency_key": "first"}, "chef")
    out = seed(gw, today=TODAY, kitchen_id="hotel", key="late")
    assert not out["has_coffee"]
    assert out["excluded"] == [{"product_id": COFFEE, "reason": "BLOCKED_BY_RECALL"}]


class Gw:
    """Monday's quote leaves the coffee out (cut-off passed); Tuesday's holds it."""
    def __init__(self):
        self.asked = []

    def _quote(self, kitchen_id, request):
        self.asked.append(request["requested_date"])
        lines = [] if request["requested_date"] == "2026-11-16" else [{"product_id": COFFEE}]
        return {"simulation": {"lines": lines}}


def test_open_day_is_the_first_day_whose_quote_holds_the_coffee():
    from demo.recall_demo import open_day
    gw = Gw()
    assert open_day(gw, TODAY) == date(2026, 11, 17)
    assert gw.asked == ["2026-11-16", "2026-11-17"]
