"""Snap the shelf: a photo of the walk-in fridge becomes a stock count to confirm (#373).

    python -m agent.shelf agent/fixtures/shelf/shelf.png          # recorded reply, offline
    python -m agent.shelf PHOTO.png --live                        # Nemotron VL on Verda

Nemotron 3.5 Super VL lists what it sees: {label, count, confidence} per product
(agent/vision.py, strict schema). Plain code matches each label to the kitchen's
products by name. Nothing becomes a number by itself:
  COUNTED       matched, count read, confidence high or medium: a suggestion to confirm;
  PLEASE_COUNT  low confidence or an unreadable count: the person counts, no number;
  UNMATCHED     the label fits no product, or fits two: the person picks the product.
The output is the body for POST /v1/kitchens/{k}/stock-counts (docs/contract.md).
`on_hand` is null for every row a person has not confirmed: unknown, never zero.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import re
import sys

from agent.vision import VisionError, read_image

FIXTURES = Path(__file__).with_name("fixtures") / "shelf"
UNKNOWN = "unknown"
MIN_SCORE = 0.6     # share of the product name's words the label must match

SHELF_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "maxItems": 40, "items": {
        "type": "object", "additionalProperties": False, "required": ["label", "count", "confidence"],
        "properties": {
            "label": {"type": "string", "maxLength": 120},
            "count": {"type": "string", "pattern": r"^(\d{1,4}|unknown)$"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        }}}}}

INSTRUCTION = (
    "This is a photo of a kitchen fridge shelf. List each distinct product you can see, once. "
    "label: the product text exactly as printed on the pack (brand, name, size). count: how many "
    "packs of that product are visible, as digits. confidence: high if every pack is fully "
    "visible and the label is readable, medium if you are fairly sure, low if packs are hidden, "
    "cut off or the label is partly unreadable. If you cannot count them, count is \"unknown\".")


def _words(text: str) -> set[str]:
    """Words and numbers apart, so "1L" and "1 L" match; "3%" stays one word."""
    return set(re.findall(r"\d+(?:[.,]\d+)?%?|[a-z]+", text.lower()))


def match_product(label: str, products: list[dict]) -> dict | None:
    """The one product whose name the label covers best; None if none fits or two tie."""
    seen = _words(label)
    scored = sorted(((len(seen & _words(p["name"])) / len(_words(p["name"])), p) for p in products),
                    key=lambda sp: -sp[0])
    if not scored or scored[0][0] < MIN_SCORE:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][1]


def count_rows(reply: dict, products: list[dict]) -> list[dict]:
    rows = []
    for item in reply["items"]:
        product = match_product(item["label"], products)
        count = None if item["count"] == UNKNOWN else int(item["count"])
        if product is None:
            status = "UNMATCHED"
        elif count is None or item["confidence"] == "low":
            status = "PLEASE_COUNT"
        else:
            status = "COUNTED"
        rows.append({"label": item["label"], "confidence": item["confidence"],
                     "product_id": product and product["product_id"], "name": product and product["name"],
                     "packs": count if status == "COUNTED" else None, "status": status})
    return rows


def stock_count_body(rows: list[dict], products: list[dict], confirmed: dict[str, int],
                     counted_at: datetime, idempotency_key: str) -> dict:
    """The POST /stock-counts body. `confirmed` = {product_id: packs a person confirmed}.
    A product the person did not confirm is sent as null: unknown, never zero."""
    if counted_at.tzinfo is None:
        raise ValueError("counted_at must carry a timezone")
    seen = {r["product_id"] for r in rows if r["product_id"]}
    counts = []
    for p in products:
        if p["product_id"] not in seen and p["product_id"] not in confirmed:
            continue
        packs = confirmed.get(p["product_id"])
        on_hand = None if packs is None else format((Decimal(packs) * Decimal(p["pack_size"])).normalize(), "f")
        counts.append({"product_id": p["product_id"], "on_hand": on_hand, "unit": p["unit"]})
    return {"idempotency_key": idempotency_key, "counted_at": counted_at.isoformat(),
            "source": "manual", "counts": counts}


class RecordedModel:
    def __init__(self, reply: dict):
        self.reply, self.requests = reply, []

    async def complete_json(self, messages, schema, name, **_):
        self.requests.append({"messages": messages, "schema": schema, "name": name})
        return self.reply


async def read_shelf(photo: Path, products: list[dict], model) -> list[dict]:
    reply = await read_image(model, photo.read_bytes(), INSTRUCTION, SHELF_SCHEMA, "shelf_count")
    return count_rows(reply, products)


def render(rows: list[dict]) -> str:
    out = []
    for r in rows:
        what = f"{r['product_id']} {r['name']}" if r["product_id"] else "no product - pick one"
        n = f"{r['packs']} packs" if r["packs"] is not None else "please count"
        out.append(f"  {r['status']:<12} {n:<13} {what}   (read: \"{r['label']}\", {r['confidence']})")
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Read a fridge shelf photo into a stock count to confirm")
    p.add_argument("photo", type=Path)
    p.add_argument("--products", type=Path, default=FIXTURES / "kitchen.json")
    p.add_argument("--live", action="store_true", help="call Nemotron VL on Verda (uses inference credits)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--confirm-all", action="store_true",
                   help="print the POST /stock-counts body as if a person confirmed every COUNTED row")
    a = p.parse_args(argv)
    products = json.loads(a.products.read_text(encoding="utf-8"))["products"]

    async def go():
        if a.live:
            from dotenv import load_dotenv
            from agent.model import Nemotron
            load_dotenv(Path.cwd() / ".env", override=False)
            model = Nemotron()
            try:
                return await read_shelf(a.photo, products, model)
            finally:
                await model.close()
        recorded = a.photo.with_suffix(".reply.json")
        if not recorded.exists():
            p.error(f"no recorded reply {recorded.name}; use --live")
        return await read_shelf(a.photo, products, RecordedModel(json.loads(recorded.read_text(encoding="utf-8"))))
    try:
        rows = asyncio.run(go())
    except VisionError as exc:
        print(f"could not read the shelf: {exc}", file=sys.stderr)
        return 2
    if a.confirm_all:
        from datetime import timezone
        confirmed = {r["product_id"]: r["packs"] for r in rows if r["status"] == "COUNTED"}
        now = datetime.now(timezone.utc).replace(microsecond=0)
        body = stock_count_body(rows, products, confirmed, now, f"shelf-{a.photo.stem}-{now:%Y%m%dT%H%M%S}")
        print(json.dumps(body, indent=2))
        return 0
    print(json.dumps(rows, indent=2) if a.json else render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
