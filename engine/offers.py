"""A request ("1,000 L lactose-free milk by Monday") against live offers (S01, S02, S05, S12).

Rules:
- An offer whose cut-off passed, has no cut-off, is sales-blocked or arrives after the
  requested date cannot make this delivery: excluded, with a reason.
- Confirmed stock first, cheapest per measure first: certainty before price (Aron, S01).
- The rest goes on the cheapest offer with unknown stock, flagged; it is never shown as stock.
- What still cannot be covered is a shortfall, never silently dropped.
- When putting everything on the cheapest unknown offer is cheaper, that is the alternative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from engine.packs import PackInfo, to_sales_units
from engine.params import KitchenParams

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Offer:
    product_id: str
    name: str
    pack: PackInfo
    unit_price: Decimal                 # per sales unit, ex VAT
    available: Decimal | None           # in sales units; None = unknown (sentinel)
    cutoff_passed: bool | None          # None = no cut-off known
    available_date: date | None
    sales_block: bool = False

    @property
    def price_per_measure(self) -> Decimal:
        return self.unit_price / self.pack.size


@dataclass(frozen=True)
class PlanLine:
    product_id: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    total: Decimal
    unknown_stock: bool
    reason_codes: tuple[str, ...]
    why: str


@dataclass(frozen=True)
class RequestPlan:
    need: Decimal
    measure: str
    lines: tuple[PlanLine, ...]
    total: Decimal
    shortfall: Decimal                  # in measure, not covered by any line
    excluded: tuple[tuple[str, str], ...]   # (product_id, reason)
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    alternative: "RequestPlan | None" = field(default=None)


def _n(x: Decimal) -> str:
    return f"{x.normalize():f}"


def _exclude_reason(o: Offer, requested: date) -> str | None:
    if o.sales_block:
        return "sales block: cannot be ordered"
    if o.cutoff_passed is None:
        return "no cut-off time known: cannot promise this delivery"
    if o.cutoff_passed:
        return "order cut-off has passed for this delivery"
    if o.available_date is None:
        return "no delivery date known"
    if o.available_date > requested:
        return f"earliest delivery {o.available_date.isoformat()}, after {requested.isoformat()}"
    if o.available is not None and o.available <= 0:
        return "no stock"
    return None


def _line(o: Offer, qty: Decimal, codes: list[str], why: str) -> PlanLine:
    total = (qty * o.unit_price).quantize(CENT, ROUND_HALF_UP)
    if o.pack.derived:
        codes = [*codes, "PACK_SIZE_DERIVED"]
    return PlanLine(o.product_id, qty, o.pack.sales_unit, o.unit_price, total,
                    o.available is None, tuple(codes), why)


def _fill(need: Decimal, measure: str, usable: list[Offer], *, confirmed_first: bool) -> tuple[list[PlanLine], Decimal, set[str]]:
    lines: list[PlanLine] = []
    codes: set[str] = set()
    rest = need
    confirmed = sorted((o for o in usable if o.available is not None), key=lambda o: o.price_per_measure)
    unknown = sorted((o for o in usable if o.available is None), key=lambda o: o.price_per_measure)
    if confirmed_first:
        for o in confirmed:
            if rest <= 0:
                break
            qty, rounded = to_sales_units(rest, o.pack)
            cap = (o.available / o.pack.lot_size).to_integral_value(ROUND_FLOOR) * o.pack.lot_size
            line_codes = ["LOT_SIZE_ROUNDED"] if rounded and qty <= cap else []
            if qty > cap:
                qty = cap.normalize()
                line_codes.append("PARTIAL_STOCK")
                codes.add("PARTIAL_STOCK")
            if qty <= 0:
                continue
            got = qty * o.pack.size
            why = (f"{_n(qty)} {o.pack.sales_unit} of {o.name} = {_n(got)} {measure}, confirmed in stock"
                   + (f" (all {_n(o.available)} available)" if "PARTIAL_STOCK" in line_codes else "") + ".")
            lines.append(_line(o, qty, line_codes, why))
            codes.update(line_codes)
            rest -= got
    if rest > 0 and unknown:
        o = unknown[0]
        qty, rounded = to_sales_units(rest, o.pack)
        line_codes = ["STOCK_UNKNOWN"] + (["LOT_SIZE_ROUNDED"] if rounded else [])
        why = (f"{_n(qty)} {o.pack.sales_unit} of {o.name} = {_n(qty * o.pack.size)} {measure}: "
               f"cheapest per {measure} ({_n(o.price_per_measure.quantize(CENT))} EUR), "
               "but Valio does not report its stock, so it is not confirmed.")
        lines.append(_line(o, qty, line_codes, why))
        codes.update(line_codes)
        rest -= qty * o.pack.size
    return lines, max(rest, Decimal(0)), codes


def plan_request(need: Decimal, measure: str, offers: list[Offer], requested: date,
                 params: KitchenParams | None = None) -> RequestPlan:
    if need <= 0:
        raise ValueError("need must be positive")
    excluded: list[tuple[str, str]] = []
    usable: list[Offer] = []
    for o in offers:
        if o.pack.measure != measure:
            excluded.append((o.product_id, f"sold in {o.pack.measure}, request is in {measure}"))
            continue
        reason = _exclude_reason(o, requested)
        if reason:
            excluded.append((o.product_id, reason))
        else:
            usable.append(o)

    def build(confirmed_first: bool) -> RequestPlan:
        lines, shortfall, codes = _fill(need, measure, usable, confirmed_first=confirmed_first)
        if any("cut-off has passed" in r for _, r in excluded):
            codes.add("CLOSING_PASSED")
        if shortfall > 0:
            codes.add("PARTIAL_STOCK")
        total = sum((ln.total for ln in lines), Decimal("0.00"))
        warnings = ()
        if params and params.budget_warning_order_eur is not None and total > params.budget_warning_order_eur:
            warnings = ("OVER_BUDGET_WARNING",)
        order = ["CLOSING_PASSED", "PARTIAL_STOCK", "STOCK_UNKNOWN", "LOT_SIZE_ROUNDED", "PACK_SIZE_DERIVED"]
        codes |= {c for ln in lines for c in ln.reason_codes}
        return RequestPlan(need, measure, tuple(lines), total, shortfall, tuple(excluded),
                           tuple(c for c in order if c in codes), warnings)

    plan = build(confirmed_first=True)
    alt = build(confirmed_first=False)
    if alt.lines and alt.shortfall <= plan.shortfall and alt.total < plan.total and alt.lines != plan.lines:
        plan = RequestPlan(**{**plan.__dict__, "alternative": alt})
    return plan
