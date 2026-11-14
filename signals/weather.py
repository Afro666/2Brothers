"""Daily Open-Meteo weather and public holidays, versioned by issue date."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import importlib.metadata
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import holidays

ENDPOINT = "https://api.open-meteo.com/v1/forecast"
FIELDS = {"temperature_2m_max": "°C", "temperature_2m_min": "°C",
          "precipitation_sum": "mm", "weather_code": "wmo code"}


class WeatherError(RuntimeError):
    pass


@dataclass(frozen=True)
class Location:
    kitchen_id: str
    latitude: float
    longitude: float
    country: str = "FI"
    timezone: str = "Europe/Helsinki"

    def __post_init__(self):
        if not self.kitchen_id.strip():
            raise ValueError("kitchen_id is required")
        if not math.isfinite(self.latitude) or not -90 <= self.latitude <= 90:
            raise ValueError("invalid latitude")
        if not math.isfinite(self.longitude) or not -180 <= self.longitude <= 180:
            raise ValueError("invalid longitude")
        ZoneInfo(self.timezone)


def request_url(location: Location, as_of: date) -> str:
    return ENDPOINT + "?" + urlencode({
        "latitude": location.latitude, "longitude": location.longitude,
        "daily": ",".join(FIELDS), "timezone": location.timezone,
        "temperature_unit": "celsius", "precipitation_unit": "mm",
        "start_date": (as_of - timedelta(days=84)).isoformat(),
        "end_date": (as_of + timedelta(days=13)).isoformat(),
    })


def fetch_daily(url: str, *, opener=urlopen, sleep=time.sleep) -> dict:
    for attempt in range(3):
        try:
            with opener(Request(url, headers={"User-Agent": "2brothers-signals/0.1"}), timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            if (exc.code != 429 and not 500 <= exc.code < 600) or attempt == 2:
                raise WeatherError(f"Open-Meteo HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            if attempt == 2:
                raise WeatherError("Open-Meteo network failure") from None
        except (ValueError, TypeError):
            raise WeatherError("Open-Meteo returned invalid JSON") from None
        sleep(0.5 * 2**attempt)
    raise AssertionError("unreachable")


def normalize(payload: dict, location: Location, as_of: date, *, fetched_at=None) -> list[dict]:
    """Validate the full 98-day window; retain unknown measurements as null."""
    first, last = as_of - timedelta(days=84), as_of + timedelta(days=13)
    expected = [(first + timedelta(days=i)).isoformat() for i in range(98)]
    try:
        daily = payload["daily"]
        if payload["timezone"] != location.timezone or daily["time"] != expected:
            raise ValueError()
        for field, unit in FIELDS.items():
            if len(daily[field]) != 98 or payload["daily_units"][field].lower() != unit.lower():
                raise ValueError()
        calendar = holidays.country_holidays(location.country, years=range(first.year, last.year + 1),
                                             language="en_US", categories=holidays.PUBLIC)
        fetched_at = fetched_at or datetime.now(timezone.utc)
        if fetched_at.tzinfo is None:
            raise ValueError()
        rows = []
        for index, text in enumerate(expected):
            day = date.fromisoformat(text)
            weather = {field: daily[field][index] for field in FIELDS}
            for field, value in weather.items():
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                          or not math.isfinite(value)):
                    raise ValueError()
            if weather["precipitation_sum"] is not None and weather["precipitation_sum"] < 0:
                raise ValueError()
            rows.append({"kitchen_id": location.kitchen_id, "date": text, "as_of": as_of.isoformat(),
                "country": location.country, "timezone": location.timezone,
                "latitude": location.latitude, "longitude": location.longitude,
                "kind": "model_history" if day < as_of else "forecast",
                "weather": weather, "weather_complete": all(v is not None for v in weather.values()),
                "is_weekend": day.weekday() >= 5, "is_public_holiday": day in calendar,
                "holiday_names": calendar.get_list(day),
                "holiday_source": "python-holidays/" + importlib.metadata.version("holidays"),
                "weather_source": "Open-Meteo", "source_url": request_url(location, as_of),
                "fetched_at": fetched_at.isoformat(), "units": dict(FIELDS)})
        return rows
    except (KeyError, TypeError, ValueError, AttributeError, NotImplementedError):
        raise WeatherError("Invalid weather window, units, calendar or measurements") from None


def collect(location: Location, *, as_of=None, fetch=fetch_daily) -> list[dict]:
    as_of = as_of or datetime.now(ZoneInfo(location.timezone)).date()
    return normalize(fetch(request_url(location, as_of)), location, as_of)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kitchen-id", default="demo-helsinki")
    parser.add_argument("--latitude", type=float, default=60.1699)
    parser.add_argument("--longitude", type=float, default=24.9384)
    parser.add_argument("--country", default="FI")
    parser.add_argument("--timezone", default="Europe/Helsinki")
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--store", action="store_true", help="Upsert snapshots through store.signals into MongoDB")
    parser.add_argument("--out", type=Path, default=Path("signals/out/daily_signals.jsonl"))
    args = parser.parse_args()
    location = Location(args.kitchen_id, args.latitude, args.longitude, args.country, args.timezone)
    try:
        rows = collect(location, as_of=args.as_of)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        if args.store:
            from dotenv import load_dotenv
            from store.db import get_db
            from store.signals import save_daily
            load_dotenv(Path.cwd() / ".env", override=False)
            save_daily(get_db(), rows)
        print(json.dumps({"kitchen_id": location.kitchen_id, "rows": len(rows),
            "history_days": sum(r["kind"] == "model_history" for r in rows),
            "forecast_days": sum(r["kind"] == "forecast" for r in rows),
            "from": rows[0]["date"], "to": rows[-1]["date"], "stored": args.store,
            "output": str(args.out)}))
    except Exception as exc:
        # Only WeatherError text is sanitized; other messages may hold a connection string.
        detail = f"{type(exc).__name__}: {exc}" if isinstance(exc, WeatherError) else type(exc).__name__
        parser.exit(1, f"Signal collection failed ({detail}).\n")


if __name__ == "__main__":
    main()
