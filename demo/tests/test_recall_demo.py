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


class Valio:
    """Monday's cut-off has passed; Tuesday is open."""
    def availability(self, products, day):
        passed = day == "2026-11-16"
        return {"products": [{"productId": COFFEE, "cutoff_passed": passed,
                              "scheduleLines": [{"availableDate": day, "availableAmount": 50}]}]}


class Gw:
    valio = Valio()


def test_open_day_skips_a_day_whose_cut_off_has_passed():
    from demo.recall_demo import open_day
    assert open_day(Gw(), TODAY) == date(2026, 11, 17)


def test_stock_alert_needs_no_seed(monkeypatch):
    """The coffee is on the shelf and no proposal holds it: the check alerts without `seed`."""
    from datetime import timedelta

    from monitor.tests.test_proposals import NOW
    from store.history import record_stock_count
    monkeypatch.setattr(recalls_view, "ContextDev", NoKey)
    db, gw, _ = setup()
    db.proposals.delete_many({})
    db.offers.delete_many({})
    record_stock_count(db, "hotel", NOW - timedelta(days=1),
                       [{"product_id": COFFEE, "unit": "KG", "on_hand": "3.253"}])
    view = recalls_view.run_check(gw, "hotel", {"idempotency_key": "shelf"}, "chef")
    [alert] = view["alerts"]
    assert alert["product_id"] == COFFEE and alert["where"] == ["in stock: 3.253 KG"]
    assert alert["proposals"] == [] and alert["status"] == "active"
    out = seed(gw, today=TODAY, kitchen_id="hotel", key="after")
    assert not out["has_coffee"] and out["excluded"] == [{"product_id": COFFEE, "reason": "BLOCKED_BY_RECALL"}]
