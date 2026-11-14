"""Delivery-note reader: a photo of the note becomes checked receipt lines (#362).

    python -m agent.receiving agent/fixtures/receiving/short.png      # recorded reply, offline
    python -m agent.receiving PHOTO.png --live                        # Nemotron VL on Verda

Nemotron 3.5 Super VL reads the note into NOTE_SCHEMA (agent/vision.py). Plain code then
matches it to the placed order, works out what is missing, and gives the stock after the
delivery. The next suggestion for the product is sized by the engine (engine.replenish).
An unreadable field stays "unknown": a missing quantity is never guessed, and an
unknown quantity gives an unknown stock ("count it"), never a number.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import sys

from agent.vision import VisionError, read_image

FIXTURES = Path(__file__).with_name("fixtures") / "receiving"
UNKNOWN = "unknown"

_text = {"type": "string", "maxLength": 120}
NOTE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["order_ref", "delivery_date", "lines"],
    "properties": {
        "order_ref": _text,
        "delivery_date": {"type": "string", "pattern": r"^(\d{4}-\d{2}-\d{2}|unknown)$"},
        "lines": {"type": "array", "maxItems": 50, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["product_code", "description", "quantity", "unit", "lot", "best_before", "replaces"],
            "properties": {
                "product_code": {"type": "string", "pattern": r"^(\d{6}|unknown)$"},
                "description": _text,
                "quantity": {"type": "string", "pattern": r"^(\d{1,6}(\.\d{1,3})?|unknown)$"},
                "unit": {"type": "string", "enum": ["ST", "KI", "KG", "L", "unknown"]},
                "lot": _text,
                "best_before": {"type": "string", "pattern": r"^(\d{4}-\d{2}-\d{2}|unknown)$"},
                "replaces": {"type": "string", "pattern": r"^(\d{6}|none|unknown)$"},
            }}},
    }}

INSTRUCTION = (
    "This is a photo of a food delivery note. Return every product line printed in the table. "
    "product_code: the 6-digit code. quantity: the number as printed, digits only. unit: as "
    "printed (ST, KI, KG or L). lot and best_before (YYYY-MM-DD) as printed. replaces: the "
    "6-digit code if the line says it is a substitute that replaces another product, else "
    "\"none\". Any field that is smudged, cut off or unclear: \"unknown\".")


def _qty(value: str) -> Decimal | None:
    return None if value == UNKNOWN else Decimal(value)


def _base(qty: Decimal | None, unit: str, units: dict) -> Decimal | None:
    """Note quantity in the product's base unit, via the catalog's units only."""
    if qty is None or unit not in units:
        return None
    return qty * Decimal(str(units[unit]))


def match_delivery(order: dict, note: dict) -> dict:
    """Compare the note with the order. `order` = {"lines": [{product_id, quantity, unit}],
    "catalog": {product_id: {"base_unit", "units": {unit_id: size_in_base}}}}."""
    catalog = order["catalog"]
    unreadable_code = any(ln["product_code"] == UNKNOWN for ln in note["lines"])
    by_code: dict[str, list] = {}
    for ln in note["lines"]:
        by_code.setdefault(ln["product_code"], []).append(ln)
    received = {}   # product_id -> base units received, None = unknown

    ordered_rows = []
    for line in order["lines"]:
        pid = line["product_id"]
        units = catalog[pid]["units"]
        want = _base(Decimal(str(line["quantity"])), line["unit"], units)
        got_lines = by_code.get(pid, [])
        parts = [_base(_qty(ln["quantity"]), ln["unit"], units) for ln in got_lines]
        got = None if any(p is None for p in parts) else sum(parts, Decimal(0))
        if got is None or want is None:
            # Unreadable quantity, or an ordered unit the catalog lacks: unknown, never a crash.
            status, missing = "UNKNOWN", None
        elif not got_lines:
            # An unreadable code may be this product: unknown, never "missing".
            status, missing = ("UNKNOWN", None) if unreadable_code else ("MISSING", want)
        elif got < want:
            status, missing = "SHORT", want - got
        else:
            status, missing = "RECEIVED", Decimal(0)
        received[pid] = None if status == "UNKNOWN" else (got if got_lines else Decimal(0))
        ordered_rows.append({"product_id": pid, "status": status, "ordered": _s(want),
                             "received": _s(received[pid]), "missing": _s(missing),
                             "base_unit": catalog[pid]["base_unit"],
                             "lots": [{"lot": ln["lot"], "best_before": ln["best_before"],
                                       "quantity": ln["quantity"], "unit": ln["unit"]} for ln in got_lines]})

    ordered_ids = {ln["product_id"] for ln in order["lines"]}
    others = []
    for ln in note["lines"]:
        code = ln["product_code"]
        if code in ordered_ids:
            continue
        if code == UNKNOWN:
            kind = "UNREADABLE"
        elif ln["replaces"] in ordered_ids or ln["replaces"] == UNKNOWN:
            # An unreadable "replaces" may be a substitute: unknown is never safe, a person checks.
            kind = "SUBSTITUTE"
        else:
            kind = "EXTRA"
        units = catalog.get(code, {}).get("units", {})
        base = _base(_qty(ln["quantity"]), ln["unit"], units)
        if code != UNKNOWN:
            prior = received.get(code, Decimal(0))
            received[code] = None if base is None or prior is None else prior + base
        others.append({"product_id": code, "status": kind, "replaces": ln["replaces"],
                       "quantity": ln["quantity"], "unit": ln["unit"], "received": _s(base),
                       "base_unit": catalog.get(code, {}).get("base_unit", UNKNOWN),
                       "lot": ln["lot"], "best_before": ln["best_before"],
                       "needs_approval": kind == "SUBSTITUTE"})
    return {"order_ref": note["order_ref"], "delivery_date": note["delivery_date"],
            "lines": ordered_rows, "not_ordered": others,
            "received": {k: _s(v) for k, v in received.items()},
            "complete": all(r["status"] == "RECEIVED" for r in ordered_rows) and not others}


def _s(x: Decimal | None) -> str | None:
    return None if x is None else format(x.normalize(), "f")


def stock_after(before: str | None, received: str | None) -> str | None:
    """Count after the delivery in base units; unknown in, unknown out ("count it")."""
    if before is None or received is None:
        return None
    return _s(Decimal(before) + Decimal(received))


def next_suggestion(item: dict, on_hand: str | None) -> dict:
    """The engine's next order for the product with the stock after this delivery."""
    from engine.packs import PackInfo
    from engine.params import KitchenParams
    from engine.quantity import Item, replenish

    pack = PackInfo(item["sales_unit"], item["measure"], Decimal(item["size"]), Decimal(item["lot_size"]), False)
    base = Item(item["product_id"], pack, item["daily_demand"], item["lead_time_days"], item["review_days"],
                None, safety_stock=item.get("safety_stock"))
    plan = replenish(replace(base, on_hand=None if on_hand is None else float(on_hand)), KitchenParams())
    return {"product_id": plan.product_id, "quantity": _s(plan.quantity), "unit": plan.unit,
            "reason_codes": list(plan.reason_codes), "why": plan.why}


class RecordedModel:
    """Replays a recorded Nemotron reply; checks the request carries the photo and schema."""

    def __init__(self, reply: dict):
        self.reply, self.requests = reply, []

    async def complete_json(self, messages, schema, name, **_):
        self.requests.append({"messages": messages, "schema": schema, "name": name})
        return self.reply


async def receive(photo: Path, order: dict, model) -> dict:
    note = await read_image(model, photo.read_bytes(), INSTRUCTION, NOTE_SCHEMA, "delivery_note")
    result = match_delivery(order, note)
    result["note"] = note
    result["stock"], result["next"] = {}, {}
    for item in order.get("items", []):
        pid = item["product_id"]
        after = stock_after(order["stock_before"].get(pid), result["received"].get(pid))
        result["stock"][pid] = after
        result["next"][pid] = next_suggestion(item, after)
    return result


def render(r: dict) -> str:
    out = [f"order {r['order_ref']}  delivered {r['delivery_date']}  "
           + ("complete" if r["complete"] else "NOT complete")]
    for ln in r["lines"]:
        miss = f", missing {ln['missing']}" if ln["missing"] not in (None, "0") else ""
        out.append(f"  {ln['status']:<10} {ln['product_id']}  ordered {ln['ordered']} {ln['base_unit']}, "
                   f"received {ln['received'] or 'unknown'}{miss}")
        for lot in ln["lots"]:
            out.append(f"             lot {lot['lot']}  best before {lot['best_before']}  {lot['quantity']} {lot['unit']}")
    for ln in r["not_ordered"]:
        out.append(f"  {ln['status']:<10} {ln['product_id']}  {ln['quantity']} {ln['unit']} = {ln['received'] or 'unknown'} "
                   f"{ln['base_unit']}" + (f", replaces {ln['replaces']} - needs a person's OK" if ln["needs_approval"] else ""))
    for pid, nxt in r["next"].items():
        stock = r["stock"][pid]
        out.append(f"  stock {pid} after delivery: {stock if stock is not None else 'unknown - count it'}")
        out.append(f"  next suggestion: {nxt['quantity']} {nxt['unit']}  ({nxt['why']})")
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Read a delivery-note photo and check it against the order")
    p.add_argument("photo", type=Path)
    p.add_argument("--order", type=Path, default=FIXTURES / "order.json")
    p.add_argument("--live", action="store_true", help="call Nemotron VL on Verda (uses inference credits)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    order = json.loads(a.order.read_text(encoding="utf-8"))

    async def go():
        if a.live:
            from dotenv import load_dotenv
            from agent.model import Nemotron
            from agent.usage import emit
            load_dotenv(Path.cwd() / ".env", override=False)
            model = Nemotron()
            try:
                return await receive(a.photo, order, model)
            finally:
                emit(model.meter, run="delivery_note")
                await model.close()
        recorded = a.photo.with_suffix(".reply.json")
        if not recorded.exists():
            p.error(f"no recorded reply {recorded.name}; use --live")
        return await receive(a.photo, order, RecordedModel(json.loads(recorded.read_text(encoding="utf-8"))))
    try:
        result = asyncio.run(go())
    except VisionError as exc:
        print(f"could not read the note: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if a.json else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
