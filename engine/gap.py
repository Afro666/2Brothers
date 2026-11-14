"""Fill a short order's gap with a substitute, by weight or volume, not by case count (S02).

Pure. The caller gives the plan that came up short, the original product's pack in a
common measure (KG or L), and the substitute offers in that measure. The engine sizes the
substitute for the gap; a person must say yes, so the result carries SUBSTITUTE_NEEDS_OK.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from engine.offers import Offer, RequestPlan, plan_request
from engine.packs import PackInfo
from engine.params import KitchenParams


def gap_in_measure(plan: RequestPlan, original: PackInfo) -> Decimal | None:
    """The plan's shortfall (in its own measure, e.g. cases) as the original pack's
    measure (e.g. kg): 4 cases x 8.4 kg = 33.6 kg. None when the measures cannot be
    linked: the plan's measure must be the original's sales unit."""
    if plan.shortfall <= 0 or plan.measure != original.sales_unit or original.size <= 0:
        return None
    return plan.shortfall * original.size


def fill_gap(plan: RequestPlan, original: PackInfo, substitutes: list[Offer], requested: date,
             params: KitchenParams | None = None) -> RequestPlan | None:
    """The engine-sized substitute for the gap, or None when there is no gap or no
    substitute fits. Every line says SUBSTITUTE_NEEDS_OK: the format changes, so a chef agrees."""
    gap = gap_in_measure(plan, original)
    if gap is None or not substitutes:
        return None
    sub = plan_request(gap, original.measure, substitutes, requested, params)
    if not sub.lines:
        return None
    lines = tuple(replace(ln, reason_codes=(*ln.reason_codes, "SUBSTITUTE_NEEDS_OK"),
                          why=ln.why + " Substitute for the missing part, sized by "
                          f"{original.measure}: a person says yes first.") for ln in sub.lines)
    return replace(sub, lines=lines, reason_codes=tuple(dict.fromkeys((*sub.reason_codes, "SUBSTITUTE_NEEDS_OK"))))
