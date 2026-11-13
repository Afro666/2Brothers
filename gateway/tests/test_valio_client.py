from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import unittest
from urllib.error import HTTPError, URLError

from gateway.valio_client import ValioClient, ValioError, closing_time


def fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text())


class ValioTests(unittest.TestCase):
    def client(self, transport, **kw):
        return ValioClient("test-not-a-real-key", transport=transport, **kw)

    def test_recorded_prices_preserve_error_and_absent_price(self):
        result = self.client(lambda *args: fixture("price")).price(["462775"], "2026-11-16")
        self.assertEqual(result["products"][0]["catalogPrice"]["value"], 2.57)
        self.assertTrue(result["products"][-1]["error"])
        self.assertNotIn("catalogPrice", result["products"][-1])

    def test_recorded_milk_stock_and_cutoffs(self):
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        result = self.client(lambda *args: fixture("availability"), now=lambda: now).availability(["462775"], "2026-11-16")
        rows = result["products"]
        self.assertTrue(rows[0]["scheduleLines"][0]["orderable"])
        self.assertTrue(rows[1]["cutoff_passed"])
        for row in rows[1:3]:
            line = row["scheduleLines"][0]
            self.assertIsNone(line["availableAmount"])
            self.assertTrue(line["unknown_stock"])
            self.assertFalse(line["orderable"])
        self.assertEqual(rows[3]["scheduleLines"], [])

    def test_missing_cutoff_and_sales_blocks_fail_closed(self):
        for field, value in [("closingTime", None), ("salesBlock", True)]:
            data = fixture("availability")
            data["products"][0][field] = value
            result = self.client(lambda *args: data).availability(["462775"], "2026-11-16")
            self.assertFalse(result["products"][0]["scheduleLines"][0]["orderable"])
            if field == "closingTime":
                self.assertIsNone(result["products"][0]["cutoff_passed"])

    def test_available_date_must_be_valid_and_no_later_than_requested(self):
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        for available, expected in [("2026-11-16", True), ("2026-11-15", True),
                                    ("2026-11-17", False), (None, False),
                                    ("", False), ("2026-02-30", False), (17, False)]:
            with self.subTest(available=available):
                data = fixture("availability")
                data["products"][0]["scheduleLines"][0]["availableDate"] = available
                client = self.client(lambda *args: data, now=lambda: now)
                result = client.availability(["462775"], "2026-11-16")
                line = result["products"][0]["scheduleLines"][0]
                self.assertEqual(line["orderable"], expected)
                self.assertEqual(line["availableDate"], available)

    def test_missing_available_date_is_not_orderable(self):
        data = fixture("availability")
        del data["products"][0]["scheduleLines"][0]["availableDate"]
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        result = self.client(lambda *args: data, now=lambda: now).availability(["462775"], "2026-11-16")
        self.assertFalse(result["products"][0]["scheduleLines"][0]["orderable"])

    def test_unknown_stock_stays_visible_but_unconfirmed_with_future_cutoff(self):
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        for model in ["Terminal", "Stock"]:
            for amount in [999999, 9999999999, None]:
                with self.subTest(model=model, amount=amount):
                    data = fixture("availability")
                    original = data["products"][0]
                    original["logisticModel"] = model
                    original["scheduleLines"][0]["availableAmount"] = amount
                    result = self.client(lambda *args: data, now=lambda: now).availability(["462775"], "2026-11-16")
                    self.assertEqual(len(result["products"]), len(data["products"]))
                    product = result["products"][0]
                    self.assertEqual(product["productId"], "462775")
                    self.assertFalse(product["cutoff_passed"])
                    self.assertEqual(len(product["scheduleLines"]), 1)
                    line = product["scheduleLines"][0]
                    self.assertIsNone(line["availableAmount"])
                    self.assertTrue(line["unknown_stock"])
                    self.assertFalse(line["orderable"])

    def test_confirmed_zero_stock_is_unavailable_not_unknown(self):
        data = fixture("availability")
        data["products"][0]["scheduleLines"][0]["availableAmount"] = 0
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        result = self.client(lambda *args: data, now=lambda: now).availability(["462775"], "2026-11-16")
        line = result["products"][0]["scheduleLines"][0]
        self.assertEqual(line["availableAmount"], 0)
        self.assertFalse(line["unknown_stock"])
        self.assertFalse(line["orderable"])

    def test_1001_products_are_chunked_with_auth_and_user_agent(self):
        calls = []
        def transport(path, payload, headers):
            calls.append(deepcopy((path, payload, headers)))
            return {"products": [{"productId": p} for p in payload["products"]]}
        products = [str(i) for i in range(1001)]
        rows = self.client(transport).price(products, "2026-11-16")["products"]
        self.assertEqual([len(c[1]["products"]) for c in calls], [1000, 1])
        self.assertEqual([p["productId"] for p in rows], products)
        self.assertEqual(calls[0][2]["X-API-Key"], "test-not-a-real-key")
        self.assertTrue(calls[0][2]["User-Agent"])

    def test_cache_copy_expiry_and_cutoff_recomputed(self):
        clock, now, calls = [0], [datetime(2026, 11, 15, 14, 59, tzinfo=timezone.utc)], []
        def transport(*args):
            calls.append(1)
            return fixture("availability")
        client = self.client(transport, monotonic=lambda: clock[0], now=lambda: now[0])
        first = client.availability(["462775"], "2026-11-16")
        first["products"][0]["scheduleLines"].clear()
        now[0] += timedelta(minutes=2)
        second = client.availability(["462775"], "2026-11-16")
        self.assertTrue(second["products"][0]["cutoff_passed"])
        self.assertTrue(second["products"][0]["scheduleLines"])
        self.assertEqual(len(calls), 1)
        clock[0] = 31
        client.availability(["462775"], "2026-11-16")
        self.assertEqual(len(calls), 2)

    def test_retry_429_and_503_then_succeed(self):
        errors = [429, 503]
        sleeps = []
        def transport(*args):
            if errors:
                raise HTTPError("hidden", errors.pop(0), "hidden", {"Retry-After": "1"}, None)
            return {"status": "ok"}
        self.assertEqual(self.client(transport, sleep=sleeps.append).ping(), {"status": "ok"})
        self.assertEqual(sleeps, [1, 1])

    def test_no_auth_retry_and_no_secret_in_exception(self):
        calls = []
        def transport(*args):
            calls.append(1)
            raise HTTPError("secret-url", 401, "test-not-a-real-key", {}, None)
        with self.assertRaisesRegex(ValioError, "^Valio HTTP 401$"):
            self.client(transport).ping()
        self.assertEqual(len(calls), 1)

    def test_network_retries_bounded(self):
        calls = []
        def transport(*args):
            calls.append(1)
            raise URLError("test-not-a-real-key")
        with self.assertRaisesRegex(ValioError, "^Valio network request failed$"):
            self.client(transport, sleep=lambda _: None).ping()
        self.assertEqual(len(calls), 3)

    def test_naive_time_is_helsinki_in_summer_and_winter(self):
        self.assertEqual(closing_time("2026-07-01T12:00:00").utcoffset(), timedelta(hours=3))
        self.assertEqual(closing_time("2026-11-01T12:00:00").utcoffset(), timedelta(hours=2))

    def test_invalid_inputs_never_send_a_request(self):
        client = self.client(lambda *args: self.fail("unexpected request"))
        for codes, day in [([], "2026-11-16"), ([1], "2026-11-16"), (["1"], "bad-date")]:
            with self.assertRaises(ValueError):
                client.price(codes, day)

    def test_malformed_response_is_not_cached(self):
        client = self.client(lambda *args: [])
        with self.assertRaises(ValioError):
            client.ping()
        self.assertEqual(client._cache, {})
