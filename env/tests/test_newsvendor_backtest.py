import unittest

from env.newsvendor_backtest import compare


class NewsvendorBacktest(unittest.TestCase):
    def test_newsvendor_costs_less_than_a_fixed_service_level(self):
        row = compare(seeds=(1,), kitchens=8, weeks=8)[0]
        self.assertLess(row["newsvendor"]["cost_eur"], row["reference"]["cost_eur"])
        self.assertLessEqual(row["newsvendor"]["waste_eur"], row["reference"]["waste_eur"])


if __name__ == "__main__":
    unittest.main()
