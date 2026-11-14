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


def supplier_message(proposal: dict, index: int, names: dict[str, str] | None = None,
                     show_all: bool = False, mode: str = "view", line: int | None = None) -> Message:
    """One supplier's whole order. `mode`: view, change (pick a line) or line (− / + / remove)."""
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
    elif mode == "change":
        buttons = [[{"text": f"{quantity(ln.get('quantity'), ln.get('unit'))}  {name_of(ln)}"[:60],
                     "callback_data": f"l:{pid}:{index}:{i}"}] for i, ln in enumerate(lines)]
        buttons.append([{"text": "Done", "callback_data": f"v:{pid}:{index}"}])
    else:
        row = [{"text": "Change", "callback_data": f"c:{pid}:{index}"}]
        if len(lines) > SHOWN_LINES and not show_all:
            row.append({"text": "Show all", "callback_data": f"a:{pid}:{index}"})
        buttons = [row]
    return Message("\n".join(out), buttons)


def refusal(code: str, message: str | None = None) -> str:
    """One plain sentence for an answer that is not a proposal."""
    known = {
        "CANNOT_READ_REQUEST": "I could not read that as an order. Say the product, the amount and the day, for example: 20 L oat drink for Monday.",
        "BUYER_UNAVAILABLE": "The Buyer does not answer now. Try again in a minute.",
        "RATE_LIMITED": "Too many requests in a short time. Try again in a minute.",
    }
    return known.get(code) or escape(message or "That did not work. Try again.")
