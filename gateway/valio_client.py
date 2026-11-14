"""Read-only Valio adapter. No upstream order submission exists."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json
import logging
import math
import os
import re
import threading
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


_log = logging.getLogger(__name__)

# Valio's rule (challenge Discord, 2026-11-14, #1237): a 429 blocks the caller for 30 s;
# a few hundred calls a minute is fine, more than 10 a second is not.
REST_SECONDS = 30          # the block after a 429 without a longer Retry-After
MAX_REST_SECONDS = 300     # a broken Retry-After never stops us for longer than this
RATE, BURST = 4, 5         # tokens a second, bucket size: never more than 9 calls in one second
MAX_WAIT = 5.0             # a call that would queue longer than this is not sent


class ValioError(RuntimeError):
    """A sanitized upstream failure; never includes credentials or response bodies."""


class ValioBusy(ValioError):
    """Valio is resting after a 429, or our own queue is too long: try after `retry_after` s."""

    def __init__(self, retry_after: int):
        self.retry_after = max(1, int(retry_after))
        super().__init__(f"Valio rate limit: wait {self.retry_after} s")


def _seconds(value: str) -> int | None:
    """Retry-After as whole seconds; None for an HTTP date or anything else."""
    return int(value) if re.fullmatch(r"[0-9]{1,6}", value) else None


class Gate:
    """When a call may go to Valio: a rest after a 429 and a token bucket. One `GATE` is
    shared by every client on the real transport in the process; thread-safe."""

    def __init__(self, rate: float | None = RATE, burst: int = BURST, *, max_wait: float = MAX_WAIT,
                 clock: Callable = time.monotonic, sleep: Callable = time.sleep):
        self.rate, self.burst, self.max_wait = rate, burst, max_wait
        self._clock, self._sleep = clock, sleep
        self._lock = threading.Lock()
        self._tokens, self._stamp = float(burst), None
        self._rest_until, self._resting = 0.0, False

    def remaining(self) -> int:
        """Whole seconds Valio still rests; 0 when calls may go."""
        with self._lock:
            return self._left(self._clock())

    def _left(self, now: float) -> int:
        left = self._rest_until - now
        if left > 0:
            return math.ceil(left)
        if self._resting:
            self._resting = False
            _log.info("Valio rate limit: the rest is over, calls go again")
        return 0

    def rest(self, retry_after: str = "") -> int:
        """Valio answered 429: no call goes until the rest is over. Returns its length."""
        seconds = min(max(_seconds(retry_after) or 0, REST_SECONDS), MAX_REST_SECONDS)
        with self._lock:
            until = self._clock() + seconds
            if until > self._rest_until:
                self._rest_until = until
            self._resting = True
        _log.warning("Valio answered HTTP 429: no calls for %d s", seconds)
        return seconds

    def acquire(self) -> None:
        """Wait briefly for a token, or fail fast with ValioBusy. Never sends anything."""
        with self._lock:
            now = self._clock()
            left = self._left(now)
            if left:
                raise ValioBusy(left)
            if self.rate is None:
                return
            if self._stamp is not None:
                self._tokens = min(float(self.burst), self._tokens + (now - self._stamp) * self.rate)
            self._stamp = now
            wait = 0.0 if self._tokens >= 1 else (1 - self._tokens) / self.rate
            if wait > self.max_wait:
                raise ValioBusy(math.ceil(wait))
            self._tokens -= 1         # reserved: later callers queue behind this one
        if wait:
            self._sleep(wait)
            left = self.remaining()   # a 429 may have come in while this call waited
            if left:
                raise ValioBusy(left)


GATE = Gate()


def closing_time(value: str | None) -> datetime | None:
    """Interpret naive upstream timestamps in Helsinki, preserving explicit offsets."""
    if not value:
        return None
    value = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value.replace("Z", "+00:00"))
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("Europe/Helsinki"))


def _transport(path: str, payload: dict | None, headers: dict) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = Request("https://junction26.valioaimo.fi" + path, data=data, headers=headers)
    with urlopen(request, timeout=20) as response:
        return json.load(response)


class ValioClient:
    def __init__(
        self, api_key: str | None = None, *, customer: str = "123", ttl: float = 30,
        retries: int = 2, transport: Callable = _transport, sleep: Callable = time.sleep,
        monotonic: Callable = time.monotonic,
        now: Callable = lambda: datetime.now(timezone.utc), gate: Gate | None = None,
    ):
        self._key = api_key if api_key is not None else os.environ.get("VALIO_API_KEY", "")
        if not self._key:
            raise ValueError("VALIO_API_KEY is required")
        if retries < 0 or ttl < 0 or not math.isfinite(ttl):
            raise ValueError("retries and ttl must be nonnegative and ttl finite")
        self.customer, self.ttl, self.retries = customer, ttl, retries
        self._transport, self._sleep = transport, sleep
        self._clock, self._now = monotonic, now
        self._cache: dict[tuple, tuple[float, dict]] = {}
        # For GET /health (#1188): live or a stand-in, and how the last real call went.
        # Set from calls the gateway makes anyway; /health never calls Valio itself.
        self.live = transport is _transport
        self.last_reachable: bool | None = None
        self.last_checked_at: datetime | None = None
        # Real Valio: the process-wide gate. A fake transport (tests, scenarios) reaches no
        # Valio, so it gets its own gate: the rest after a 429, no limiter.
        if gate is None:
            gate = GATE if transport is _transport else Gate(None, clock=monotonic, sleep=sleep)
        self._gate = gate

    def resting(self) -> int:
        """Whole seconds Valio still rests after a 429; 0 when calls may go."""
        return self._gate.remaining()

    def _read(self, path: str, payload: dict | None = None) -> dict:
        key = (path, json.dumps(payload, sort_keys=True))
        now = self._clock()
        self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
        if key in self._cache:
            return deepcopy(self._cache[key][1])
        headers = {"X-API-Key": self._key, "User-Agent": "2brothers/0.1", "Content-Type": "application/json"}
        for attempt in range(self.retries + 1):
            self._gate.acquire()      # ValioBusy during a rest: nothing is sent
            try:
                result = self._transport(path, payload, headers)
                self._seen(True)
                if not isinstance(result, dict):
                    raise ValioError("Valio returned an invalid JSON object")
                if self.ttl:
                    # Bound storage even if a caller varies products continuously.
                    if len(self._cache) >= 128:
                        self._cache.pop(next(iter(self._cache)))
                    self._cache[key] = (self._clock() + self.ttl, deepcopy(result))
                return deepcopy(result)
            except HTTPError as exc:
                retry_after = str(exc.headers.get("Retry-After", "") if exc.headers else "").strip()
                if exc.code == 429:   # never retried: a retry would fall inside Valio's block
                    self._seen(False)
                    raise ValioBusy(self._gate.rest(retry_after)) from None
                if not 500 <= exc.code < 600 or attempt == self.retries:
                    self._seen(False)
                    raise ValioError(f"Valio HTTP {exc.code}") from None
                delay = _seconds(retry_after)
                delay = 0.5 * 2**attempt if delay is None else delay
                self._sleep(min(delay, 30))
            except (URLError, TimeoutError, OSError):
                if attempt == self.retries:
                    self._seen(False)
                    raise ValioError("Valio network request failed") from None
                self._sleep(0.5 * 2**attempt)
            except (ValueError, TypeError):
                raise ValioError("Valio returned invalid data") from None
        raise AssertionError("unreachable")

    def _seen(self, ok: bool) -> None:
        self.last_reachable, self.last_checked_at = ok, self._now()

    def ping(self) -> dict:
        return self._read("/api/ping")

    def _products(self, path: str, products: list[str], requested_date: str | date) -> dict:
        if not products or any(not isinstance(p, str) or not p for p in products):
            raise ValueError("products must contain nonempty string codes")
        requested = date.fromisoformat(str(requested_date)).isoformat()
        combined = None
        for start in range(0, len(products), 1000):
            payload = {"customer": self.customer, "requestedDate": requested,
                       "products": products[start:start + 1000]}
            response = self._read(path, payload)
            if not isinstance(response.get("products"), list):
                raise ValioError("Valio response is missing products")
            if combined is None:
                combined = response
            else:
                combined["products"].extend(response["products"])
        return combined

    def price(self, products: list[str], requested_date: str | date) -> dict:
        """Preserve per-product error flags and absent prices; never substitute zero."""
        return self._products("/api/price", products, requested_date)

    def availability(self, products: list[str], requested_date: str | date) -> dict:
        result = self._products("/api/availability", products, requested_date)
        requested = date.fromisoformat(str(requested_date))
        for product in result["products"]:
            try:
                cutoff = closing_time(product.get("closingTime"))
            except (ValueError, TypeError):
                raise ValioError("Valio returned an invalid closingTime") from None
            product["closingTime"] = cutoff.isoformat() if cutoff else None
            product["cutoff_passed"] = cutoff <= self._now() if cutoff else None
            for line in product.get("scheduleLines", []):
                try:
                    available = date.fromisoformat(line.get("availableDate"))
                except (ValueError, TypeError):
                    available = None
                amount = line.get("availableAmount")
                # Valio, 14 Nov: 999999 or more (666666666, 9999999999, ...) is a filler, "we do not
                # know the availability"; "Empty = not available", so absent or null is zero.
                unknown = amount is not None and amount >= 999999
                if amount is None:
                    line["availableAmount"] = amount = 0
                line["unknown_stock"] = unknown
                if unknown:
                    line["availableAmount"] = None
                line["orderable"] = bool(
                    not product.get("salesBlock") and not line.get("salesBlock")
                    and product["cutoff_passed"] is False
                    and available is not None and available <= requested
                    and not unknown and amount > 0
                )
        return result
