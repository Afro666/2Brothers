"""Small in-memory limits for the routes that spend Context.dev credits (#604, #652).

Everything here is process-local: it lives in this gateway process and is empty after a
restart. That is enough because the demo runs one gateway process; with several workers
each would keep its own counts, so the real limit would be the number times the workers.

No clock is read here: every method takes `now` (seconds, monotonic), so tests never sleep.
"""

from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict, deque
from contextlib import contextmanager

from gateway.service import GatewayError


def env_number(name: str, default: float) -> float:
    """A number from the environment; the default when it is missing, not a number or below 0."""
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if math.isfinite(value) and value >= 0 else default


class TooMany(GatewayError):
    """429 with the seconds to wait. `answer()` adds the Retry-After header."""

    def __init__(self, code: str, message: str, retry_after_s: float):
        self.retry_after_s = max(1, math.ceil(retry_after_s))
        super().__init__(429, code, message, retry_after_s=self.retry_after_s)

    def answer(self):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=429, headers={"Retry-After": str(self.retry_after_s)},
            content={"error": {"code": self.code, "message": self.message, **self.extra}})


class TTLCache:
    """key -> value until its own expiry; at most `max_entries`, the oldest goes first."""

    def __init__(self, max_entries: int = 256):
        self._max, self._rows, self._lock = max_entries, OrderedDict(), threading.Lock()

    def get(self, key, now: float):
        with self._lock:
            row = self._rows.get(key)
            if row is None:
                return None
            if now >= row[0]:
                del self._rows[key]
                return None
            return row[1]

    def put(self, key, value, ttl: float, now: float) -> None:
        if ttl <= 0:
            return
        with self._lock:
            self._rows.pop(key, None)
            self._rows[key] = (now + ttl, value)
            while len(self._rows) > self._max:
                self._rows.popitem(last=False)


class RateLimit:
    """At most `limit` hits per `window` seconds for one key (a sliding window)."""

    def __init__(self, max_keys: int = 4096):
        self._max, self._hits, self._lock = max_keys, OrderedDict(), threading.Lock()

    def hit(self, key, limit: float, window: float, now: float) -> float:
        """Count one hit. Returns 0 when it is allowed, else the seconds until one is."""
        if limit <= 0 or window <= 0:       # switched off
            return 0.0
        with self._lock:
            times = self._hits.setdefault(key, deque())
            self._hits.move_to_end(key)
            while times and times[0] <= now - window:
                times.popleft()
            if len(times) >= limit:
                return times[0] + window - now
            times.append(now)
            while len(self._hits) > self._max:      # many callers: forget the least recent
                self._hits.popitem(last=False)
            return 0.0


class KeyedLocks:
    """One lock per key, so one thing runs at a time per key. A key nobody holds is forgotten."""

    def __init__(self):
        self._rows: dict = {}                   # key -> [lock, users]
        self._guard = threading.Lock()

    @contextmanager
    def hold(self, key, wait: float):
        """Yields True with the key's lock held, or False when `wait` seconds were not enough."""
        with self._guard:
            row = self._rows.setdefault(key, [threading.Lock(), 0])
            row[1] += 1
        held = row[0].acquire(timeout=max(wait, 0))
        try:
            yield held
        finally:
            if held:
                row[0].release()
            with self._guard:
                row[1] -= 1
                if row[1] == 0:
                    self._rows.pop(key, None)
