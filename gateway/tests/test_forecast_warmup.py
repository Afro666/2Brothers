"""Forecast proof excludes unavailable history, never a genuine bad zero forecast."""
from datetime import date, datetime, timezone

import mongomock

from gateway.service import Gateway
from store.history import forecast_vs_actual


def add(db, collection, day, *, pid='milk', need=0, used=100, kitchen='k1', made_on=None):
    row = {'meta': {'kitchen_id': kitchen, 'product_id': pid},
           'ts': datetime.fromisoformat(day).replace(tzinfo=timezone.utc), 'unit': 'L'}
    row.update({'used': used, 'short': 0} if collection == 'kitchen_stock' else {'need': need, 'made_on': made_on})
    db[collection].insert_one(row)


def test_legacy_warmup_is_omitted_and_totals_use_the_same_pairs():
    db = mongomock.MongoClient(tz_aware=True).test
    # Another kitchen's older history must not make our first week eligible.
    add(db, 'kitchen_stock', '2026-08-10', kitchen='other')
    for day in ('2026-08-17', '2026-08-24'):
        add(db, 'kitchen_stock', day)
        add(db, 'forecasts', day, need=95, made_on=day)
        add(db, 'forecast_baseline', day, need=0, made_on=day)
    # Engine-only extra series must not change its scoring population.
    add(db, 'kitchen_stock', '2026-08-24', pid='bread', used=500)
    add(db, 'forecasts', '2026-08-24', pid='bread', need=0)
    methods = Gateway(db, None).forecast_accuracy('k1', '2026-08-17', '2026-08-30')['methods']
    for method in methods.values():
        assert [r['week'] for r in method['weeks']] == ['2026-W35']
        assert method['total']['actual'] == 100
        assert method['total']['series'] == 1
    # A zero prediction with history remains scored as a real error.
    assert methods['weekday-average']['total']['wape'] == 1


def test_history_outside_display_range_and_measured_zero_are_eligible():
    db = mongomock.MongoClient(tz_aware=True).test
    add(db, 'kitchen_stock', '2026-08-17', used=0)
    add(db, 'kitchen_stock', '2026-08-24', used=0)
    add(db, 'forecast_baseline', '2026-08-24', made_on='2026-08-24')
    assert forecast_vs_actual(db, 'k1', '2026-08-24', '2026-08-24', 'forecast_baseline') == [
        ('milk', date(2026, 8, 24), 0, 0)]


def test_history_must_precede_issuance_not_just_the_target_day():
    db = mongomock.MongoClient(tz_aware=True).test
    add(db, 'kitchen_stock', '2026-08-17')
    add(db, 'kitchen_stock', '2026-08-24')
    add(db, 'forecast_baseline', '2026-08-24', made_on='2026-08-17')
    assert forecast_vs_actual(db, 'k1', '2026-08-24', '2026-08-24', 'forecast_baseline') == []


def test_no_common_evaluation_data_produces_no_scored_weeks():
    db = mongomock.MongoClient(tz_aware=True).test
    add(db, 'kitchen_stock', '2026-08-17')
    add(db, 'forecasts', '2026-08-17', need=100)
    add(db, 'forecast_baseline', '2026-08-17', made_on='2026-08-17')
    methods = Gateway(db, None).forecast_accuracy('k1', '2026-08-17', '2026-08-17')['methods']
    assert all(m['weeks'] == [] and m['total']['series'] == 0 for m in methods.values())
