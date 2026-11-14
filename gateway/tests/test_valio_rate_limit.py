"""Valio's rate limit (#1237): a 429 blocks us for 30 s, over 10 calls a second is not ok.

Every test uses a fake transport and a fake clock: nothing sleeps for real, nothing
reaches Valio."""

import logging
import unittest
from urllib.error import HTTPError

from gateway import valio_client
from gateway.valio_client import Gate, ValioBusy, ValioClient, ValioError


class Clock:
    """A fake monotonic clock; `sleep` moves it forward and records the wait."""

    def __init__(self):
        self.t, self.sleeps = 1000.0, []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def too_many(retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return HTTPError("hidden", 429, "Too Many Requests", headers, None)


class Valio:
    """Answers ok, or raises the queued errors first. Records each call's clock time."""

    def __init__(self, clock, errors=()):
        self.clock, self.errors, self.calls = clock, list(errors), []

    def __call__(self, path, payload, headers):
        self.calls.append(self.clock())
        if self.errors:
            raise self.errors.pop(0)
        return {"status": "ok", "products": []}


class RestTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.gate = Gate(clock=self.clock, sleep=self.clock.sleep)

    def client(self, valio, **kw):
        return ValioClient("test-not-a-real-key", transport=valio, gate=self.gate,
                           monotonic=self.clock, sleep=self.clock.sleep, **kw)

    def test_a_429_without_retry_after_stops_every_call_for_30_s_with_no_retry(self):
        valio = Valio(self.clock, [too_many()])
        first, other = self.client(valio, ttl=0), self.client(valio, ttl=0)
        with self.assertRaises(ValioBusy) as busy:
            first.ping()
        self.assertEqual(busy.exception.retry_after, 30)
        self.assertEqual(str(busy.exception), "Valio rate limit: wait 30 s")
        self.assertIsInstance(busy.exception, ValioError)       # old callers still catch it
        self.assertEqual(len(valio.calls), 1)                   # no retry inside the block
        self.assertEqual(self.clock.sleeps, [])                 # and no waiting it out in a request
        self.clock.t += 29.5
        for client in (first, other):                           # shared: the other client rests too
            with self.assertRaises(ValioBusy) as busy:
                client.ping()
            self.assertEqual(busy.exception.retry_after, 1)
        self.assertEqual(len(valio.calls), 1)
        self.assertEqual(other.resting(), 1)
        self.clock.t += 0.5
        self.assertEqual(other.resting(), 0)
        self.assertEqual(other.ping()["status"], "ok")
        self.assertEqual(len(valio.calls), 2)

    def test_a_longer_retry_after_is_honoured_and_a_shorter_one_is_not(self):
        for header, rest in [("45", 45), ("5", 30), ("Wed, 21 Oct 2026 07:28:00 GMT", 30), ("99999", 300), ("²", 30), (" 45 ", 45)]:
            with self.subTest(header=header):
                self.setUp()
                valio = Valio(self.clock, [too_many(header)])
                client = self.client(valio, ttl=0)
                with self.assertRaises(ValioBusy) as busy:
                    client.ping()
                self.assertEqual(busy.exception.retry_after, rest)
                self.clock.t += rest - 1
                with self.assertRaises(ValioBusy):
                    client.ping()
                self.clock.t += 1
                self.assertEqual(client.ping()["status"], "ok")
                self.assertEqual(len(valio.calls), 2)

    def test_a_cached_answer_is_still_served_during_a_rest(self):
        valio = Valio(self.clock)
        client = self.client(valio, ttl=30)
        client.price(["462775"], "2026-11-16")
        valio.errors.append(too_many())
        with self.assertRaises(ValioBusy):
            client.availability(["462775"], "2026-11-16")
        self.assertEqual(client.price(["462775"], "2026-11-16")["products"], [])   # from the cache
        self.assertEqual(len(valio.calls), 2)

    def test_a_503_still_retries_and_a_429_during_the_retries_stops_them(self):
        valio = Valio(self.clock, [HTTPError("hidden", 503, "x", {}, None)])
        self.assertEqual(self.client(valio, ttl=0).ping()["status"], "ok")
        self.assertEqual(len(valio.calls), 2)
        valio = Valio(self.clock, [HTTPError("hidden", 503, "x", {}, None), too_many()])
        with self.assertRaises(ValioBusy):
            self.client(valio, ttl=0).ping()
        self.assertEqual(len(valio.calls), 2)
        self.setUp()
        valio = Valio(self.clock, [HTTPError("hidden", 503, "x", {}, None)] * 3)
        with self.assertRaisesRegex(ValioError, "^Valio HTTP 503$"):
            self.client(valio, ttl=0).ping()
        self.assertEqual(len(valio.calls), 3)
        self.assertEqual(self.gate.remaining(), 0)              # a 5xx is not a rest

    def test_the_rest_is_logged_with_status_only_never_the_key(self):
        valio = Valio(self.clock, [too_many()])
        client = self.client(valio, ttl=0)
        with self.assertLogs("gateway.valio_client", logging.INFO) as logs:
            with self.assertRaises(ValioBusy):
                client.ping()
            self.clock.t += 30
            client.ping()
        text = "\n".join(logs.output)
        self.assertIn("429", text)
        self.assertIn("30 s", text)
        self.assertIn("rest is over", text)
        self.assertNotIn("test-not-a-real-key", text)


class LimiterTests(unittest.TestCase):
    def test_20_calls_in_one_go_are_spread_to_at_most_9_in_any_second(self):
        clock = Clock()
        gate = Gate(clock=clock, sleep=clock.sleep)
        valio = Valio(clock)
        client = ValioClient("test-not-a-real-key", transport=valio, gate=gate, ttl=0,
                             monotonic=clock, sleep=clock.sleep)
        for _ in range(20):
            client.ping()
        times = valio.calls
        self.assertEqual(len(times), 20)
        for start in times:                                     # every one-second window
            self.assertLessEqual(sum(1 for t in times if start <= t <= start + 1), 9)
        self.assertEqual(times[:5], [1000.0] * 5)               # a burst of 5 goes at once
        self.assertAlmostEqual(times[-1] - times[0], 15 / 4)    # then 4 a second
        self.assertTrue(all(0 < s <= 0.25 + 1e-9 for s in clock.sleeps))   # brief waits only

    def test_a_call_that_would_wait_more_than_5_s_is_not_sent(self):
        clock = Clock()
        # Concurrent callers: the clock does not move while each one waits for its turn.
        gate = Gate(clock=clock, sleep=lambda s: None)
        valio = Valio(clock)
        client = ValioClient("test-not-a-real-key", transport=valio, gate=gate, ttl=0,
                             monotonic=clock, sleep=lambda s: None)
        for _ in range(25):                                     # 5 at once, then 20 queued for up to 5 s
            client.ping()
        with self.assertRaises(ValioBusy) as busy:
            client.ping()
        self.assertEqual(busy.exception.retry_after, 6)
        self.assertEqual(len(valio.calls), 25)
        self.assertEqual(gate.remaining(), 0)                   # our own queue is not a Valio rest

    def test_clients_on_the_real_transport_share_one_gate_and_fakes_get_their_own(self):
        a, b = ValioClient("test-not-a-real-key"), ValioClient("test-not-a-real-key")
        self.assertIs(a._gate, valio_client.GATE)
        self.assertIs(b._gate, valio_client.GATE)
        fake = ValioClient("test-not-a-real-key", transport=lambda *a: {})
        self.assertIsNot(fake._gate, valio_client.GATE)
        self.assertEqual((valio_client.GATE.rate, valio_client.GATE.burst), (4, 5))


if __name__ == "__main__":
    unittest.main()
