from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from gateway import claim_check
from store import briefs

HELSINKI = ZoneInfo("Europe/Helsinki")
BAD_ORDER = {"CANCELLED", "CANCELED", "FAILED", "NOT_SENT", "SENT_READ_FAILED", "REJECTED", "REFUSED"}


def _dt(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return (parsed.replace(tzinfo=HELSINKI) if parsed.tzinfo is None else parsed).astimezone(HELSINKI)


def _day(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    parsed = _dt(value)
    if parsed:
        return parsed.date().isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None
    return None


def _dec(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _quantity(quantity, unit):
    number = _dec(quantity)
    if number is None or number < 0 or not isinstance(unit, str) or not unit.strip():
        return None
    return f"{format(number.normalize(), 'f')} {unit.strip()}"


def _stamp(value):
    parsed = _dt(value)
    return parsed.timestamp() if parsed else float("inf")


def _ref(document):
    value = document.get("event_id") or document.get("order_id") or document.get("_id")
    return str(value) if value is not None else ""


def _product(snapshot, product_id, lang):
    names = (snapshot["products"].get(str(product_id)) or {})
    return names.get(lang) or names.get("en") or names.get("fi") or (
        "unknown product" if lang == "en" else "tuntematon tuote")


def _supplier(snapshot, document, lang):
    supplier_id = document.get("supplier_id")
    name = snapshot["suppliers"].get(str(supplier_id)) if supplier_id is not None else None
    name = name or document.get("supplier_name")
    blocks = document.get("blocks") or []
    if not name and len(blocks) == 1 and isinstance(blocks[0], dict):
        name = blocks[0].get("name")
    return name or ("unknown supplier" if lang == "en" else "tuntematon toimittaja")


def _row(kind, ref_id, urgent, en, fi, lang):
    variants = {"en": en, "fi": fi}
    return {"kind": kind, "ref_id": str(ref_id), "urgent": urgent, "variants": [variants[lang], ("Kitchen update: " if lang == "en" else "Keittiön tilanne: ") + variants[lang]],
            "numbers": [str(number) for number in claim_check.numbers_in(variants[lang], lang)]}


def _add(rows, rank, when, ref_id, row):
    if str(ref_id):
        rows.append((rank, _stamp(when), str(ref_id), row))


def _bad_order(order):
    values = (str(order.get("status") or "").upper(), str(order.get("outcome") or "").upper())
    return any(value in BAD_ORDER or value.startswith("CANCEL") or value.endswith("_FAILED")
               for value in values)


def _requested_date(order):
    value = order.get("requested_date")
    receipt = order.get("receipt")
    if value is None and isinstance(receipt, dict):
        value = receipt.get("requested_date")
    return value


def _total(block, simulation):
    currency = block.get("currency") or simulation.get("currency")
    if currency and str(currency).upper() != "EUR":
        return None
    amount = _dec(block.get("expected_total"))
    if amount is not None:
        return amount
    lines = block.get("lines") or []
    if not lines:
        return None
    values = []
    for line in lines:
        quantity, price = _dec(line.get("quantity")), _dec(line.get("unit_price"))
        if quantity is None or price is None:
            return None
        values.append(quantity * price)
    return sum(values, Decimal(0))


def _proposal_groups(snapshot, item):
    offer = item["offer"]
    simulation = offer.get("simulation") or {}
    lines = simulation.get("lines") or []
    blocks = simulation.get("blocks") or []
    if not blocks:
        grouped = {}
        for line in lines:
            supplier_id = line.get("supplier_id") or simulation.get("supplier_id") or offer.get("supplier_id")
            key = str(supplier_id) if supplier_id is not None else "unknown"
            grouped.setdefault(key, {"supplier_id": supplier_id, "lines": []})["lines"].append(line)
        blocks = list(grouped.values()) or [{"supplier_id": simulation.get("supplier_id")}]
    result = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        supplier_id = block.get("supplier_id") or simulation.get("supplier_id") or offer.get("supplier_id")
        name = snapshot["suppliers"].get(str(supplier_id)) if supplier_id is not None else None
        name = name or block.get("supplier_name") or block.get("name")
        key = str(supplier_id) if supplier_id is not None else ("name:" + name if name else "unknown")
        result.append([key, name, _total(block, simulation)])
    if len(result) == 1 and result[0][2] is None:
        result[0][2] = _total(simulation, simulation)
    return result


def collect(gateway, kitchen, when, lang):
    if when not in ("morning", "evening") or lang not in ("en", "fi"):
        raise ValueError("unsupported brief period or language")
    snap = briefs.snapshot(gateway.db, kitchen)
    now = gateway.now()
    now = (now.replace(tzinfo=HELSINKI) if now.tzinfo is None else now).astimezone(HELSINKI)
    today = now.date()
    tomorrow_noon = datetime.combine(today + timedelta(days=1), time(12), HELSINKI)
    essential, active_proposals = [], []

    for item in snap["proposals"]:
        proposal = item["proposal"]
        ref_id = _ref(proposal)
        valid = _dt(item["offer"].get("valid_until"))
        if valid is None or valid <= now:
            continue
        simulation = item["offer"].get("simulation") or {}
        closing = [_dt(line.get("closing_time")) for line in simulation.get("lines") or []]
        cutoff = min((d for d in closing if d), default=None)
        due = cutoff and ((cutoff.date() == today) if when == "morning"
                          else (now <= cutoff <= tomorrow_noon))
        if due:
            stamp = cutoff.strftime("%Y-%m-%d %H:%M")
            details = []
            for line in (simulation.get('lines') or [])[:3]:
                product = _product(snap, line.get('product_id'), lang)
                quantity = _quantity(line.get('quantity'), line.get('unit'))
                details.append(product + (f': {quantity}' if quantity else ''))
            names = ', '.join(filter(None, (g[1] for g in _proposal_groups(snap, item))))
            description = '; '.join(details)
            total = _dec(simulation.get('expected_total'))
            if total is not None:
                description += f'; EUR {total:.2f}'
            en = f"Draft closes at {stamp}: {description}" + (f' ({names})' if names else '') + '.'
            fi = f"Luonnoksen tilausaika päättyy {stamp}: {description}" + (f' ({names})' if names else '') + '.'
            _add(essential, 0, cutoff, ref_id,
                 _row("CUTOFF", ref_id, cutoff.date() == today, en, fi, lang))
        active_proposals.append(item)

    context = snap["recall_context"] or {}
    stock, recipes = context.get("stock") or {}, context.get("recipes") or {}
    waiting_products = {str(product_id) for product_id in context.get("proposal") or []}
    for alert in snap["alerts"]:
        product_id, ref_id = alert.get("product_id"), _ref(alert)
        pid = str(product_id) if product_id is not None else ""
        held = stock.get(pid)
        on_hand = _dec(held[0]) if isinstance(held, (list, tuple)) and held else None
        quantity = _quantity(on_hand, held[1]) if on_hand is not None and len(held) > 1 else None
        product = _product(snap, product_id, lang)
        if on_hand is not None and on_hand > 0:
            en = f"Active recall for {product}: {quantity + ' in stock' if quantity else 'positive stock is present'}."
            fi = f"Aktiivinen takaisinveto: {product}: {('varastossa ' + quantity) if quantity else 'varastosaldo on positiivinen'}."
        elif pid in waiting_products:
            en = f"Active recall for {product}: the product is in an open proposal."
            fi = f"Aktiivinen takaisinveto: {product} on avoimessa ehdotuksessa."
        elif pid in recipes:
            en = f"Active recall for {product}: the product is used in a recipe."
            fi = f"Aktiivinen takaisinveto: {product} on reseptissä."
        else:
            continue
        _add(essential, 1, alert.get("detected_at"), ref_id,
             _row("RECALL", ref_id, True, en, fi, lang))

    for offer in snap["supplier_offers"]:
        requested = _day(offer.get("requested_date"))
        ref_id = _ref(offer)
        if not requested or requested < today.isoformat():
            continue
        supplier = _supplier(snap, offer, lang)
        product = _product(snap, offer.get("product_id"), lang)
        quantity = _quantity(offer.get("quantity"), offer.get("unit"))
        item = f"{quantity} {product}" if quantity else product
        en = f"Open supplier offer from {supplier} for {item}, requested for {requested}."
        fi = f"Avoin tarjous toimittajalta {supplier}: {item}, pyydetty päiväksi {requested}."
        _add(essential, 2, requested, ref_id,
             _row("SUPPLIER_OFFER", ref_id, False, en, fi, lang))

    orders = {str(order.get("order_id") or order.get("_id")): order
              for order in snap["orders"] if not _bad_order(order)}
    if when == "morning":
        for ref_id, order in orders.items():
            requested = _day(_requested_date(order))
            if requested != today.isoformat():
                continue
            supplier = _supplier(snap, order, lang)
            en = f"Order {ref_id} from {supplier} has requested delivery on {requested}."
            fi = f"Tilauksen {ref_id} pyydetty toimituspäivä on {requested}; toimittaja on {supplier}."
            _add(essential, 3, requested, ref_id,
                 _row("DELIVERY", ref_id, False, en, fi, lang))
    else:
        audits = [row for row in snap["audit"]
                  if (row.get("event") or {}).get("kind") == "delivery_note_read"
                  and _day((row.get("server") or {}).get("at")) == today.isoformat()]
        audits.sort(key=lambda row: (_stamp((row.get("server") or {}).get("at")), str(row.get("_id"))),
                    reverse=True)
        seen = set()
        for entry in audits:
            event = entry.get("event") or {}
            ref_id = str(event.get("order_id") or "")
            if ref_id not in orders or ref_id in seen:
                continue
            seen.add(ref_id)
            statuses = event.get("statuses") or {}
            counts = {}
            for status in ("SHORT", "MISSING", "SUBSTITUTE"):
                count = _dec(statuses.get(status))
                if count is not None and count >= 0 and count == count.to_integral_value():
                    counts[status] = int(count)
            if not any(counts.values()):
                continue
            detail = ", ".join(f"{status} {count}" for status, count in counts.items())
            en = f"Delivery-note check for order {ref_id}: {detail}."
            fi = f"Toimituslähetteen tarkistus tilaukselle {ref_id}: {detail}."
            _add(essential, 3, (entry.get("server") or {}).get("at"), ref_id,
                 _row("DELIVERY_CHECK", ref_id, False, en, fi, lang))

    represented = {entry[2] for entry in sorted(essential)[:6] if entry[3]["kind"] == "CUTOFF"}
    grouped = {}
    for item in active_proposals:
        ref_id = _ref(item["proposal"])
        if ref_id in represented:
            continue
        for key, name, total in _proposal_groups(snap, item):
            group = grouped.setdefault(key, {"ref_id": ref_id, "name": name, "count": 0, "total": Decimal(0),
                                             "complete": True})
            group["name"] = group["name"] or name
            group["count"] += 1
            if total is None:
                group["complete"] = False
            else:
                group["total"] += total

    waiting = []
    for ref_id, group in grouped.items():
        count = group["count"]
        name = group["name"] or ("unknown supplier" if lang == "en" else "tuntematon toimittaja")
        noun = "draft" if count == 1 else "drafts"
        if group["complete"]:
            amount = format(group["total"].quantize(Decimal("0.01")), ".2f")
            en = f"{count} READY {noun} for {name}, EUR {amount} in total."
            fi = f"{count} READY-luonnosta toimittajalle {name}, yhteensä {amount} EUR."
        else:
            en = f"{count} READY {noun} for {name}; the EUR total is not fully known."
            fi = f"{count} READY-luonnosta toimittajalle {name}; EUR-summa ei ole täysin tiedossa."
        waiting.append((4, float("inf"), ref_id, _row("WAITING_DRAFTS", group['ref_id'], False, en, fi, lang)))

    unconfirmed = []
    for ref_id, order in orders.items():
        if not order.get("supplier_must_confirm"):
            continue
        supplier = _supplier(snap, order, lang)
        en = f"Order {ref_id} from {supplier} still requires supplier confirmation."
        fi = f"Tilaus {ref_id} toimittajalta {supplier} vaatii edelleen toimittajan vahvistuksen."
        _add(unconfirmed, 5, order.get("updated_at") or order.get("created_at"), ref_id,
             _row("UNCONFIRMED", ref_id, False, en, fi, lang))

    return [entry[3] for entry in sorted(essential + waiting + unconfirmed)[:6]]
