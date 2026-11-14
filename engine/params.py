"""Per-kitchen engine settings. The user can change every one (Aron, 2026-11-14 on #18)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal

# One-sided normal quantiles for the service levels we offer.
_Z = {Decimal("0.90"): 1.2816, Decimal("0.95"): 1.6449, Decimal("0.975"): 1.9600,
      Decimal("0.98"): 2.0537, Decimal("0.99"): 2.3263}


_CATEGORIES = ("fresh_dairy", "vegetables", "meat", "fish", "frozen", "dry", "other")


def _default_cover() -> dict[str, int]:
    return {"fresh_dairy": 4, "vegetables": 4, "meat": 3, "fish": 2, "frozen": 21,
            "dry": 30, "other": 14}


@dataclass(frozen=True)
class KitchenParams:
    service_level: dict[str, Decimal] = field(default_factory=lambda: {
        "A": Decimal("0.975"), "B": Decimal("0.95"), "C": Decimal("0.90")})
    max_cover_days: dict[str, int] = field(default_factory=_default_cover)
    stockout_cap: float = 1.8
    budget_warning_order_eur: Decimal | None = Decimal("1500")
    budget_warning_week_eur: Decimal | None = Decimal("5000")

    def z(self, abc: str | None) -> float:
        """Unknown class gets the A level: a missing value is never the safe one."""
        level = self.service_level.get(abc or "A", self.service_level["A"])
        if level in _Z:
            return _Z[level]
        from statistics import NormalDist
        return NormalDist().inv_cdf(float(level))

    def cover_days(self, category: str | None) -> int:
        return self.max_cover_days.get(category or "other", self.max_cover_days["other"])

    @classmethod
    def from_dict(cls, data: dict | None) -> "KitchenParams":
        """Build from stored kitchen settings; missing keys keep the defaults."""
        base = cls()
        if not data:
            return base
        changes: dict = {}
        if "service_level" in data:
            levels = {k: Decimal(str(v)) for k, v in data["service_level"].items()}
            for k, level in levels.items():
                if not Decimal(0) < level < Decimal(1):
                    raise ValueError(f"service_level {k} must be a fraction above 0 and below 1 "
                                     f"(97.5 % is 0.975), got {level}")
            changes["service_level"] = {**base.service_level, **levels}
        if "max_cover_days" in data:
            cover = {k: int(v) for k, v in data["max_cover_days"].items()}
            for k, days in cover.items():
                if k not in _CATEGORIES:
                    raise ValueError(f"max_cover_days key {k!r} is not one of "
                                     f"{', '.join(_CATEGORIES)}")
                if days < 1:
                    raise ValueError(f"max_cover_days {k} must be at least 1, got {days}")
            changes["max_cover_days"] = {**base.max_cover_days, **cover}
        if "stockout_cap" in data:
            cap = float(data["stockout_cap"])
            if not 1 <= cap <= 3:
                raise ValueError(f"stockout_cap must be from 1 to 3, got {cap}")
            changes["stockout_cap"] = cap
        for key in ("budget_warning_order_eur", "budget_warning_week_eur"):
            if key in data:
                changes[key] = None if data[key] is None else Decimal(str(data[key]))
        return replace(base, **changes)
