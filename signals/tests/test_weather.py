from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import mongomock

from signals.weather import Location, WeatherError, collect, fetch_daily, normalize, request_url
from store.signals import list_daily, save_daily

AS_OF = date(2026, 11, 13)
LOCATION = Location("demo-helsinki", 60.1699, 24.9384)
FETCHED = datetime(2026, 11, 13, 20, tzinfo=timezone.utc)


def fixture():
    return json.loads((Path(__file__).parent / "fixtures/helsinki_daily.json").read_text())


class WeatherTests(unittest.TestCase):
    def test_recorded_window_provenance_units_and_holidays(self):
        rows = normalize(fixture(), LOCATION, AS_OF, fetched_at=FETCHED)
        self.assertEqual(len(rows), 98)
        self.assertEqual(sum(r["kind"] == "model_history" for r in rows), 84)
        self.assertEqual(sum(r["kind"] == "forecast" for r in rows), 14)
        self.assertEqual(rows[0]["date"], "2026-08-21")
        self.assertEqual(rows[-1]["date"], "2026-11-26")
        indexed = {r["date"]: r for r in rows}
        self.assertTrue(indexed["2026-10-31"]["is_public_holiday"])
        self.assertTrue(indexed["2026-10-31"]["holiday_names"])
        self.assertFalse(indexed["2026-11-13"]["is_public_holiday"])
        self.assertEqual(rows[0]["units"]["precipitation_sum"], "mm")
        self.assertEqual(rows[0]["fetched_at"], FETCHED.isoformat())

    def test_null_is_not_zero(self):
        data = fixture(); data["daily"]["temperature_2m_max"][0] = None
        row = normalize(data, LOCATION, AS_OF)[0]
        self.assertIsNone(row["weather"]["temperature_2m_max"])
        self.assertFalse(row["weather_complete"])

    def test_bad_window_units_or_measurements_are_rejected(self):
        mutations = [lambda d: d["daily"]["time"].pop(),
                     lambda d: d["daily_units"].update(temperature_2m_max="F"),
                     lambda d: d.update(timezone="UTC"),
                     lambda d: d["daily"]["temperature_2m_max"].__setitem__(0, float("nan")),
                     lambda d: d["daily"]["temperature_2m_min"].__setitem__(0, True),
                     lambda d: d["daily"]["precipitation_sum"].__setitem__(0, -1)]
        for change in mutations:
            data = fixture(); change(data)
            with self.assertRaises(WeatherError):
                normalize(data, LOCATION, AS_OF)

    def test_request_has_explicit_local_dates_and_no_key(self):
        queries = []
        def fetch(url):
            queries.append(parse_qs(urlsplit(url).query))
            return fixture()
        self.assertEqual(len(collect(LOCATION, as_of=AS_OF, fetch=fetch)), 98)
        self.assertEqual(queries[0]["timezone"], ["Europe/Helsinki"])
        self.assertEqual(queries[0]["start_date"], ["2026-08-21"])
        self.assertEqual(queries[0]["end_date"], ["2026-11-26"])
        self.assertNotIn("apikey", queries[0])

    def test_bad_location_is_rejected(self):
        for lat, lon in [(91, 24), (60, 181), (float("nan"), 24)]:
            with self.assertRaises(ValueError):
                Location("demo", lat, lon)

    def test_retryable_reads_are_bounded(self):
        errors, sleeps = [429, 503], []
        def opener(request, timeout):
            if errors:
                raise HTTPError("private-url", errors.pop(0), "private-body", {}, None)
            return io.BytesIO(json.dumps(fixture()).encode())
        result = fetch_daily(request_url(LOCATION, AS_OF), opener=opener, sleep=sleeps.append)
        self.assertEqual(len(result["daily"]["time"]), 98)
        self.assertEqual(sleeps, [0.5, 1])

    def test_network_error_is_sanitized_and_not_infinite(self):
        calls = []
        def opener(*args, **kwargs):
            calls.append(1)
            raise URLError("private-network-marker")
        with self.assertRaisesRegex(WeatherError, "^Open-Meteo network failure$"):
            fetch_daily("https://example.test", opener=opener, sleep=lambda _: None)
        self.assertEqual(len(calls), 3)


class StorageTests(unittest.TestCase):
    def test_idempotent_snapshots_and_kitchen_isolation(self):
        db = mongomock.MongoClient().signals_test
        rows = normalize(fixture(), LOCATION, AS_OF, fetched_at=FETCHED)
        self.assertEqual(save_daily(db, rows), 98)
        changed = deepcopy(rows); changed[0]["weather"]["temperature_2m_max"] = 42
        save_daily(db, changed)
        self.assertEqual(db.daily_signals.count_documents({}), 98)
        loaded = list_daily(db, LOCATION.kitchen_id, AS_OF - timedelta(days=84), AS_OF + timedelta(days=13), as_of=AS_OF)
        self.assertEqual(loaded[0]["weather"]["temperature_2m_max"], 42)
        self.assertEqual(list_daily(db, "other", AS_OF, AS_OF, as_of=AS_OF), [])
        next_vintage = deepcopy(rows)
        for row in next_vintage:
            row["as_of"] = "2026-11-14"
        save_daily(db, next_vintage)
        self.assertEqual(db.daily_signals.count_documents({}), 196)
        self.assertEqual(len(list_daily(db, LOCATION.kitchen_id, date(2026, 8, 21), date(2026, 11, 26), as_of=AS_OF)), 98)

    def test_invalid_batch_is_checked_before_any_writes(self):
        db = mongomock.MongoClient().signals_test
        rows = normalize(fixture(), LOCATION, AS_OF)
        rows[-1]["date"] = "bad-date"
        with self.assertRaises(ValueError):
            save_daily(db, rows)
        self.assertEqual(db.daily_signals.count_documents({}), 0)
