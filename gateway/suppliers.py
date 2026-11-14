"""Supplier adapters: live offers per supplier, in the engine's `Offer` shape (#73).

`ValioAdapter` reads Valio's price and availability. `ManualAdapter` serves a supplier
whose adapter is `manual` or `csv`: the price list is the kitchen's own products for
that supplier, stock is always unknown, and the cut-off comes from the supplier's
user-set terms. An unknown term stays unknown (None), never zero.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

from engine import Offer, allergen_codes, pack_info
from engine.offers import PlanLine, RequestPlan
from engine.packs import PackDataError, PackInfo
from store.products import get_product

VALIO = "sup-valio"
CENT = Decimal("0.01")
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
KITCHEN_TZ = ZoneInfo("Europe/Helsinki")   # `cutoff_time` is the kitchen's local time

Skipped = list[tuple[str, str]]
Tax = dict[str, Decimal | None]            # VAT rate in percent; None = unknown


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


class SupplierAdapter(Protocol):
    when: dict[str, dict]

    def offers(self, product_ids: list[str], measure: str,
               requested_date: date) -> tuple[list[Offer], Skipped, Tax]:
        """Offers the engine can plan with, the products left out (with a reason), VAT rates.
        After the call, `when` holds per product the delivery facts a line shows (#531)."""


class ValioAdapter:
    """Live Valio price and availability, converted for the engine."""

    def __init__(self, db, valio):
        self.db, self.valio, self.when = db, valio, {}

    def offers(self, product_ids: list[str], measure: str,
               requested_date: date) -> tuple[list[Offer], Skipped, Tax]:
        day = requested_date.isoformat()
        prices = {p["productId"]: p for p in self.valio.price(product_ids, day)["products"]}
        avail = {p["productId"]: p for p in self.valio.availability(product_ids, day)["products"]}
        offers, skipped, tax = [], [], {}
        for pid in product_ids:
            doc = get_product(self.db, pid, raw=True)
            price, stock = prices.get(pid) or {}, avail.get(pid) or {}
            if doc is None or not doc.get("raw"):
                skipped.append((pid, "not in the catalog"))
                continue
            if price.get("error") or not (price.get("catalogPrice") or {}).get("value"):
                skipped.append((pid, "no price from Valio"))
                continue
            lines = stock.get("scheduleLines") or []
            if not lines:
                skipped.append((pid, "Valio cannot deliver it on any date"))
                continue
            unit_price = _dec(price["catalogPrice"]["value"])
            cmp = price.get("comparisonPrice") or {}
            try:
                pack = pack_info(doc["raw"], price=unit_price, comparison_price=_dec(cmp.get("value")),
                                 comparison_unit=price.get("comparisonUnit"), measure=measure)
            except PackDataError as exc:
                skipped.append((pid, f"pack size unknown: {exc}"))
                continue
            line = lines[0]
            available_date = line.get("availableDate")
            offers.append(Offer(
                pid, (doc.get("names") or {}).get("en") or doc.get("name") or pid, pack, unit_price,
                _dec(line.get("availableAmount")),   # the client already turned sentinels into None
                stock.get("cutoff_passed"),
                date.fromisoformat(available_date) if available_date else None,
                bool(stock.get("salesBlock") or line.get("salesBlock")),
                allergen_data_known=not allergen_codes(doc),   # unknown allergen data is never safe (S02, S04)
                reliability=doc.get("reliability"),            # Valio CSV, delivered / ordered
                carbon=doc.get("carbon_kg_co2e_per_kg"),       # product-group average
                labels=tuple(doc.get("labels") or ()),
            ))
            # VAT (#1603): Valio's live tax rate wins; without it the catalog's vatCode rate;
            # else unknown (None). Never 0 % for a rate nobody gave.
            tax[pid], vat_source = vat_rate(price, doc)
            self.when[pid] = {"available_date": available_date, "cutoff_passed": stock.get("cutoff_passed"),
                              "closing_time": stock.get("closingTime"), "vat_source": vat_source}
        return offers, skipped, tax


def vat_rate(price: dict, row: dict | None) -> tuple[Decimal | None, str | None]:
    """`(rate in percent, vat_source)` of one Valio line (#1603): `valio_price` (the live
    `tax.taxRate`), `catalog` (the product row's `vat_rate`) or `(None, None)`."""
    live = (price.get("tax") or {}).get("taxRate")
    if live is not None:
        try:
            return Decimal(str(live)), "valio_price"
        except ArithmeticError:
            pass
    stored = (row or {}).get("vat_rate")
    return (Decimal(str(stored)), "catalog") if stored is not None else (None, None)


def manual_delivery(terms: dict, requested: date, now: datetime) -> tuple[bool | None, date | None]:
    """`(cutoff_passed, earliest delivery)` from the user-set terms.

    The next allowed order moment is the first order day whose cut-off is still ahead;
    the delivery is that day plus the lead time. When it lands after the requested
    date, the cut-off for this delivery has passed. A missing term: `(None, None)`.
    """
    days, clock, lead = terms.get("order_days"), terms.get("cutoff_time"), terms.get("lead_time_days")
    if not days or clock is None or lead is None:
        return None, None
    local = now.astimezone(KITCHEN_TZ)
    cutoff = time.fromisoformat(clock)
    for ahead in range(8):                 # 8: today's weekday again when today's cut-off passed
        day = local.date() + timedelta(days=ahead)
        if WEEKDAYS[day.weekday()] in days and (ahead > 0 or local.time() < cutoff):
            delivery = day + timedelta(days=int(lead))
            return delivery > requested, delivery
    return None, None


VALIO_SOURCE, TERMS_SOURCE, DEMO_SOURCE = "valio", "supplier_terms", "demo"
UNKNOWN_FACTS = {"cutoff_at": None, "cutoff_source": None, "lead_time_days": None,
                 "lead_time_source": None, "delivery_reliability": None, "reliability_source": None}


def latest_cutoff(order_days, clock: str, lead: int, delivery: date) -> datetime | None:
    """The last order moment (kitchen time) that still delivers by `delivery` with `lead` days."""
    for back in range(7):
        day = delivery - timedelta(days=int(lead) + back)
        if WEEKDAYS[day.weekday()] in order_days:
            return datetime.combine(day, time.fromisoformat(clock), KITCHEN_TZ)
    return None


def _first(*pairs):
    """The first `(value, source)` whose value is known; `(None, None)` when none is."""
    return next(((v, s) for v, s in pairs if v is not None), (None, None))


def delivery_facts(when: dict[str, dict], offers: list[Offer], terms: dict, demo: dict,
                   requested: date) -> dict[str, dict]:
    """Per product: `when` plus the cut-off, lead time and reliability a line shows (#1453).

    Display only: the engine never reads them. Real data wins: Valio's `closing_time` and CSV
    reliability, then the supplier's user-set terms, then the demo kitchen's demo values
    (store/demo_delivery.py), which are marked `demo` and are never Valio's numbers.
    """
    supplier, products = demo.get("supplier") or {}, demo.get("products") or {}
    reliability = {o.product_id: o.reliability for o in offers}
    out = {}
    for pid, facts in when.items():
        own = products.get(pid) or {}
        # Terms first (#1462): a per-product demo value never hides the supplier's real lead time.
        lead, lead_source = _first((terms.get("lead_time_days"), TERMS_SOURCE),
                                   (own.get("lead_time_days"), DEMO_SOURCE),
                                   (supplier.get("lead_time_days"), DEMO_SOURCE))
        days, days_source = _first((terms.get("order_days") or None, TERMS_SOURCE),
                                   (supplier.get("order_days") or None, DEMO_SOURCE))
        clock, clock_source = _first((terms.get("cutoff_time"), TERMS_SOURCE),
                                     (supplier.get("cutoff_time"), DEMO_SOURCE))
        cutoff, cutoff_source = facts.get("closing_time"), VALIO_SOURCE if facts.get("closing_time") else None
        if cutoff is None and None not in (lead, days, clock):
            available = facts.get("available_date")
            delivery = max(requested, date.fromisoformat(available)) if available else requested
            moment = latest_cutoff(days, clock, lead, delivery)
            if moment is not None:
                cutoff = moment.isoformat()
                cutoff_source = (DEMO_SOURCE if DEMO_SOURCE in (lead_source, days_source, clock_source)
                                 else TERMS_SOURCE)
        rel, rel_source = _first((reliability.get(pid), VALIO_SOURCE), (own.get("reliability"), DEMO_SOURCE),
                                 (supplier.get("reliability"), DEMO_SOURCE))
        out[pid] = {**facts, "cutoff_at": cutoff, "cutoff_source": cutoff_source,
                    "lead_time_days": None if lead is None else int(lead), "lead_time_source": lead_source,
                    # Text: the store refuses a binary float in an offer (#570); answers give a number.
                    "delivery_reliability": None if rel is None else str(rel), "reliability_source": rel_source}
    return out


class ManualAdapter:
    """A `manual` or `csv` supplier: the kitchen's own products are its price list."""

    def __init__(self, db, kitchen_id: str, supplier: dict, now: Callable[[], datetime]):
        self.db, self.kitchen_id, self.supplier, self.now = db, kitchen_id, supplier, now
        self.when: dict[str, dict] = {}

    def offers(self, product_ids: list[str], measure: str,
               requested_date: date) -> tuple[list[Offer], Skipped, Tax]:
        name = self.supplier.get("name") or self.supplier["supplier_id"]
        cutoff_passed, delivery = manual_delivery(self.supplier.get("terms") or {}, requested_date, self.now())
        offers, skipped, tax = [], [], {}
        for pid in product_ids:
            row = get_product(self.db, pid)
            if (row is None or row.get("source") != "own" or row.get("kitchen_id") != self.kitchen_id
                    or row.get("supplier_id") != self.supplier["supplier_id"]):
                skipped.append((pid, f"not on the price list of {name}"))
                continue
            price = _dec(row.get("unit_price_eur"))
            if price is None or price <= 0:
                skipped.append((pid, f"no price entered for {name}"))   # unknown, never zero
                continue
            content, unit = row.get("net_content"), row["base_unit"]
            # A request in the sales unit itself (a changed proposal line, #1480) counts sales
            # units, as pack_info does for Valio; else the net content converts L or KG.
            if unit == measure:
                pack = PackInfo(unit, unit, Decimal(1), Decimal(1), derived=False)
            elif content:
                pack = PackInfo(unit, content["unit"], _dec(content["value"]), Decimal(1), derived=False)
            else:
                skipped.append((pid, f"pack size unknown: no {measure} per {unit} entered"))
                continue
            offers.append(Offer(pid, (row.get("names") or {}).get("en") or pid, pack, price,
                                None,                  # a price list says nothing about stock
                                cutoff_passed, delivery,
                                allergen_data_known=not allergen_codes(row),
                                labels=tuple(row.get("labels") or ()), stock_source=name))
            rate = _dec(row.get("vat_rate"))           # entered by the kitchen, else unknown (#1603)
            tax[pid] = rate
            self.when[pid] = {"available_date": delivery.isoformat() if delivery else None,
                              "cutoff_passed": cutoff_passed, "closing_time": None,
                              "vat_source": None if rate is None else "entered"}
        return offers, skipped, tax


def _tier(tiers: list[dict], line: PlanLine) -> dict | None:
    """The tier with the highest `min_qty` at or below the line quantity, in the line's unit."""
    fits = [t for t in tiers
            if t.get("product_id") in (None, line.product_id) and t.get("unit") == line.unit
            and t.get("min_qty") is not None and t.get("unit_price_eur") is not None
            and _dec(t["min_qty"]) <= line.quantity]
    # Same break twice: the tier that names the product wins over the one for every product.
    return max(fits, key=lambda t: (_dec(t["min_qty"]), t.get("product_id") is not None), default=None)


def apply_discount_tiers(plan: RequestPlan, tiers_for: Callable[[str], list[dict]]) -> RequestPlan:
    """Re-price each line with its supplier's quantity break; `why` names the tier.

    `tiers_for(product_id)` returns the `discount_tiers` of that product's supplier.
    """
    def priced(line: PlanLine) -> PlanLine:
        tier = _tier(tiers_for(line.product_id), line)
        if tier is None:
            return line
        price = _dec(tier["unit_price_eur"])
        if price == line.unit_price:
            return line
        why = (f"{line.why} Discount tier applied: from {_dec(tier['min_qty']).normalize():f} {line.unit} "
               f"the price is {price.quantize(CENT, ROUND_HALF_UP)} EUR per {line.unit} "
               f"(list price {line.unit_price.quantize(CENT, ROUND_HALF_UP)}).")
        return replace(line, unit_price=price, why=why,
                       total=(line.quantity * price).quantize(CENT, ROUND_HALF_UP))

    lines = tuple(priced(line) for line in plan.lines)
    alternative = None if plan.alternative is None else apply_discount_tiers(plan.alternative, tiers_for)
    if lines == plan.lines and alternative is plan.alternative:
        return plan
    return replace(plan, lines=lines, total=sum((ln.total for ln in lines), Decimal("0.00")),
                   alternative=alternative)
