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
        "/brief shows what waits and what is urgent. It also comes at 07:00 and 16:00.\n"
        "A photo of a shelf becomes a stock count: you check it, then save it.\n"
        "You approve on the approval card: press \"Open to approve\".")
NOT_LINKED = "This chat is not linked to a kitchen yet. Ask the kitchen's admin for a link."
MAX_VOICE_SECONDS = 30
MAX_PHOTO_BYTES = 4 * 1024 * 1024       # the gateway's limit for a shelf photo
MAX_SHELVES = 50


BRIEF_TIMES = {"morning": "07:00", "evening": "16:00"}      # the kitchen's time
BRIEF_WINDOW = timedelta(hours=2)       # a bot that starts at 15:00 does not send the 07:00 brief


def due_slot(now: datetime, times: dict[str, str]) -> str | None:
    """The brief whose time has come: "morning", "evening" or None."""
    for slot, clock in times.items():
        try:
            hour, minute = (int(part) for part in clock.split(":"))
            start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            continue
        if start <= now < start + BRIEF_WINDOW:
            return slot
    return None


def parse_brief_times(text: str | None) -> dict[str, str]:
    """BOT_BRIEF_TIMES: "07:00,16:00" (morning, evening); "off" sends no timed brief."""
    if text is None or not text.strip():
        return dict(BRIEF_TIMES)
    if text.strip().lower() == "off":
        return {}
    return dict(zip(("morning", "evening"), (part.strip() for part in text.split(","))))


class NotConfigured(Exception):
    pass


class Bot:
    def __init__(self, telegram: Telegram, gateway: Gateway, links: Links, speech: Speech | None = None,
                 site_url: str | None = None, now=lambda: datetime.now(render.HELSINKI),
                 brief_times: dict[str, str] | None = None):
        self.tg, self.gw, self.links, self.speech = telegram, gateway, links, speech
        self.site_url = site_url.rstrip("/") if site_url else None
        self.now = now
        self._products: dict[str, dict] = {}                 # product_id -> {"name", "lot"}
        self._summaries: dict[tuple[int, str], int] = {}     # (chat, proposal) -> summary message id
        self._heard: dict[tuple[int, str], str] = {}
        self._shelves: dict[tuple[int, int], dict] = {}      # (chat, message) -> a shelf read to confirm
        self._chat_types: dict[int, str] = {}                # chat -> "private", "group", "supergroup", ...
        self._lock = threading.Lock()
        self.brief_times = brief_times if brief_times is not None else dict(BRIEF_TIMES)

    # ---- entry -------------------------------------------------------------------------
    def handle(self, update: dict) -> None:
        try:
            if "callback_query" in update:
                self._callback(update["callback_query"])
            elif "message" in update:
                self._message(update["message"])
        except TelegramError as exc:
            print(f"bot: telegram: {exc}", file=sys.stderr, flush=True)
        except Exception as exc:        # one bad update must not stop the bot; never the content
            print(f"bot: update failed: {type(exc).__name__}", file=sys.stderr, flush=True)

    def _remember_type(self, chat_info: dict) -> None:
        if chat_info.get("id") is not None and chat_info.get("type"):
            with self._lock:
                self._chat_types[chat_info["id"]] = chat_info["type"]

    def _markup(self, chat: int, markup: dict | None) -> dict | None:
        """Telegram allows inline `web_app` buttons only in private chats: elsewhere the whole
        send fails. Outside a private chat they become plain `url` buttons. A chat whose type
        is not known yet is private when its id is positive (group ids are negative)."""
        private = self._chat_types.get(chat, "private" if chat > 0 else "group") == "private"
        if private or not markup:
            return markup
        return {"inline_keyboard": [[{"text": b["text"], "url": b["web_app"]["url"]} if "web_app" in b else b
                                     for b in row] for row in markup["inline_keyboard"]]}

    def _message(self, message: dict) -> None:
        self._remember_type(message["chat"])
        chat = message["chat"]["id"]
        text = (message.get("text") or "").strip()
        if text.startswith("/start"):
            return self._start(chat, text, message)
        if not self.links.linked(chat):
            self.tg.send(chat, NOT_LINKED)
            return
        if "voice" in message:
            return self._voice(chat, message["voice"])
        if message.get("photo"):
            return self._photo(chat, message["photo"])
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
        elif text.split(" ")[0] == "/brief":
            self._brief(chat, text.partition(" ")[2].strip().lower())
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

    # ---- a shelf photo -----------------------------------------------------------------
    def _photo(self, chat: int, sizes: list[dict]) -> None:
        """Nemotron reads the shelf; the person saves the count with one press. The read is
        kept in memory only: the gateway route stores nothing, and neither does the bot."""
        fits = [s for s in sizes if int(s.get("file_size") or 0) <= MAX_PHOTO_BYTES]
        if not fits:
            self.tg.send(chat, "That photo is too large. Send a smaller one.")
            return
        best = max(fits, key=lambda s: int(s.get("width") or 0) * int(s.get("height") or 0))
        status = self.tg.send(chat, "One moment: Nemotron is reading the shelf.", silent=True)
        self.tg.typing(chat)
        try:
            answer = self.gw.shelf_photo(self.tg.download(best["file_id"], MAX_PHOTO_BYTES))
        except GatewayError as exc:
            self.tg.edit(chat, status, render.refusal(exc.code, exc.message))
            return
        with self._lock:
            self._shelves[(chat, status)] = answer
            for old in list(self._shelves)[:-MAX_SHELVES]:       # the oldest reads go first
                del self._shelves[old]
        message = render.shelf(answer)
        self.tg.edit(chat, status, message.text, message.markup)

    def _shelf_button(self, query: dict, chat: int, message_id: int, action: str) -> None:
        with self._lock:
            answer = self._shelves.get((chat, message_id))
        if answer is None:
            self.tg.answer(query["id"], "This photo is out of date. Send it again.")
            return
        if action == "drop":
            with self._lock:
                self._shelves.pop((chat, message_id), None)
            self.tg.edit(chat, message_id, "Discarded. Nothing was saved.")
            self.tg.answer(query["id"])
            return
        counts = render.shelf_counts(answer)
        if action != "save" or not counts:
            self.tg.answer(query["id"])
            return
        try:
            # The key is the chat and the message: a second press stores nothing new.
            self.gw.save_counts(counts, self.now().isoformat(timespec="seconds"), f"tg-shelf-{chat}-{message_id}")
        except GatewayError as exc:
            self.tg.answer(query["id"], exc.message[:190])
            return
        with self._lock:
            self._shelves.pop((chat, message_id), None)
        self.tg.edit(chat, message_id, render.shelf(answer, saved=True).text)
        self.tg.answer(query["id"], "Saved.")

    # ---- the brief ---------------------------------------------------------------------
    def _period(self, asked: str = "") -> str:
        return asked if asked in ("morning", "evening") else "morning" if self.now().hour < 12 else "evening"

    def _brief_messages(self, period: str) -> list[render.Message]:
        """The brief, then one message per supplier order that waits (the same order message
        as after a request, so its Change buttons work)."""
        answer = self.gw.brief(period)
        waiting = self.gw.waiting()
        url = f"{self.site_url}/approvals" if self.site_url else None
        messages = [render.brief(answer, waiting, self.now().date().isoformat(), url)]
        orders = [(p, i) for p in waiting for i in range(len(render.blocks_of(p)))]
        for proposal, index in orders[:render.BRIEF_ORDERS]:
            messages.append(render.supplier_message(proposal, index, self._names(proposal)))
        if len(orders) > render.BRIEF_ORDERS:
            more = len(orders) - render.BRIEF_ORDERS
            messages.append(render.Message(f"... and {more} more supplier order{'s' if more != 1 else ''}. "
                                           "Open the approvals to see them."))
        return messages

    def _brief(self, chat: int, asked: str = "") -> None:
        status = self.tg.send(chat, "One moment: I am reading the kitchen's day.", silent=True)
        self.tg.typing(chat)
        try:
            messages = self._brief_messages(self._period(asked))
        except GatewayError as exc:
            self.tg.edit(chat, status, render.refusal(exc.code, exc.message))
            return
        self.tg.edit(chat, status, messages[0].text, self._markup(chat, messages[0].markup))
        for message in messages[1:]:
            self.tg.send(chat, message.text, message.markup, silent=True)

    def tick(self) -> None:
        """Called about twice a minute: sends the 07:00 and the 16:00 brief to every linked chat,
        once per slot. The slot is marked before the send, so a restart or a failure never sends
        it twice; a missed brief is still there with /brief."""
        now = self.now()
        slot = due_slot(now, self.brief_times)
        if slot is None or not self.links.chats() or not self.links.mark_sent(f"{now.date().isoformat()} {slot}"):
            return
        try:
            messages = self._brief_messages(slot)
        except GatewayError as exc:
            print(f"bot: the {slot} brief was not sent: {exc.code}", file=sys.stderr, flush=True)
            return
        quiet = len(messages) == 1 and "<b>" not in messages[0].text      # nothing urgent: no sound
        for chat in self.links.chats():
            try:
                self.tg.send(chat, messages[0].text, self._markup(chat, messages[0].markup), silent=quiet)
                for message in messages[1:]:
                    self.tg.send(chat, message.text, message.markup, silent=True)
            except TelegramError as exc:
                print(f"bot: telegram: {exc}", file=sys.stderr, flush=True)

    def _show_summary(self, chat: int, proposal: dict) -> None:
        pid = proposal.get("proposal_id")
        message_id = self._summaries.get((chat, pid))
        if message_id is None:
            return          # after a restart the summary is not known: the PO message is still right
        url = f"{self.site_url}/approvals?proposal={pid}" if self.site_url and pid else None
        message = render.summary(proposal, url, self._heard.get((chat, pid)))
        self.tg.edit(chat, message_id, message.text, self._markup(chat, message.markup))

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
        self._remember_type(message.get("chat") or {})
        chat, message_id = (message.get("chat") or {}).get("id"), message.get("message_id")
        parts = str(query.get("data") or "").split(":")
        if chat is None or not self.links.linked(chat) or parts[0] == "noop" or len(parts) < 3:
            self.tg.answer(query["id"])
            return
        if parts[0] == "s":
            return self._shelf_button(query, chat, message_id, parts[1])
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
    return Bot(Telegram(token), gateway, Links(), speech, env.get("BOT_SITE_URL"),
               brief_times=parse_brief_times(env.get("BOT_BRIEF_TIMES")))


def run(bot: Bot, stop: threading.Event | None = None) -> None:
    """Long polling: Telegram needs no public address. Each update runs on a worker, so a
    request that waits for the Buyer does not hold up another chat."""
    stop = stop or threading.Event()
    offset = None

    def clock() -> None:
        while not stop.wait(30):
            try:
                bot.tick()
            except Exception as exc:        # the timer must outlive one bad brief; never the content
                print(f"bot: brief timer: {type(exc).__name__}", file=sys.stderr, flush=True)

    threading.Thread(target=clock, name="brief-timer", daemon=True).start()
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
