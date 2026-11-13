"""Read-only Valio adapter. No upstream order submission exists."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import json
import math
import os
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


class ValioError(RuntimeError):
    """A sanitized upstream failure; never includes credentials or response bodies."""


def closing_time(value: str | None) -> datetime | None:
    """Interpret naive upstream timestamps in Helsinki, preserving explicit offsets."""
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
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
        now: Callable = lambda: datetime.now(timezone.utc),
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

    def _read(self, path: str, payload: dict | None = None) -> dict:
        key = (path, json.dumps(payload, sort_keys=True))
        now = self._clock()
        self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
        if key in self._cache:
            return deepcopy(self._cache[key][1])
        headers = {"X-API-Key": self._key, "User-Agent": "2brothers/0.1", "Content-Type": "application/json"}
        for attempt in range(self.retries + 1):
            try:
                result = self._transport(path, payload, headers)
                if not isinstance(result, dict):
                    raise ValioError("Valio returned an invalid JSON object")
                if self.ttl:
                    # Bound storage even if a caller varies products continuously.
                    if len(self._cache) >= 128:
                        self._cache.pop(next(iter(self._cache)))
                    self._cache[key] = (self._clock() + self.ttl, deepcopy(result))
                return deepcopy(result)
            except HTTPError as exc:
                retry = exc.code == 429 or 500 <= exc.code < 600
                if not retry or attempt == self.retries:
                    raise ValioError(f"Valio HTTP {exc.code}") from None
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                delay = float(retry_after) if retry_after.isdigit() else 0.5 * 2**attempt
                self._sleep(min(delay, 30))
            except (URLError, TimeoutError, OSError):
                if attempt == self.retries:
                    raise ValioError("Valio network request failed") from None
                self._sleep(0.5 * 2**attempt)
            except (ValueError, TypeError):
                raise ValioError("Valio returned invalid data") from None
        raise AssertionError("unreachable")

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
        for product in result["products"]:
            try:
                cutoff = closing_time(product.get("closingTime"))
            except (ValueError, TypeError):
                raise ValioError("Valio returned an invalid closingTime") from None
            product["closingTime"] = cutoff.isoformat() if cutoff else None
            product["cutoff_passed"] = cutoff <= self._now() if cutoff else None
            for line in product.get("scheduleLines", []):
                amount = line.get("availableAmount")
                unknown = amount is None or amount in (999999, 9999999999)
                line["unknown_stock"] = unknown
                if unknown:
                    line["availableAmount"] = None
                line["orderable"] = bool(
                    not product.get("salesBlock") and not line.get("salesBlock")
                    and product["cutoff_passed"] is False
                    and line.get("availableDate") and not unknown and amount > 0
                )
        return result
