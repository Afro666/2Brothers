"""Turns a proposal into Telegram messages (#1330). Pure functions: no network, no clock.

The rules, for a chef with one hand and two seconds:
- first a summary message, then one message per supplier (a PO), never one per product;
- the first line says the one thing that matters, in bold;
- bold only: the counts and total of a first line, a PO total, a deadline;
- every number is copied from the proposal. Nothing here computes a price or a total.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from html import escape
from zoneinfo import ZoneInfo

HELSINKI = ZoneInfo("Europe/Helsinki")
SHOWN_LINES = 8
# Valio's unit codes, said the way a kitchen says them.
UNITS = {"ST": "pcs", "KI": "case", "KG": "kg", "L": "L", "BAG": "bag", "PCS": "pcs"}
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass
class Message:
    text: str
    buttons: list[list[dict]] = field(default_factory=list)   # Telegram inline keyboard rows

    @property
    def markup(self) -> dict | None:
        return {"inline_keyboard": self.buttons} if self.buttons else None


def money(value) -> str:
    """"1240.1" -> "EUR 1,240.10". A value that is not a number is shown as it came."""
    try:
        return f"EUR {Decimal(str(value)):,.2f}"
    except (InvalidOperation, TypeError):
        return f"EUR {escape(str(value))}"


def quantity(value, unit) -> str:
    try:
        number = Decimal(str(value))
        shown = f"{number.normalize():f}" if number != number.to_integral() else f"{number.to_integral()}"
    except (InvalidOperation, TypeError):
        shown = str(value)
    return f"{shown} {UNITS.get(str(unit).upper(), str(unit))}"


def when(stamp: str | None) -> str | None:
    """An ISO time with an offset -> "Sun 15 Nov 17:00" in the kitchen's time. None stays None."""
    if not stamp:
        return None
    try:
        local = datetime.fromisoformat(stamp).astimezone(HELSINKI)
    except ValueError:
        return None
    return f"{DAYS[local.weekday()]} {local.day} {MONTHS[local.month - 1]} {local:%H:%M}"


def day(iso_date: str | None) -> str:
    try:
        d = datetime.fromisoformat(str(iso_date))
    except ValueError:
        return escape(str(iso_date or ""))
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def blocks_of(proposal: dict) -> list[dict]:
    """The supplier blocks. A proposal stored before blocks existed is one Valio block."""
    blocks = proposal.get("blocks") or []
    if blocks:
        return blocks
    lines = proposal.get("lines") or []
    return [{"supplier_id": "sup-valio", "name": "Valio Aimo", "lines": lines,
             "expected_total": proposal.get("expected_total")}] if lines else []


def earliest_cutoff(lines: list[dict]) -> str | None:
    stamps = [ln["closing_time"] for ln in lines if ln.get("closing_time")]
    return min(stamps, key=lambda s: datetime.fromisoformat(s)) if stamps else None


def _stock_words(lines: list[dict]) -> str | None:
    return "stock not confirmed" if any(ln.get("unknown_stock") for ln in lines) else None


def _deadline(lines: list[dict]) -> str | None:
    if any(ln.get("cutoff_passed") for ln in lines):
        return "the cut-off has passed"
    stamp = when(earliest_cutoff(lines))
    return f"before {stamp}" if stamp else None


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def summary(proposal: dict, approve_url: str | None = None, heard: str | None = None) -> Message:
    """The first message: what, from how many suppliers, the total, then one line per supplier."""
    request = proposal.get("request") or {}
    blocks = blocks_of(proposal)
    out: list[str] = []
    if heard:
        out.append(f"Heard: \"{escape(heard)}\"")
    if proposal.get("status") == "REJECTED" or not blocks:
        reasons = (proposal.get("mandate") or {}).get("reasons") or []
        out.append(f"<b>Nothing can be ordered.</b> {escape(str(reasons[0])) if reasons else ''}".strip())
        return Message("\n".join(out))

    products = sum(len(b.get("lines") or []) for b in blocks)
    head = f"<b>{_plural(products, 'product')} · {_plural(len(blocks), 'supplier')} · {money(proposal.get('expected_total'))}</b>"
    if request.get("requested_date"):
        head += f" for {day(request['requested_date'])}"
    out.append(head)
    for block in blocks:
        lines = block.get("lines") or []
        parts = [f"{escape(str(block.get('name') or block.get('supplier_id')))}: {_plural(len(lines), 'item')}",
                 f"<b>{money(block.get('expected_total'))}</b>"]
        parts += [p for p in (_deadline(lines), _stock_words(lines)) if p]
        out.append(", ".join(parts))
    shortfall = proposal.get("shortfall")
    if shortfall not in (None, "", "0", "0.0", "0.00"):
        out.append(f"{escape(str(shortfall))} {escape(str(proposal.get('measure') or ''))} of the request could not be covered.".replace("  ", " "))
    problems = request.get("problems") or []
    if problems:
        out.append(f"{_plural(len(problems), 'menu entry').replace('entrys', 'entries')} could not be counted.")
    who = {"menu_plan": "From the menu plan.", "parser": "Read by the parser (the model did not answer)."}.get(request.get("made_by"))
    if proposal.get("buyer_model"):
        who = "Proposed by the Buyer agent (Nemotron)."
    if who:
        out.append(who)
    buttons = [[{"text": "Open to approve", "web_app": {"url": approve_url}}]] if approve_url else []
    return Message("\n".join(out), buttons)


ADD_ROWS = 6          # products offered after "Add product": a phone shows about this many buttons


def add_quantity(row: dict, lot=None) -> str | None:
    """The quantity one press adds: the engine's own suggestion, or one lot when it has none.
    None when neither is a number above 0."""
    for value in (row.get("suggested_qty"), lot, 1):
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError):
            continue
        if number > 0:
            return f"{number.normalize():f}"
    return None


def supplier_message(proposal: dict, index: int, names: dict[str, str] | None = None,
                     show_all: bool = False, mode: str = "view", line: int | None = None,
                     addable: list[dict] | None = None) -> Message:
    """One supplier's whole order. `mode`: view, change (pick a line), line (− / + / remove) or
    add (pick a product from `addable`, the gateway's own list, most probable first)."""
    names = names or {}
    block = blocks_of(proposal)[index]
    lines = block.get("lines") or []
    pid = proposal["proposal_id"]
    name_of = lambda ln: names.get(str(ln.get("product_id"))) or f"product {ln.get('product_id')}"   # noqa: E731

    out = [f"<b>{escape(str(block.get('name') or block.get('supplier_id')))} · {_plural(len(lines), 'item')} · {money(block.get('expected_total'))}</b>"]
    second = []
    deadline = _deadline(lines)
    if deadline:
        second.append(f"<b>Approve {deadline}</b>" if deadline.startswith("before") else f"<b>{deadline.capitalize()}</b>")
    stock = _stock_words(lines)
    second.append("stock not confirmed: the order waits for the supplier's answer" if stock else "stock confirmed")
    out.append(" · ".join(second))

    shown = lines if show_all or mode != "view" or len(lines) <= SHOWN_LINES else lines[:SHOWN_LINES]
    width = max((len(quantity(ln.get("quantity"), ln.get("unit"))) for ln in shown), default=0)
    for i, ln in enumerate(shown):
        mark = "▸ " if mode == "line" and i == line else ""
        out.append(f"{mark}<code>{quantity(ln.get('quantity'), ln.get('unit')).ljust(width)}</code>  {escape(name_of(ln))}")
    if len(shown) < len(lines):
        out.append(f"... and {len(lines) - len(shown)} more")

    if mode == "line" and line is not None and 0 <= line < len(lines):
        why = lines[line].get("why")
        if why and "LOT_SIZE_ROUNDED" in (lines[line].get("reason_codes") or []):
            out.append(f"<i>{escape(str(why))}</i>")
        buttons = [[{"text": "−", "callback_data": f"q:{pid}:{index}:{line}:-"},
                    {"text": quantity(lines[line].get("quantity"), lines[line].get("unit")), "callback_data": "noop"},
                    {"text": "+", "callback_data": f"q:{pid}:{index}:{line}:+"}],
                   [{"text": "Remove", "callback_data": f"q:{pid}:{index}:{line}:0"},
                    {"text": "Done", "callback_data": f"v:{pid}:{index}"}]]
    elif mode == "add":
        out.append("<i>Press a product to add it. The quantity is the engine's suggestion; change it after.</i>")
        buttons = [[{"text": f"+ {quantity(row['add_qty'], row.get('unit'))}  {row.get('name') or row['product_id']}"[:60],
                     "callback_data": f"d:{pid}:{index}:{row['product_id']}"}] for row in (addable or [])[:ADD_ROWS]]
        buttons.append([{"text": "Done", "callback_data": f"v:{pid}:{index}"}])
    elif mode == "change":
        buttons = [[{"text": f"{quantity(ln.get('quantity'), ln.get('unit'))}  {name_of(ln)}"[:60],
                     "callback_data": f"l:{pid}:{index}:{i}"}] for i, ln in enumerate(lines)]
        buttons.append([{"text": "Done", "callback_data": f"v:{pid}:{index}"}])
    else:
        row = [{"text": "Change", "callback_data": f"c:{pid}:{index}"},
               {"text": "Add product", "callback_data": f"p:{pid}:{index}"}]
        if len(lines) > SHOWN_LINES and not show_all:
            row.append({"text": "Show all", "callback_data": f"a:{pid}:{index}"})
        buttons = [row]
    return Message("\n".join(out), buttons)


BRIEF_ORDERS = 6      # supplier messages after a brief; more than this is a wall of text


def waiting_suppliers(waiting: list[dict]) -> list[dict]:
    """The waiting orders added up per supplier: items, total, deadline, stock words.
    `total` is None when one of the supplier's totals is not a number: never a part total."""
    found: dict[str, dict] = {}
    for proposal in waiting:
        for block in blocks_of(proposal):
            key = str(block.get("supplier_id") or block.get("name"))
            row = found.setdefault(key, {"name": str(block.get("name") or block.get("supplier_id")),
                                         "lines": [], "total": Decimal(0)})
            row["lines"] += block.get("lines") or []
            try:
                if row["total"] is not None:
                    row["total"] += Decimal(str(block.get("expected_total")))
            except (InvalidOperation, TypeError):
                row["total"] = None
    return list(found.values())


_LONG_ID = re.compile(r"\b([0-9a-f]{8})[0-9a-f]{24}\b")
_ISO_DAY = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def tidy(text) -> str:
    """A line of the gateway's brief, made short for a phone: a 32-character id becomes its
    first 8, and a date like 2026-11-16 becomes "Mon 16 Nov". Nothing else changes."""
    short = _LONG_ID.sub(lambda m: m.group(1), str(text or ""))
    return escape(_ISO_DAY.sub(lambda m: day(m.group(0)), short))


def brief(answer: dict, waiting: list[dict], today: str, approve_url: str | None = None) -> Message:
    """The morning or evening brief: what waits (products, suppliers, cost), what is urgent,
    one line per supplier, then the other things to know. `answer` is the gateway's brief,
    `waiting` the proposals that wait for approval."""
    title = f"{'Morning' if answer.get('when') == 'morning' else 'Evening'} brief · {day(today)}"
    rows = answer.get("lines") or []
    suppliers = waiting_suppliers(waiting)
    if not rows and not suppliers:
        return Message(f"{title}\nNothing urgent. No orders wait.")
    out = [title]
    if suppliers:
        products = sum(len(s["lines"]) for s in suppliers)
        head = f"{_plural(products, 'product')} needed · {_plural(len(suppliers), 'supplier')}"
        if all(s["total"] is not None for s in suppliers):
            head += f" · {money(sum(s['total'] for s in suppliers))}"
        out.append(f"<b>{head}</b>")
    out += [f"<b>{tidy(r.get('text'))}</b>" for r in rows if r.get("urgent")]
    if suppliers:
        out.append("")
        for s in suppliers:
            parts = [f"{escape(s['name'])}: {_plural(len(s['lines']), 'item')}"]
            if s["total"] is not None:
                parts.append(money(s["total"]))
            parts += [p for p in (_deadline(s["lines"]), _stock_words(s["lines"])) if p]
            out.append(", ".join(parts))
    # With the orders shown above, the gateway's own "drafts wait" row would say it twice.
    rest = [r for r in rows if not r.get("urgent") and not (suppliers and r.get("kind") == "WAITING_DRAFTS")]
    if rest:
        out.append("")
        out += [tidy(r.get("text")) for r in rest]
    if answer.get("made_by") in ("model", "mixed"):
        out.append("<i>Wording by the Buyer agent (Nemotron).</i>")
    buttons = [[{"text": "Open to approve", "web_app": {"url": approve_url}}]] if approve_url and suppliers else []
    return Message("\n".join(out), buttons)


def shelf_counts(answer: dict) -> list[dict]:
    """The rows a person may save: only COUNTED ones. Unknown is never a number."""
    return [{"product_id": str(r["product_id"]), "on_hand": str(r["count"]), "unit": r.get("unit")}
            for r in answer.get("rows") or []
            if r.get("row") == "COUNTED" and r.get("product_id") and r.get("count") is not None]


def shelf(answer: dict, saved: bool = False) -> Message:
    """What Nemotron read on a shelf photo. Nothing is stored until the person presses Save."""
    rows = answer.get("rows") or []
    counted = [r for r in rows if r.get("row") == "COUNTED" and r.get("product_id") and r.get("count") is not None]
    by_hand = [r for r in rows if r.get("row") == "PLEASE_COUNT"]
    unknown = [r for r in rows if r.get("row") == "UNMATCHED"]
    if not rows:
        return Message("<b>I see no product on this photo.</b>\nTake it closer, with the labels to the camera.")
    if saved:
        head = f"Saved: {_plural(len(counted), 'count')}"
    else:
        parts = [f"{len(counted)} counted"]
        if by_hand:
            parts.append(f"{len(by_hand)} to count by hand")
        head = "Shelf photo: " + " · ".join(parts)
    out = [f"<b>{head}</b>"]
    width = max((len(quantity(r.get("count"), r.get("unit"))) for r in counted), default=0)
    name_of = lambda r: escape(str(r.get("product_name") or r.get("label") or r.get("product_id")))   # noqa: E731
    out += [f"<code>{quantity(r.get('count'), r.get('unit')).ljust(width)}</code>  {name_of(r)}" for r in counted]
    out += [f"Count by hand: {name_of(r)}" for r in by_hand]
    for r in unknown:
        label = str(r.get("label") or "").strip()
        out.append("One pack with no label I can read." if label.lower() in ("", "unknown", "n/a", "none")
                   else f"Not in this kitchen's products: \"{escape(label[:80])}\"")
    if saved:
        return Message("\n".join(out))
    seconds = answer.get("duration_ms")
    took = f" in {int(seconds) / 1000:.1f} s" if isinstance(seconds, (int, float)) else ""
    out.append(f"<i>Read by Nemotron{took}. " + ("Nothing is saved until you press Save.</i>" if counted
                                                    else "Nothing to save: count these by hand.</i>"))
    buttons = [[{"text": f"Save {_plural(len(counted), 'count')}", "callback_data": "s:save:0"},
                {"text": "Discard", "callback_data": "s:drop:0"}]] if counted else []
    return Message("\n".join(out), buttons)


def refusal(code: str, message: str | None = None) -> str:
    """One plain sentence for an answer that is not a proposal."""
    known = {
        "CANNOT_READ_REQUEST": "I could not read that as an order. Say the product, the amount and the day, for example: 20 L oat drink for Monday.",
        "BUYER_UNAVAILABLE": "The Buyer does not answer now. Try again in a minute.",
        "RATE_LIMITED": "Too many requests in a short time. Try again in a minute.",
        "STOCK_PHOTO_BUSY": "Another photo is being read. Send this one again when that answer is here.",
        "VISION_TIMEOUT": "The photo took too long to read. Send it again.",
        "NOT_AN_IMAGE": "I could not read that as a photo. Send it as a photo, not as a file.",
    }
    return known.get(code) or escape(message or "That did not work. Try again.")
