"""Point-in-time demand features; no network or database access.

School holidays are kitchen/local calendar input, never inferred nationally.
Weather rows use the versioned signals.weather.normalize shape. Bookings/events
may be supplied on the same date/as_of snapshot by the kitchen integration.
"""
from datetime import date
from functools import lru_cache
import math
from copy import deepcopy


@lru_cache(maxsize=16)
def _public(year):
    import holidays
    return holidays.country_holidays("FI", years=year)


class CoverSignals:
    def __init__(self, kitchen, rows=()):
        self.kitchen = kitchen
        self.rows = {}
        for row in rows:
            if row["kitchen_id"] == kitchen.id:
                self.rows.setdefault(date.fromisoformat(row["date"]), []).append(deepcopy(row))

    def snapshot(self, day, origin):
        eligible = [r for r in self.rows.get(day, ())
                    if date.fromisoformat(r["as_of"]) <= origin]
        return max(eligible, key=lambda r: r["as_of"], default={})

    def features(self, day, origin):
        row = self.snapshot(day, origin)
        weather = row.get("weather") or {}
        values = [float(day.weekday() == d) for d in range(7)]
        angle = 2 * math.pi * day.isocalendar().week / 53
        school_holiday = row.get("is_school_holiday")
        if school_holiday is None:
            school_holiday = day.isocalendar().week in self.kitchen.type.holiday_weeks
        values += [math.sin(angle), math.cos(angle), float(day in _public(day.year)), float(school_holiday)]
        # Value + availability indicator: unknown is distinguishable from zero.
        for value, scale, boolean_ok in ((weather.get("temperature_2m_max"), 20, False),
                             (weather.get("precipitation_sum"), 10, False),
                             (row.get("events_flag"), 1, True),
                             (row.get("occupancy"), 1, False),
                             (row.get("reservations"), self.kitchen.base_covers, False)):
            known = (isinstance(value, (int, float)) and math.isfinite(value)
                     and (boolean_ok or not isinstance(value, bool)))
            values += [float(value) / scale if known else 0., float(known)]
        return values
