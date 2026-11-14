"""The Telegram bot of one kitchen (#1330): ask, see the order per supplier, change it.

A chef says or types what the kitchen needs. The gateway (and its Buyer, Nemotron) makes the
proposal; this bot only shows it and passes changes on. Approval is not here: the summary
message opens our own approval card, where a person approves the exact total.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from bot import render
from bot.clients import Gateway, GatewayError, Speech, SpeechError, Telegram, TelegramError
from bot.links import Links

HELP = ("Say or type what the kitchen needs, for example: <b>20 L oat drink for Monday</b>.\n"
        "/week makes the order for the menu plan: 7 days from the next working day.\n"
        "You approve on the approval card: press \"Open to approve\".")
NOT_LINKED = "This chat is not linked to a kitchen yet. Ask the kitchen's admin for a link."
MAX_VOICE_SECONDS = 30


class NotConfigured(Exception):
    pass


class Bot:
    def __init__(self, telegram: Telegram, gateway: Gateway, links: Links, speech: Speech | None = None,
                 site_url: str | None = None, now=lambda: datetime.now(render.HELSINKI)):
        self.tg, self.gw, self.links, self.speech = telegram, gateway, links, speech
        self.site_url = site_url.rstrip("/") if site_url else None
        self.now = now
        self._products: dict[str, dict] = {}                 # product_id -> {"name", "lot"}
        self._summaries: dict[tuple[int, str], int] = {}     # (chat, proposal) -> summary message id
        self._heard: dict[tuple[int, str], str] = {}
        self._lock = threading.Lock()
        self._chat_locks: dict[int, threading.Lock] = {}     # one update at a time per chat

    # ---- entry -------------------------------------------------------------------------
    def handle(self, update: dict) -> None:
        # Updates from one chat run in order (two fast "+" taps are two steps); other chats
        # are not blocked.
        with self._chat_lock(update):
            self._handle(update)

    def _chat_lock(self, update: dict) -> threading.Lock:
        message = (update.get("callback_query") or {}).get("message") or update.get("message") or {}
        chat = (message.get("chat") or {}).get("id")
        with self._lock:
            return self._chat_locks.setdefault(chat, threading.Lock())

    def _handle(self, update: dict) -> None:
        try:
            if "callback_query" in update:
                self._callback(update["callback_query"])
            elif "message" in update:
                self._message(update["message"])
        except TelegramError as exc:
            print(f"bot: telegram: {exc}", file=sys.stderr, flush=True)
        except Exception as exc:        # one bad update must not stop the bot; never the content
            print(f"bot: update failed: {type(exc).__name__}", file=sys.stderr, flush=True)

    def _message(self, message: dict) -> None:
        chat = message["chat"]["id"]
        text = (message.get("text") or "").strip()
        if text.startswith("/start"):
            return self._start(chat, text, message)
        if not self.links.linked(chat):
            self.tg.send(chat, NOT_LINKED)
            return
        if "voice" in message:
            return self._voice(chat, message["voice"])
        if text in ("/help", "/start"):
            self.tg.send(chat, HELP)
        elif text == "/week":
            # The order arrives on the first working day from tomorrow and covers the 7 days from
            # it. The delivery day is sent with the window, as the site's Planner does: without
            # it the gateway quotes the window's first day, and a Sunday refuses every line.
            first = (self.now() + timedelta(days=1)).date()
            while first.weekday() >= 5:
                first += timedelta(days=1)
            self._order(chat, lambda: self.gw.plan(first.isoformat(), (first + timedelta(days=6)).isoformat(),
                                                   first.isoformat()),
                        f"One moment: I am adding up what the menu plan needs from {render.day(first.isoformat())}.")
        elif text.startswith("/"):
            self.tg.send(chat, HELP)
        elif text:
            self._ask(chat, text)

    def _start(self, chat: int, text: str, message: dict) -> None:
        code = text.partition(" ")[2].strip()
        if self.links.linked(chat):
            self.tg.send(chat, "This chat is linked.\n" + HELP)
        elif code and self.links.redeem(code, chat, str((message.get("from") or {}).get("first_name") or "")):
            self.tg.send(chat, "<b>Linked to your kitchen.</b>\n" + HELP)
        else:
            self.tg.send(chat, NOT_LINKED)

    # ---- a request ---------------------------------------------------------------------
    def _voice(self, chat: int, voice: dict) -> None:
        if self.speech is None:
            self.tg.send(chat, "I cannot listen here yet. Type the request instead.")
            return
        if int(voice.get("duration") or 0) > MAX_VOICE_SECONDS:
            self.tg.send(chat, f"That message is longer than {MAX_VOICE_SECONDS} seconds. Send a shorter one.")
            return
        self.tg.typing(chat)
        try:
            heard = self.speech.text(self.tg.download(voice["file_id"]))
        except SpeechError as exc:
            self.tg.send(chat, render.escape(exc.message))
            return
        if not heard:
            self.tg.send(chat, "I did not catch that. Say it again or type it.")
            return
        self._ask(chat, heard, heard=heard)

    def _ask(self, chat: int, text: str, heard: str | None = None) -> None:
        tomorrow = (self.now() + timedelta(days=1)).date().isoformat()
        wait = f"Heard: \"{render.escape(heard)}\"\nOne moment: the Buyer is working on it." if heard \
            else "One moment: the Buyer is working on it."
        self._order(chat, lambda: self.gw.ask(text, tomorrow), wait, heard)

    def _order(self, chat: int, make, wait_text: str, heard: str | None = None) -> None:
        """Show that work started, then turn that same message into the summary."""
        status = self.tg.send(chat, wait_text, silent=True)
        self.tg.typing(chat)
        try:
            proposal = make()
        except GatewayError as exc:
            prefix = f"Heard: \"{render.escape(heard)}\"\n" if heard else ""
            self.tg.edit(chat, status, prefix + render.refusal(exc.code, exc.message))
            return
        pid = proposal.get("proposal_id")
        if pid:
            with self._lock:
                self._summaries[(chat, pid)] = status
                if heard:
                    self._heard[(chat, pid)] = heard
        self._show_summary(chat, proposal)
        if proposal.get("status") == "REJECTED":
            return
        names = self._names(proposal)
        for index in range(len(render.blocks_of(proposal))):
            message = render.supplier_message(proposal, index, names)
            self.tg.send(chat, message.text, message.markup, silent=True)

    def _show_summary(self, chat: int, proposal: dict) -> None:
        pid = proposal.get("proposal_id")
        message_id = self._summaries.get((chat, pid))
        if message_id is None:
            return          # after a restart the summary is not known: the PO message is still right
        url = f"{self.site_url}/approvals?proposal={pid}" if self.site_url and pid else None
        message = render.summary(proposal, url, self._heard.get((chat, pid)))
        self.tg.edit(chat, message_id, message.text, message.markup)

    def _names(self, proposal: dict) -> dict[str, str]:
        ids = [str(ln["product_id"]) for b in render.blocks_of(proposal) for ln in b.get("lines") or []]
        missing = [i for i in ids if i not in self._products]
        if missing:
            found = self.gw.products(missing)
            with self._lock:
                self._products.update(found)
        return {i: self._products[i]["name"] for i in ids if (self._products.get(i) or {}).get("name")}

    # ---- buttons -----------------------------------------------------------------------
    def _callback(self, query: dict) -> None:
        message = query.get("message") or {}
        chat, message_id = (message.get("chat") or {}).get("id"), message.get("message_id")
        parts = str(query.get("data") or "").split(":")
        if chat is None or not self.links.linked(chat) or parts[0] == "noop" or len(parts) < 3:
            self.tg.answer(query["id"])
            return
        action, pid = parts[0], parts[1]
        try:
            index = int(parts[2])
            line = int(parts[3]) if len(parts) > 3 else None
            proposal = self.gw.proposal(pid)
            blocks = render.blocks_of(proposal)
            if not 0 <= index < len(blocks):
                raise GatewayError(409, "CHANGED", "This order has changed. Ask again to see it.")
            notice = None
            mode, show_all = "view", False
            if action == "c":
                mode = "change"
            elif action == "a":
                show_all = True
            elif action == "l":
                mode = "line"
            elif action == "q":
                proposal, mode, notice = self._set_quantity(proposal, index, line, parts[4])
                self._show_summary(chat, proposal)
                blocks = render.blocks_of(proposal)
                if not 0 <= index < len(blocks):          # the supplier's last line was removed
                    self.tg.edit(chat, message_id, "Removed from the order.")
                    self.tg.answer(query["id"], notice)
                    return
            lines = blocks[index].get("lines") or []
            if mode == "line" and (line is None or not 0 <= line < len(lines)):
                mode = "change"
            shown = render.supplier_message(proposal, index, self._names(proposal), show_all, mode, line)
            self.tg.edit(chat, message_id, shown.text, shown.markup)
            self.tg.answer(query["id"], notice)
        except (GatewayError, ValueError, IndexError) as exc:
            text = exc.message if isinstance(exc, GatewayError) else "That button is out of date. Ask again to see the order."
            self.tg.answer(query["id"], text[:190])

    def _set_quantity(self, proposal: dict, index: int, line: int | None, how: str):
        """One step up or down (the product's lot size), or 0 to remove. The gateway does the
        rounding, the stock check and the new total; the answer is the new proposal."""
        lines = render.blocks_of(proposal)[index].get("lines") or []
        if line is None or not 0 <= line < len(lines):
            raise ValueError("line")
        target = lines[line]
        product_id = str(target["product_id"])
        self._names(proposal)
        try:
            step = Decimal(str((self._products.get(product_id) or {}).get("lot") or 1))
            current = Decimal(str(target["quantity"]))
        except InvalidOperation:
            step, current = Decimal(1), Decimal(0)
        if step <= 0:
            step = Decimal(1)
        new = Decimal(0) if how == "0" else current + step if how == "+" else current - step
        if new < 0:
            new = Decimal(0)
        changed = self.gw.change(proposal["proposal_id"], product_id, f"{new.normalize():f}")
        after = next((ln for b in render.blocks_of(changed) for ln in b.get("lines") or []
                      if str(ln.get("product_id")) == product_id), None)
        if after is None:
            return changed, "change", "Removed."
        notice = None
        if how == "+" and Decimal(str(after["quantity"])) < new:
            notice = "No more confirmed stock: the quantity was cut to what the supplier has."
        return changed, "line", notice


# ---- running ---------------------------------------------------------------------------
def build() -> Bot:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    env = os.environ
    token = env.get("TELEGRAM_BOT") or env.get("TELEGRAM_BOT_TOKEN")
    missing = [name for name, value in (("TELEGRAM_BOT", token), ("BOT_GATEWAY_URL", env.get("BOT_GATEWAY_URL")),
                                        ("BOT_KITCHEN_TOKEN", env.get("BOT_KITCHEN_TOKEN"))) if not value]
    if missing:
        raise NotConfigured(f"bot: not started: set {', '.join(missing)} (the key names are in .env.example)")
    gateway = Gateway(env["BOT_GATEWAY_URL"], env["BOT_KITCHEN_TOKEN"], env.get("BOT_KITCHEN_ID", "demo-kitchen"))
    speech = Speech(env["BOT_STT_URL"]) if env.get("BOT_STT_URL") else None
    return Bot(Telegram(token), gateway, Links(), speech, env.get("BOT_SITE_URL"))


def run(bot: Bot, stop: threading.Event | None = None) -> None:
    """Long polling: Telegram needs no public address. Each update runs on a worker, so a
    request that waits for the Buyer does not hold up another chat."""
    stop = stop or threading.Event()
    offset = None
    with ThreadPoolExecutor(max_workers=4) as pool:
        while not stop.is_set():
            try:
                updates = bot.tg.updates(offset)
            except TelegramError as exc:
                print(f"bot: telegram: {exc}", file=sys.stderr, flush=True)
                time.sleep(3)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                pool.submit(bot.handle, update)


def main() -> int:
    try:
        bot = build()
    except NotConfigured as exc:
        # Stay up and idle: a container that exits would be started again and again.
        print(exc, flush=True)
        threading.Event().wait()
        return 0
    me = bot.tg.call("getMe")
    print(f"bot: @{me.get('username')} is running for kitchen {bot.gw.kitchen_id}", flush=True)
    run(bot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
