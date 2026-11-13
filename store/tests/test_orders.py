from decimal import Decimal
import unittest

from store import orders


class GuardTests(unittest.TestCase):
    """The guards run before any database call, so `db=None` is enough here."""

    def test_binary_floats_are_refused_for_money(self):
        with self.assertRaises(TypeError):
            orders.save_offer(None, {"lines": [{"unit_price": 2.57}]})
        with self.assertRaises(TypeError):
            orders.record_attempt(None, idempotency_key="k", offer_id="o", expected_total=149.02,
                                  lines=[], payload_hash="h")

    def test_stock_sentinels_are_never_stored(self):
        for sentinel in (999999, 9999999999, Decimal("999999")):
            with self.assertRaises(ValueError):
                orders.save_offer(None, {"lines": [{"available_amount": sentinel}]})

    def test_outcome_and_decision_values_follow_the_contract(self):
        with self.assertRaises(ValueError):
            orders.set_outcome(None, "o1", outcome="DONE", status="PLACED")
        with self.assertRaises(ValueError):
            orders.decide_approval(None, "a1", status="AUTO", decided_by="chef")
        with self.assertRaises(ValueError):
            orders.decide_approval(None, "a1", status="APPROVED", decided_by="")


if __name__ == "__main__":
    unittest.main()
