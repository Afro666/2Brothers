"""Valio's selling agent (#374): before a predicted shortage, offer a kitchen a substitute.

    python -m agent.seller --dry-run                                  # prints, sends nothing
    python -m agent.seller --apply --limit 1 --kitchen demo-kitchen   # sends one offer
    python -m agent.seller --dry-run --no-model                       # the rule picks, not Nemotron

On the server it runs inside the gateway image, next to the gateway's own code (no HTTP,
no token):

    docker compose --env-file .env -f deploy/compose.yaml run --rm -T --no-deps gateway python -m agent.seller --dry-run

Who decides what:
- Code reads the supplier's shortage view (only kitchens that share their forecast) and
  builds the shortlist: at most 5 catalog products of the same category and measure, that
  can arrive for the date with confirmed stock for this kitchen's need, that pass the
  kitchen's allergen rule, and that are not short themselves. Allergen data must be known,
  unless the short product has none either (fresh vegetables): then the offer is marked.
- Nemotron 3.5 Super VL picks one entry of the shortlist and writes the reason. It sees
  catalog fields and the shortage numbers, never a kitchen's name or text. A pick outside
  the shortlist, or no valid answer, means no offer.
- The gateway (gateway/supplier_offers.py) checks the offer again and sets the quantity
  from the kitchen's own forecast. The offer is a suggestion: a person accepts it, and the
  proposal it becomes still needs the normal approval.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta
from decimal import Decimal
import json
import re

SUPPLIER = "sup-valio"
MODEL_NAME = "nemotron-3.5-super-vl"
SHORTLIST = 5
CANDIDATES = 150           # how many products of the category are asked for live availability
UNKNOWN_FROM = 999999      # an available amount from here up is Valio's filler, not a count
DAYS = 7
MAX_PAIRS = 60             # kitchen and product pairs looked at in one run (each costs a search)
MEASURES = ("L", "KG")     # the engine sizes a request in litres or kilograms
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["index", "reason"],
          "properties": {"index": {"type": "integer"}, "reason": {"type": "string"}}}
SYSTEM = ("You work for a food wholesaler. One product is predicted to run short. Pick the one "
          "product from the shortlist that best replaces it for a professional kitchen: the same "
          "kind of product, the closest pack size. Answer with the index of your pick and a reason "
          "of one or two short sentences in plain English for the kitchen's chef. Use only the "
          "facts given. Do not mention prices.")


def short_rows(gw, supplier_id: str, start: date, end: date) -> tuple[list[dict], set[tuple[str, str]]]:
    """SHORT rows in litres or kilograms, nearest date first, and every (product, date) that
    is not OK: such a product is never offered as a substitute for that date."""
    from gateway.supplier_routes import supplier_demand
    rows = supplier_demand(gw.db, gw.valio, supplier_id, start, end)["rows"]
    not_ok = {(row["product_id"], row["date"]) for row in rows if row["risk"] != "OK"}
    short = [row for row in rows if row["risk"] == "SHORT" and row["unit"] in MEASURES]
    short.sort(key=lambda row: (row["date"], -Decimal(row["shortage"])))
    return short, not_ok


def _words(name: str) -> set[str]:
    return set(re.findall(r"[a-z\u00e5\u00e4\u00f6]{3,}", (name or "").lower()))


def _name(row: dict) -> str:
    names = row.get("names") or {}
    return names.get("en") or names.get("fi") or row["product_id"]


def _allergens_ok(policy, row: dict, short_known: bool) -> bool:
    """The kitchen's rule, as the gateway applies it to an offer (gateway/supplier_offers.py):
    known allergen data that passes; or, when the short product has no allergen data either,
    a product without allergen data that declares nothing the kitchen excludes."""
    if policy.allowed(row, substitute=True):
        return True
    if short_known or row.get("allergen_data_known") is True:
        return False
    allergens = row.get("allergens")
    if not isinstance(allergens, dict):
        return False
    levels = [allergens.get(key) for key in ("contains", "may_contain", "undeclared")]
    if any(not isinstance(level, list) for level in levels):
        return False
    return not set(policy.excluded).intersection(v for level in levels for v in level)


def shortlist(gw, row: dict, kitchen_id: str, demand: Decimal, not_ok: set) -> list[dict]:
    """At most SHORTLIST substitutes for this kitchen. Code only.

    The whole catalog category of the short product is read from the store (the text search
    returns 50 hits and ranks by words, so it missed whole categories live). Products named
    like the short one come first (another cucumber before a courgette)."""
    from agent.substitutes import AllergenPolicy
    from gateway.supplier_routes import _per_sales_unit
    from store import recalls
    from store.buyer_context import excluded_allergens
    from store.products import category_products, get_products
    short = next(iter(get_products(gw.db, [row["product_id"]])), None)
    if not short or not short.get("category"):
        return []
    try:        # a misspelt allergen rule fails closed: no offer for this kitchen
        policy = AllergenPolicy(tuple(excluded_allergens(gw.db, kitchen_id) or ()))
    except ValueError:
        return []
    blocked = recalls.blocked_ids(gw.db, kitchen_id)
    short_known = short.get("allergen_data_known") is True
    wanted = _words(_name(short))
    usable = [r for r in category_products(gw.db, short["category"])
              if r["product_id"] != row["product_id"] and r.get("source", "valio") != "own"
              and (r.get("net_content") or {}).get("unit") == row["unit"]
              and r["product_id"] not in blocked and (r["product_id"], row["date"]) not in not_ok
              and _allergens_ok(policy, r, short_known)]
    usable.sort(key=lambda r: (-len(wanted & _words(_name(r))), r["product_id"]))
    usable = usable[:CANDIDATES]
    live: dict[str, dict] = {}
    for at in range(0, len(usable), 50):
        ids = [r["product_id"] for r in usable[at:at + 50]]
        live.update({p["productId"]: p for p in gw.valio.availability(ids, row["date"])["products"]})
    day = date.fromisoformat(row["date"])
    out = []
    for r in usable:
        product = live.get(r["product_id"]) or {}
        lines = product.get("scheduleLines") or []
        per = _per_sales_unit(r)
        if not lines or per is None or product.get("salesBlock") or product.get("cutoff_passed") is True:
            continue
        line = lines[0]
        amount, arrives = line.get("availableAmount"), line.get("availableDate")
        # Valio writes "plenty" as a large filler number (999999, 666666666, 1999999999):
        # that is not a confirmed amount.
        if line.get("salesBlock") or amount is None or amount >= UNKNOWN_FROM or not arrives:
            continue
        if date.fromisoformat(arrives) > day:
            continue
        have = Decimal(str(amount)) * per
        if have < demand:               # confirmed stock must cover this kitchen's need
            continue
        out.append({"product_id": r["product_id"], "name": _name(r),
                    "brand": r.get("brand"), "pack": r.get("net_content"), "lactose_free": r.get("lactose_free"),
                    "allergen_data_known": r.get("allergen_data_known") is True,
                    "available": f"{have.normalize():f}", "unit": row["unit"]})
        if len(out) == SHORTLIST:
            break
    return out


def _messages(row: dict, demand: Decimal, entries: list[dict]) -> list[dict]:
    facts = {"short_product": {"name": row["product_name"], "date": row["date"], "unit": row["unit"],
                               "demand_all_kitchens": row["demand"], "available": row["available"],
                               "shortage": row["shortage"]},
             "this_kitchen_needs": f"{demand.normalize():f}",
             "shortlist": [{"index": i, **{k: e[k] for k in ("name", "brand", "pack", "lactose_free", "available")}}
                           for i, e in enumerate(entries)]}
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)}]


async def model_pick(model, row: dict, demand: Decimal, entries: list[dict]) -> tuple[int, str] | None:
    """Nemotron's pick, checked: an index inside the shortlist and a reason, or None."""
    from gateway.supplier_offers import REASON_MAX, clean_text
    try:
        reply = await model.complete_json(_messages(row, demand, entries), SCHEMA, "substitute_pick",
                                          max_tokens=300)
        data = json.loads(reply.get("content") or "")
    except Exception:           # no answer, a network error, not JSON: no offer
        return None
    if not isinstance(data, dict):
        return None
    index, reason = data.get("index"), data.get("reason")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(entries):
        return None
    if not isinstance(reason, str):
        return None
    reason = clean_text(reason)[:REASON_MAX].strip()
    return (index, reason) if reason else None


def rule_pick(row: dict, entries: list[dict]) -> tuple[int, str]:
    return 0, (f"{entries[0]['name']} is the closest match in our catalog to {row['product_name']} "
               f"and is in stock for {row['date']}. Picked by rule, not by the model.")[:300]


async def run(gw, *, today: date, apply: bool, limit: int = 3, kitchen: str | None = None,
              supplier_id: str = SUPPLIER, days: int = DAYS, model=None) -> list[dict]:
    """One pass over the shortage view, nearest dates first. `model=None`: the rule picks.
    Returns what it did. One offer per kitchen and short product: a later date is tried only
    when the nearer one gave no offer."""
    from gateway.service import GatewayError
    from gateway.supplier_offers import create
    from store import supplier_offers as store
    from store.history import consenting_kitchens
    if kitchen is not None and kitchen not in consenting_kitchens(gw.db, supplier_id):
        return [{"kitchen_id": kitchen, "result": "SHARING_REQUIRED",
                 "note": "this kitchen does not share its forecast with the supplier: it gets no offers"}]
    rows, not_ok = short_rows(gw, supplier_id, today + timedelta(days=1), today + timedelta(days=days))
    done: set[tuple[str, str]] = set()
    report: list[dict] = []
    offers = 0
    for row in rows:
        for part in row["by_kitchen"]:
            kitchen_id = part["kitchen_id"]
            if offers >= limit or len(report) >= MAX_PAIRS:
                return report
            if (kitchen is not None and kitchen_id != kitchen) or (kitchen_id, row["product_id"]) in done:
                continue
            entry = {"kitchen_id": kitchen_id, "date": row["date"], "short_product_id": row["product_id"],
                     "short_product": row["product_name"], "kitchen_needs": part["demand"], "unit": row["unit"]}
            report.append(entry)
            key = f"seller:{kitchen_id}:{row['product_id']}:{row['date']}"
            if store.by_key(gw.db, supplier_id, key) is not None:
                entry["result"] = "ALREADY_OFFERED"
                done.add((kitchen_id, row["product_id"]))
                continue
            demand = Decimal(part["demand"])
            entries = shortlist(gw, row, kitchen_id, demand, not_ok)
            entry["shortlist"] = [f"{e['product_id']} {e['name']}" for e in entries]
            if not entries:
                entry["result"] = "NO_SUBSTITUTE"
                continue
            picked = rule_pick(row, entries) if model is None else await model_pick(model, row, demand, entries)
            if picked is None:
                entry["result"] = "NO_VALID_PICK"       # the model's answer was not usable: no offer
                continue
            choice = entries[picked[0]]
            entry.update(offered_product_id=choice["product_id"], offered_product=choice["name"],
                         reason=picked[1], made_by="rule" if model is None else MODEL_NAME)
            if not apply:
                offers += 1
                done.add((kitchen_id, row["product_id"]))
                entry["result"] = "DRY_RUN"
                continue
            try:
                offer = create(gw, supplier_id, {
                    "kitchen_id": kitchen_id, "product_id": choice["product_id"],
                    "replaces_product_id": row["product_id"], "requested_date": row["date"],
                    "reason": picked[1], "made_by": entry["made_by"], "idempotency_key": key}, "seller-agent")
                entry.update(result=offer["status"], offer_id=offer["offer_id"], quantity=offer["quantity"])
            except GatewayError as exc:
                entry["result"] = exc.code        # refused: not counted, a later date may still be tried
                continue
            offers += 1
            done.add((kitchen_id, row["product_id"]))
    return report


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print what would be offered; send nothing")
    mode.add_argument("--apply", action="store_true", help="send the offers")
    p.add_argument("--limit", type=int, default=3, help="at most this many offers (default 3)")
    p.add_argument("--kitchen", help="only this kitchen")
    p.add_argument("--days", type=int, default=DAYS, help="look this many days ahead (default 7)")
    p.add_argument("--no-model", action="store_true", help="the first shortlist entry, not Nemotron's pick")
    p.add_argument("--today", type=date.fromisoformat, default=None)
    a = p.parse_args(argv)
    if not 1 <= a.limit <= 20 or not 1 <= a.days <= 14:
        raise SystemExit("--limit: 1 to 20, --days: 1 to 14")
    from gateway.service import Gateway
    from gateway.valio_client import ValioClient
    from store.db import get_db
    model = None
    if not a.no_model:
        from agent.model import Nemotron
        try:
            model = Nemotron()
        except ValueError:
            raise SystemExit("VERDA_INFERENCE_KEY is not set here: the model cannot pick. "
                             "Set it, or run with --no-model.") from None
    gw = Gateway(get_db(), ValioClient())

    async def go():
        try:
            return await run(gw, today=a.today or gw.now().date(), apply=a.apply, limit=a.limit,
                             kitchen=a.kitchen, days=a.days, model=model)
        finally:
            if model is not None:
                await model.close()

    report = asyncio.run(go())
    for entry in report:
        print(json.dumps(entry, ensure_ascii=False))
    sent = sum(1 for e in report if e.get("result") == "OPEN")
    would = sum(1 for e in report if e.get("result") == "DRY_RUN")
    print(f"{len(report)} kitchen and product pairs looked at; "
          + (f"{sent} offers sent" if a.apply else f"{would} offers would be sent (dry run, nothing sent)"))


if __name__ == "__main__":
    main()
