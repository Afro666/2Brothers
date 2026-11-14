from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Event

import pytest

from agent.memory_cache import KitchenFactsCache


def test_cache_refreshes_and_isolates_kitchen_day_and_returned_data():
    clock = [0]
    cache = KitchenFactsCache(clock=lambda: clock[0], max_entries=2)
    calls = []
    def load():
        calls.append(True)
        return [{'value': len(calls)}]
    day = date(2026, 11, 14)
    result = cache.get('a', day, load)
    result[0]['value'] = 999
    assert cache.get('a', day, load) == [{'value': 1}]
    assert cache.get('b', day, load) == [{'value': 2}]
    assert cache.get('a', day + timedelta(days=1), load) == [{'value': 3}]
    assert cache.get('a', day, load) == [{'value': 4}]  # bounded cache evicted it
    clock[0] = 60
    assert cache.get('a', day, load) == [{'value': 5}]


def test_failed_reads_retry_and_worker_caches_are_independent():
    cache = KitchenFactsCache()
    def fail():
        raise RuntimeError('store unavailable')
    with pytest.raises(RuntimeError):
        cache.get('a', 'day', fail)
    assert cache.get('a', 'day', lambda: []) == []
    other_worker = KitchenFactsCache()
    assert other_worker.get('a', 'day', lambda: ['different database']) == ['different database']


def test_concurrent_memory_reads_share_one_load():
    cache = KitchenFactsCache()
    entered, release = Event(), Event()
    calls = []
    def load():
        calls.append(True)
        entered.set()
        assert release.wait(2)
        return ['facts']
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get, 'a', 'day', load)
        assert entered.wait(2)
        second = pool.submit(cache.get, 'a', 'day', load)
        release.set()
        assert first.result() == second.result() == ['facts']
    assert len(calls) == 1


def test_blocked_load_for_one_kitchen_does_not_block_another():
    cache = KitchenFactsCache()
    entered, release = Event(), Event()
    def slow():
        entered.set()
        assert release.wait(2)
        return ['a facts']
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get, 'a', 'day', slow)
        assert entered.wait(2)
        other = pool.submit(cache.get, 'b', 'day', lambda: ['b facts'])
        try:
            assert other.result(timeout=1) == ['b facts']
        finally:
            release.set()
        assert first.result() == ['a facts']
    assert cache._loading == {}
