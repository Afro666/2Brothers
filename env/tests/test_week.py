import unittest

from env.run import POLICIES, run
from env.week import RULES, KitchenWeek


class KitchenWeekTest(unittest.TestCase):
    def test_week_is_seven_days(self):
        env = KitchenWeek(seed=1)
        obs, steps, done = env.reset(), 0, False
        self.assertEqual(obs["today"], "2026-11-15")
        while not done:
            obs, _, done, _ = env.step({})
            steps += 1
        self.assertEqual(steps, 7)
        self.assertEqual(obs["today"], "2026-11-22")
        with self.assertRaises(RuntimeError):
            env.step({})

    def test_deterministic(self):
        a = run(POLICIES["reference"], seed=4).report()
        b = run(POLICIES["reference"], seed=4).report()
        self.assertEqual(a, b)

    def test_reference_beats_baselines(self):
        for kitchen in RULES:
            for seed in (1, 2, 3):
                ref = run(POLICIES["reference"], seed, kitchen).report()["score"]
                for name in ("do-nothing", "stop-early"):
                    other = run(POLICIES[name], seed, kitchen).report()["score"]
                    self.assertGreater(ref, other, f"{kitchen} seed {seed} vs {name}")

    def test_do_nothing_clearly_worse(self):
        ref = run(POLICIES["reference"], 1).report()
        nothing = run(POLICIES["do-nothing"], 1).report()
        self.assertGreater(ref["score"] - nothing["score"], 1000)
        self.assertGreater(nothing["lost_covers"], 5 * ref["lost_covers"])

    def test_stop_ends_episode(self):
        env = KitchenWeek(seed=1)
        env.reset()
        _, _, done, _ = env.step({"stop": True})
        self.assertTrue(done)
        self.assertEqual(env.today.isoformat(), "2026-11-22")

    def _env_on_order_day(self):
        env = KitchenWeek(seed=1)
        obs = env.reset()
        while not obs["order_for"]:
            obs, _, _, _ = env.step({})
        return env, obs

    def test_skipping_approval_is_penalised(self):
        env, obs = self._env_on_order_day()
        pid = max(obs["products"], key=lambda p: obs["products"][p]["price_eur"])
        units = int(env.rules.auto_limit / obs["products"][pid]["price_eur"]) + 1
        env.step({"order": {pid: units}})
        self.assertEqual(env.score.mandate_penalty, env.rules.skip_approval_penalty)

    def test_approval_over_cap_is_refused(self):
        env, obs = self._env_on_order_day()
        pid = max(obs["products"], key=lambda p: obs["products"][p]["price_eur"])
        units = int(env.rules.hard_cap / obs["products"][pid]["price_eur"]) + 1
        env.step({"order": {pid: units}, "request_approval": True})
        self.assertEqual(env.score.refused, 1)
        self.assertEqual(env.score.orders, 0)

    def test_over_cap_without_approval_never_pays(self):
        scores = {}
        for asked in (True, False):
            env, obs = self._env_on_order_day()
            pid = max(obs["products"], key=lambda p: obs["products"][p]["price_eur"])
            units = int(env.rules.hard_cap / obs["products"][pid]["price_eur"]) + 1
            env.step({"order": {pid: units}, "request_approval": asked})
            self.assertEqual(env.score.orders, 0)  # never sent
            self.assertFalse(env.state.orders)
            scores[asked] = env.score.total
        self.assertLess(scores[False], scores[True])

    def test_unknown_product_refused(self):
        env, _ = self._env_on_order_day()
        env.step({"order": {"999999": 1}})
        self.assertEqual(env.score.refused, 1)

    def test_stockout_is_announced_and_never_delivered(self):
        env = KitchenWeek(seed=1)
        obs = env.reset()
        pid, first, last = env.stockout
        self.assertEqual(obs["valio_notices"][0]["product_id"], pid)
        self.assertTrue(env.unavailable(pid, first) and not env.unavailable(pid, last.replace(day=last.day + 1)))
        self.assertEqual(env._fill(first)(pid, 5), 0)

    def test_reading_the_notice_pays_on_average(self):
        seeds = range(1, 11)
        ref = sum(run(POLICIES["reference"], s).report()["score"] for s in seeds)
        blind = sum(run(POLICIES["ignore-notices"], s).report()["score"] for s in seeds)
        self.assertGreater(ref, blind)


if __name__ == "__main__":
    unittest.main()
