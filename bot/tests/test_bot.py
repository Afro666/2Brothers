"""The bot with a fake Telegram and a fake gateway: no network, no token."""
from datetime import datetime

import pytest

from bot import render
from bot.app import NOT_LINKED, Bot, due_slot, parse_brief_times
from bot.clients import GatewayError, SpeechError, TelegramError
from bot.links import Links

PID = "0bfc95fb26a047cc876f7a2f034c9762"


def line(product_id, quantity, unit="ST", total="10.00", unknown=False, closing="2026-11-15T17:00:00+02:00", **more):
    return {"product_id": product_id, "quantity": quantity, "unit": unit, "total": total, "unknown_stock": unknown,
            "cutoff_passed": False, "closing_time": closing, "why": "", "reason_codes": [], **more}


def proposal(blocks=None, status="READY", total="2052.50", **more):
    blocks = blocks if blocks is not None else [
        {"supplier_id": "sup-valio", "name": "Valio Aimo", "expected_total": "1240.10",
         "lines": [line("463380", "698", "L"), line("469549", "40", "KG")]},
        {"supplier_id": "sup-bakery", "name": "Corner Bakery <demo>", "expected_total": "812.40",
         "lines": [line("own-1", "40", "ST", unknown=True, closing=None)]},
    ]
    return {"proposal_id": PID, "status": status, "expected_total": total, "blocks": blocks,
            "lines": [ln for b in blocks for ln in b["lines"]],
            "request": {"requested_date": "2026-11-16", "made_by": "menu_plan"}, **more}


class FakeTelegram:
    def __init__(self):
        self.sent, self.edits, self.answers, self.next_id = [], [], [], 100

    def send(self, chat_id, text, markup=None, silent=False):
        self.next_id += 1
        self.sent.append({"chat": chat_id, "id": self.next_id, "text": text, "markup": markup})
        return self.next_id

    def edit(self, chat_id, message_id, text, markup=None):
        self.edits.append({"chat": chat_id, "id": message_id, "text": text, "markup": markup})

    def answer(self, callback_id, text=None):
        self.answers.append(text)

    def typing(self, chat_id):
        pass

    def download(self, file_id, limit=0):
        return b"OggS"


class FakeGateway:
    kitchen_id = "test-kitchen"

    def __init__(self, current=None, error=None):
        self.current, self.error, self.calls = current or proposal(), error, []
        self.brief_answer, self.waiting_list = None, None
        self.addable_rows = [
            {"rank": 1, "product_id": "469549b", "name": "Butter 500 g", "suggested_qty": "12", "unit": "ST",
             "unit_price": "3.85", "addable": True},
            {"rank": 2, "product_id": "463380b", "name": "Cream <1 L>", "suggested_qty": None, "unit": "ST",
             "unit_price": "2.10", "addable": True}]
        self.shelf_answer = {"model": "nemotron-3.5-super-vl", "duration_ms": 4210, "saved": False, "rows": [
            {"row": "COUNTED", "product_id": "463335", "product_name": "Valio Eila 3 % milk drink 1 l",
             "label": "Valio Eila 3% 1L", "confidence": "high", "packs": 6, "pack_size": "1", "count": "6", "unit": "L"},
            {"row": "COUNTED", "product_id": "400100", "product_name": "Eggs M", "label": "Eggs",
             "confidence": "medium", "packs": 12, "pack_size": "1", "count": "12", "unit": "PCS"},
            {"row": "PLEASE_COUNT", "product_id": "463038", "product_name": "Valio Eila 10 L novobox",
             "label": "Valio Eila 10 L novobox", "confidence": "low", "packs": None, "pack_size": "10",
             "count": None, "unit": "L"},
            {"row": "UNMATCHED", "product_id": None, "product_name": None, "label": "Arla <b>L</b> m",
             "confidence": "low", "packs": None, "pack_size": None, "count": None, "unit": None}]}

    def _answer(self, *call):
        self.calls.append(call)
        if self.error:
            raise self.error
        return self.current

    def ask(self, text, requested_date):
        return self._answer("ask", text, requested_date)

    def plan(self, first, last, delivery):
        return self._answer("plan", first, last, delivery)

    def proposal(self, proposal_id):
        return self.current

    def brief(self, when, lang="en"):
        self.calls.append(("brief", when))
        if self.error:
            raise self.error
        return self.brief_answer if self.brief_answer is not None else {
            "when": when, "lang": lang, "made_by": "model", "nothing_urgent": False, "lines": [
                {"text": "Active recall for Kulta Katriina coffee: 3.253 KG in stock.", "kind": "RECALL",
                 "ref_id": "r1", "urgent": True},
                {"text": "Open supplier offer from Valio Aimo <b>for</b> 10.48 KG potato.", "kind": "SUPPLIER_OFFER",
                 "ref_id": "o1", "urgent": False},
                {"text": "2 drafts wait.", "kind": "WAITING_DRAFTS", "ref_id": "w1", "urgent": False}]}

    def shelf_photo(self, image):
        self.calls.append(("shelf_photo", len(image)))
        if self.error:
            raise self.error
        return self.shelf_answer

    def save_counts(self, counts, counted_at, key):
        self.calls.append(("save_counts", counts, counted_at, key))
        if self.error:
            raise self.error
        return {"stock_count_id": "c1", "stored": len(counts)}

    def addable(self, proposal_id):
        self.calls.append(("addable", proposal_id))
        if self.error:
            raise self.error
        return self.addable_rows

    def add(self, proposal_id, product_id, quantity):
        self.calls.append(("add", product_id, quantity))
        if self.error:
            raise self.error
        self.current["blocks"][0]["lines"].append(line(product_id, quantity))
        self.current["expected_total"] = "2098.70"
        return self.current

    def waiting(self):
        return self.waiting_list if self.waiting_list is not None else [self.current]

    def change(self, proposal_id, product_id, quantity):
        self.calls.append(("change", product_id, quantity))
        if self.error:
            raise self.error
        for block in self.current["blocks"]:
            for ln in block["lines"]:
                if ln["product_id"] == product_id:
                    ln["quantity"] = quantity
            block["lines"] = [ln for ln in block["lines"] if ln["quantity"] != "0"]
        self.current["blocks"] = [b for b in self.current["blocks"] if b["lines"]]
        self.current["expected_total"] = "2100.00"
        return self.current

    def products(self, ids, lang="en"):
        known = {"463380": {"name": "Lactose-free milk 1 L", "lot": 6}, "469549": {"name": "Butter 500 g", "lot": None},
                 "463380b": {"name": "Cream <1 L>", "lot": 6}}
        return {i: known[i] for i in ids if i in known}


class FakeSpeech:
    def __init__(self, text="twenty litres of oat drink for Monday", error=None):
        self._text, self._error = text, error

    def text(self, audio):
        if self._error:
            raise self._error
        return self._text


@pytest.fixture
def bot(tmp_path):
    links = Links(tmp_path)
    assert links.redeem(links.new_code(), 7, "Aron")
    made = Bot(FakeTelegram(), FakeGateway(), links, FakeSpeech(), "https://site.example/",
               now=lambda: datetime(2026, 11, 14, 16, 0, tzinfo=render.HELSINKI))
    return made


def say(bot, text, chat=7):
    bot.handle({"message": {"chat": {"id": chat}, "text": text, "from": {"first_name": "Aron"}}})


def press(bot, data, message_id=555, chat=7):
    bot.handle({"callback_query": {"id": "cb", "data": data, "message": {"chat": {"id": chat}, "message_id": message_id}}})


# ---- linking -----------------------------------------------------------------------------
def test_an_unlinked_chat_gets_one_line_and_no_gateway_call(bot):
    say(bot, "20 L oat drink", chat=99)
    assert [m["text"] for m in bot.tg.sent] == [NOT_LINKED]
    assert bot.gw.calls == []


def test_a_code_links_a_chat_once(tmp_path):
    links = Links(tmp_path)
    code = links.new_code()
    made = Bot(FakeTelegram(), FakeGateway(), links)
    say(made, f"/start {code}", chat=5)
    assert "Linked to your kitchen" in made.tg.sent[0]["text"]
    say(made, f"/start {code}", chat=6)
    assert made.tg.sent[-1]["text"] == NOT_LINKED
    assert links.chats() == [5]


def test_an_old_code_does_not_link(tmp_path):
    clock = [1000.0]
    links = Links(tmp_path, clock=lambda: clock[0])
    code = links.new_code()
    clock[0] += 31 * 60
    assert links.redeem(code, 5, "x") is False


# ---- a request ---------------------------------------------------------------------------
def test_a_request_gives_a_summary_and_one_message_per_supplier(bot):
    say(bot, "what the menu needs")
    assert bot.gw.calls == [("ask", "what the menu needs", "2026-11-15")]
    assert len(bot.tg.sent) == 3                      # the status message, then one per supplier
    summary = bot.tg.edits[0]
    assert summary["id"] == bot.tg.sent[0]["id"]       # the status message became the summary
    first = summary["text"].splitlines()[0]
    assert first == "<b>3 products · 2 suppliers · EUR 2,052.50</b> for Mon 16 Nov"
    assert "Valio Aimo: 2 items, <b>EUR 1,240.10</b>, before Sun 15 Nov 17:00" in summary["text"]
    assert "Corner Bakery &lt;demo&gt;: 1 item, <b>EUR 812.40</b>, stock not confirmed" in summary["text"]
    assert summary["markup"]["inline_keyboard"][0][0]["web_app"]["url"] == f"https://site.example/approvals?proposal={PID}"
    valio, bakery = bot.tg.sent[1]["text"], bot.tg.sent[2]["text"]
    assert valio.splitlines()[0] == "<b>Valio Aimo · 2 items · EUR 1,240.10</b>"
    assert "<b>Approve before Sun 15 Nov 17:00</b> · stock confirmed" in valio
    assert "Lactose-free milk 1 L" in valio and "463380" not in valio
    assert "stock not confirmed: the order waits for the supplier's answer" in bakery
    assert "product own-1" in bakery                   # no name known: said so, never invented


def test_week_starts_on_the_next_working_day_and_names_it_as_the_delivery_day(bot):
    say(bot, "/week")                # the fixture's "now" is Saturday 14 Nov: Sunday is skipped
    assert bot.gw.calls == [("plan", "2026-11-16", "2026-11-22", "2026-11-16")]
    assert "from Mon 16 Nov" in bot.tg.sent[0]["text"]


def test_week_on_a_weekday_starts_tomorrow(bot):
    bot.now = lambda: datetime(2026, 11, 17, 9, 0, tzinfo=render.HELSINKI)      # a Tuesday
    say(bot, "/week")
    assert bot.gw.calls == [("plan", "2026-11-18", "2026-11-24", "2026-11-18")]


def test_a_refused_request_is_one_sentence_in_the_status_message(bot):
    bot.gw.error = GatewayError(422, "CANNOT_READ_REQUEST", "one product per request")
    say(bot, "cream and cheese")
    assert len(bot.tg.sent) == 1
    assert bot.tg.edits[0]["text"].startswith("I could not read that as an order.")


def test_an_unexpected_failure_turns_the_status_message_into_a_short_failure(bot):
    bot.gw.error = KeyError("blocks")
    say(bot, "20 l oat drink")
    assert len(bot.tg.sent) == 1
    assert bot.tg.edits == [{"chat": 7, "id": bot.tg.sent[0]["id"], "text": "Something went wrong. Ask again.",
                             "markup": None}]


def test_a_rejected_proposal_shows_the_reason_and_no_supplier_message(bot):
    bot.gw.current = proposal(blocks=[], status="REJECTED",
                              mandate={"reasons": ["This kitchen excludes peanuts, so \"peanut butter\" cannot be ordered."]})
    say(bot, "15 kg peanut butter")
    assert len(bot.tg.sent) == 1
    assert "<b>Nothing can be ordered.</b> This kitchen excludes peanuts" in bot.tg.edits[0]["text"]
    assert bot.tg.edits[0]["markup"] is None


def test_text_from_a_supplier_or_a_person_is_escaped():
    text = render.summary(proposal(), heard="<b>50</b> kg").text
    assert 'Heard: "&lt;b&gt;50&lt;/b&gt; kg"' in text
    assert "Corner Bakery &lt;demo&gt;" in text


# ---- voice -------------------------------------------------------------------------------
def test_a_voice_message_shows_what_was_heard_first(bot):
    bot.handle({"message": {"chat": {"id": 7}, "voice": {"file_id": "f", "duration": 6}}})
    assert bot.gw.calls[0][:2] == ("ask", "twenty litres of oat drink for Monday")
    assert bot.tg.sent[0]["text"].startswith('Heard: "twenty litres of oat drink for Monday"')
    assert bot.tg.edits[0]["text"].startswith('Heard: "twenty litres of oat drink for Monday"')


def test_silence_asks_again_and_makes_no_request(bot):
    bot.speech = FakeSpeech(text="")
    bot.handle({"message": {"chat": {"id": 7}, "voice": {"file_id": "f", "duration": 3}}})
    assert bot.gw.calls == []
    assert bot.tg.sent[0]["text"] == "I did not catch that. Say it again or type it."


def test_a_long_voice_message_is_not_downloaded(bot):
    bot.handle({"message": {"chat": {"id": 7}, "voice": {"file_id": "f", "duration": 45}}})
    assert bot.gw.calls == []
    assert "longer than 30 seconds" in bot.tg.sent[0]["text"]


def test_no_speech_service_says_to_type(bot):
    bot.speech = None
    bot.handle({"message": {"chat": {"id": 7}, "voice": {"file_id": "f", "duration": 3}}})
    assert bot.tg.sent[0]["text"] == "I cannot listen here yet. Type the request instead."


def test_a_speech_error_is_said_plainly(bot):
    bot.speech = FakeSpeech(error=SpeechError("STT_UNAVAILABLE", "I cannot listen right now. Type the request instead."))
    bot.handle({"message": {"chat": {"id": 7}, "voice": {"file_id": "f", "duration": 3}}})
    assert bot.tg.sent[0]["text"] == "I cannot listen right now. Type the request instead."


# ---- buttons -----------------------------------------------------------------------------
def test_change_turns_the_lines_into_buttons_in_the_same_message(bot):
    press(bot, f"c:{PID}:0")
    edit = bot.tg.edits[-1]
    assert edit["id"] == 555
    rows = edit["markup"]["inline_keyboard"]
    assert rows[0][0] == {"text": "698 L  Lactose-free milk 1 L", "callback_data": f"l:{PID}:0:0"}
    assert rows[-1][0]["text"] == "Done"


def test_plus_moves_one_lot_and_updates_the_po_and_the_summary(bot):
    say(bot, "milk")
    summary_id = bot.tg.sent[0]["id"]
    press(bot, f"q:{PID}:0:0:+")
    assert ("change", "463380", "704") in bot.gw.calls          # 698 + the lot size of 6
    assert any(e["id"] == summary_id and "EUR 2,100.00" in e["text"] for e in bot.tg.edits)
    assert bot.tg.edits[-1]["id"] == 555 and "704 L" in bot.tg.edits[-1]["text"]


def test_minus_without_a_lot_size_moves_one_unit(bot):
    press(bot, f"q:{PID}:0:1:-")
    assert ("change", "469549", "39") in bot.gw.calls


def test_remove_takes_the_line_off_and_the_last_line_takes_the_supplier_off(bot):
    press(bot, f"q:{PID}:1:0:0")
    assert ("change", "own-1", "0") in bot.gw.calls
    assert bot.tg.edits[-1]["text"] == "Removed from the order."


def test_a_refused_change_is_told_on_the_button_and_the_message_stays(bot):
    bot.gw.error = GatewayError(409, "NOT_READY", "This proposal is already approved.")
    press(bot, f"q:{PID}:0:0:+")
    assert bot.tg.answers == ["This proposal is already approved."]
    assert bot.tg.edits == []


def test_a_button_from_an_unlinked_chat_does_nothing(bot):
    press(bot, f"q:{PID}:0:0:+", chat=99)
    assert bot.gw.calls == [] and bot.tg.edits == []


def test_an_out_of_date_button_does_not_crash(bot):
    press(bot, f"q:{PID}:5:0:+")
    press(bot, "garbage")
    assert bot.gw.calls == []


# ---- layout ------------------------------------------------------------------------------
def test_a_long_order_shows_eight_lines_and_show_all_shows_the_rest():
    many = proposal(blocks=[{"supplier_id": "sup-valio", "name": "Valio Aimo", "expected_total": "99.00",
                             "lines": [line(str(i), "1") for i in range(11)]}])
    short = render.supplier_message(many, 0)
    assert "... and 3 more" in short.text
    assert [b["text"] for b in short.buttons[0]] == ["Change", "Add product", "Show all"]
    full = render.supplier_message(many, 0, show_all=True)
    assert "more" not in full.text and full.text.count("product ") == 11


def test_only_first_lines_totals_and_deadlines_are_bold():
    text = render.supplier_message(proposal(), 0, {"463380": "Milk"}).text
    assert text.count("<b>") == 2                         # the first line and the deadline
    assert "<b>Milk" not in text


def test_a_passed_cut_off_is_said():
    late = proposal(blocks=[{"supplier_id": "sup-valio", "name": "Valio Aimo", "expected_total": "9.00",
                             "lines": [line("1", "1", cutoff_passed=True)]}])
    assert "<b>The cut-off has passed</b>" in render.supplier_message(late, 0).text
    assert "the cut-off has passed" in render.summary(late).text


def test_money_and_quantity_formats():
    assert render.money("1240.1") == "EUR 1,240.10"
    assert render.quantity("3", "BAG") == "3 bag"
    assert render.quantity("2.50", "KG") == "2.5 kg"
    assert render.quantity("12", "ST") == "12 pcs"


# ---- the brief ---------------------------------------------------------------------------
def test_brief_shows_everything_that_waits_then_one_message_per_supplier(bot):
    say(bot, "/brief")
    assert ("brief", "evening") in bot.gw.calls              # 16:00 in the fixture
    text = bot.tg.edits[-1]["text"]
    lines = text.split("\n")
    assert lines[0] == "Evening brief · Sat 14 Nov"
    assert lines[1] == "<b>3 products needed · 2 suppliers · EUR 2,052.50</b>"
    assert lines[2] == "<b>Active recall for Kulta Katriina coffee: 3.253 KG in stock.</b>"
    assert "Valio Aimo: 2 items, EUR 1,240.10, before Sun 15 Nov 17:00" in lines
    assert "Corner Bakery &lt;demo&gt;: 1 item, EUR 812.40, stock not confirmed" in lines
    assert "Open supplier offer from Valio Aimo &lt;b&gt;for&lt;/b&gt; 10.48 KG potato." in lines   # escaped, not bold
    assert "2 drafts wait." not in text                      # the supplier lines say it already
    assert lines[-1] == "<i>Wording by the Buyer agent (Nemotron).</i>"
    assert bot.tg.edits[-1]["markup"]["inline_keyboard"][0][0]["web_app"]["url"] == "https://site.example/approvals"
    orders = bot.tg.sent[1:]
    assert [m["text"].split(" · ")[0] for m in orders] == ["<b>Valio Aimo", "<b>Corner Bakery &lt;demo&gt;"]
    assert orders[0]["markup"]["inline_keyboard"][0][0]["callback_data"] == f"c:{PID}:0"


def test_brief_with_nothing_is_one_line_with_no_button(bot):
    bot.gw.brief_answer = {"when": "morning", "lines": [], "nothing_urgent": True, "made_by": "rule"}
    bot.gw.waiting_list = []
    say(bot, "/brief morning")
    assert ("brief", "morning") in bot.gw.calls
    assert bot.tg.edits[-1]["text"] == "Morning brief · Sat 14 Nov\nNothing urgent. No orders wait."
    assert bot.tg.edits[-1]["markup"] is None and len(bot.tg.sent) == 1


def test_brief_with_the_model_off_has_the_same_numbers_and_no_nemotron_line(bot):
    bot.gw.brief_answer = {"when": "evening", "lines": [], "nothing_urgent": True, "made_by": "rule"}
    say(bot, "/brief")
    text = bot.tg.edits[-1]["text"]
    assert "<b>3 products needed · 2 suppliers · EUR 2,052.50</b>" in text and "Nemotron" not in text


def test_brief_never_shows_a_part_total(bot):
    broken = proposal()
    broken["blocks"][1]["expected_total"] = None
    bot.gw.waiting_list = [broken]
    say(bot, "/brief")
    text = bot.tg.edits[-1]["text"]
    assert "<b>3 products needed · 2 suppliers</b>" in text
    assert "Corner Bakery &lt;demo&gt;: 1 item, stock not confirmed" in text


def test_brief_adds_up_one_supplier_over_two_orders_and_caps_the_messages(bot):
    bot.gw.waiting_list = [proposal() for _ in range(4)]                     # 8 supplier orders
    say(bot, "/brief")
    text = bot.tg.edits[-1]["text"]
    assert "<b>12 products needed · 2 suppliers · EUR 8,210.00</b>" in text
    assert "Valio Aimo: 8 items, EUR 4,960.40" in text
    assert len(bot.tg.sent) == 1 + render.BRIEF_ORDERS + 1
    assert bot.tg.sent[-1]["text"].startswith("... and 2 more supplier orders.")


def test_brief_says_when_the_gateway_refuses(bot):
    bot.gw.error = GatewayError(503, "STORE_UNAVAILABLE", "The store does not answer.")
    say(bot, "/brief")
    assert bot.tg.edits[-1]["text"] == "The store does not answer."


def test_brief_never_stays_at_one_moment_on_an_unexpected_error(bot, capsys):
    bot.gw.error = RuntimeError("secret content")
    say(bot, "/brief")
    assert bot.tg.edits[-1]["text"] == "The brief could not be made. Try /brief again."
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "secret content" not in err


def test_the_timed_brief_goes_out_once_per_slot_also_after_a_restart(bot, tmp_path):
    bot.now = lambda: datetime(2026, 11, 14, 16, 0, 20, tzinfo=render.HELSINKI)
    bot.tick()
    first = len(bot.tg.sent)
    assert first == 3 and bot.tg.sent[0]["chat"] == 7 and bot.tg.sent[0]["text"].startswith("Evening brief")
    bot.tick()
    assert len(bot.tg.sent) == first
    again = Bot(FakeTelegram(), FakeGateway(), Links(tmp_path), now=bot.now)   # the bot started again
    again.tick()
    assert again.tg.sent == []
    again.now = lambda: datetime(2026, 11, 15, 7, 1, tzinfo=render.HELSINKI)
    again.tick()
    assert again.tg.sent[0]["text"].startswith("Morning brief · Sun 15 Nov")


def test_no_timed_brief_outside_its_window_or_when_switched_off(bot):
    bot.now = lambda: datetime(2026, 11, 14, 15, 59, tzinfo=render.HELSINKI)
    bot.tick()
    bot.now = lambda: datetime(2026, 11, 14, 18, 0, tzinfo=render.HELSINKI)    # started late: not sent
    bot.tick()
    assert bot.tg.sent == [] and bot.gw.calls == []
    assert parse_brief_times("off") == {} and parse_brief_times(None) == {"morning": "07:00", "evening": "16:00"}
    assert parse_brief_times("06:30, 15:00") == {"morning": "06:30", "evening": "15:00"}
    assert due_slot(datetime(2026, 11, 14, 6, 45, tzinfo=render.HELSINKI), {"morning": "06:30"}) == "morning"
    assert due_slot(datetime(2026, 11, 14, 6, 45, tzinfo=render.HELSINKI), {"morning": "nonsense"}) is None


def test_a_failed_timed_brief_is_not_sent_twice(bot):
    bot.now = lambda: datetime(2026, 11, 14, 7, 0, 5, tzinfo=render.HELSINKI)
    bot.gw.error = GatewayError(0, "NETWORK", "The gateway did not answer.")
    bot.tick()
    bot.gw.error = None
    bot.tick()
    assert bot.tg.sent == []


# ---- a shelf photo -----------------------------------------------------------------------
def photo(bot, chat=7):
    bot.handle({"message": {"chat": {"id": chat}, "photo": [
        {"file_id": "small", "width": 90, "height": 60, "file_size": 1200},
        {"file_id": "large", "width": 1280, "height": 960, "file_size": 180000},
        {"file_id": "huge", "width": 4000, "height": 3000, "file_size": 9000000}]}})


def test_a_shelf_photo_shows_the_count_and_saves_nothing_by_itself(bot):
    photo(bot)
    assert [c[0] for c in bot.gw.calls] == ["shelf_photo"]
    shown = bot.tg.edits[-1]
    lines = shown["text"].split("\n")
    assert lines[0] == "<b>Shelf photo: 2 counted · 1 to count by hand</b>"
    assert lines[1] == "<code>6 L   </code>  Valio Eila 3 % milk drink 1 l"
    assert lines[2] == "<code>12 pcs</code>  Eggs M"
    assert lines[3] == "Count by hand: Valio Eila 10 L novobox"
    assert lines[4] == 'Not in this kitchen\'s products: "Arla &lt;b&gt;L&lt;/b&gt; m"'
    assert lines[5] == "<i>Read by Nemotron in 4.2 s. Nothing is saved until you press Save.</i>"
    assert [b["text"] for b in shown["markup"]["inline_keyboard"][0]] == ["Save 2 counts", "Discard"]


def test_save_stores_only_the_counted_rows_once(bot):
    photo(bot)
    message_id = bot.tg.edits[-1]["id"]
    press(bot, "s:save:0", message_id)
    saves = [c for c in bot.gw.calls if c[0] == "save_counts"]
    assert len(saves) == 1
    assert saves[0][1] == [{"product_id": "463335", "on_hand": "6", "unit": "L"},
                           {"product_id": "400100", "on_hand": "12", "unit": "PCS"}]
    assert saves[0][2] == "2026-11-14T16:00:00+02:00" and saves[0][3] == f"tg-shelf-7-{message_id}"
    assert bot.tg.edits[-1]["text"].startswith("<b>Saved: 2 counts</b>") and bot.tg.edits[-1]["markup"] is None
    press(bot, "s:save:0", message_id)                       # a second press
    assert len([c for c in bot.gw.calls if c[0] == "save_counts"]) == 1
    assert bot.tg.answers[-1] == "This photo is out of date. Send it again."


def test_discard_saves_nothing(bot):
    photo(bot)
    press(bot, "s:drop:0", bot.tg.edits[-1]["id"])
    assert bot.tg.edits[-1]["text"] == "Discarded. Nothing was saved."
    assert not [c for c in bot.gw.calls if c[0] == "save_counts"]


def test_a_failed_save_keeps_the_count_for_a_second_try(bot):
    photo(bot)
    message_id = bot.tg.edits[-1]["id"]
    bot.gw.error = GatewayError(503, "STORE_UNAVAILABLE", "The store does not answer.")
    press(bot, "s:save:0", message_id)
    assert bot.tg.answers[-1] == "The store does not answer."
    bot.gw.error = None
    press(bot, "s:save:0", message_id)
    assert bot.tg.answers[-1] == "Saved."


def test_a_photo_with_nothing_counted_has_no_save_button(bot):
    bot.gw.shelf_answer = {"duration_ms": 900, "rows": [bot.gw.shelf_answer["rows"][2]]}
    photo(bot)
    assert bot.tg.edits[-1]["markup"] is None
    assert "<b>Shelf photo: 0 counted · 1 to count by hand</b>" in bot.tg.edits[-1]["text"]
    assert "Nothing to save" in bot.tg.edits[-1]["text"]
    bot.gw.shelf_answer = {"duration_ms": 900, "rows": []}
    photo(bot)
    assert bot.tg.edits[-1]["text"].startswith("<b>I see no product on this photo.</b>")


def test_a_busy_read_and_a_photo_from_an_unlinked_chat(bot):
    bot.gw.error = GatewayError(429, "STOCK_PHOTO_BUSY", "busy")
    photo(bot)
    assert bot.tg.edits[-1]["text"].startswith("Another photo is being read.")
    bot.gw.error, before = None, len(bot.gw.calls)
    photo(bot, chat=99)
    assert bot.tg.sent[-1]["text"] == NOT_LINKED and len(bot.gw.calls) == before


def test_the_largest_photo_that_fits_is_read(bot):
    seen = []
    bot.tg.download = lambda file_id, limit=0: seen.append(file_id) or b"JPEG"
    photo(bot)
    assert seen == ["large"]


def test_a_failed_photo_download_says_so(bot):
    def fail(file_id, limit=0):
        raise TelegramError("getFile failed")
    bot.tg.download = fail
    photo(bot)
    assert bot.tg.edits[-1]["text"] == "I could not fetch that photo. Send it again."
    assert not [c for c in bot.gw.calls if c[0] == "shelf_photo"]


# ---- add a product -----------------------------------------------------------------------
def test_add_product_lists_what_the_gateway_offers_with_the_engines_quantity(bot):
    press(bot, f"p:{PID}:0")
    shown = bot.tg.edits[-1]
    rows = shown["markup"]["inline_keyboard"]
    assert [r[0]["text"] for r in rows] == ["+ 12 pcs  Butter 500 g", "+ 6 pcs  Cream <1 L>", "Done"]   # no suggestion: one lot
    assert rows[0][0]["callback_data"] == f"d:{PID}:0:469549b"
    assert all(len(r[0]["callback_data"].encode()) <= 64 for r in rows)          # Telegram's limit
    assert "Press a product to add it" in shown["text"]


def test_a_press_adds_the_product_and_the_total_moves(bot):
    say(bot, "20 L oat drink")
    summary_id = bot.tg.sent[0]["id"]
    press(bot, f"p:{PID}:0")
    press(bot, f"d:{PID}:0:469549b")
    assert ("add", "469549b", "12") in bot.gw.calls
    assert bot.tg.answers[-1] == "Added."
    assert "<b>Valio Aimo · 3 items" in bot.tg.edits[-1]["text"]                 # back in view, with the new line
    assert [b["text"] for b in bot.tg.edits[-1]["markup"]["inline_keyboard"][0]] == ["Change", "Add product"]
    summary = [e for e in bot.tg.edits if e["id"] == summary_id][-1]
    assert "EUR 2,098.70" in summary["text"]


def test_an_add_that_makes_a_new_supplier_block_shows_that_supplier(bot):
    bot.gw.current = proposal(blocks=[{"supplier_id": "sup-valio", "name": "Valio Aimo", "expected_total": "1240.10",
                                       "lines": [line("463380", "698", "L")]}])

    def add(proposal_id, product_id, quantity):
        bot.gw.calls.append(("add", product_id, quantity))
        bot.gw.current["blocks"].append({"supplier_id": "sup-bakery", "name": "Corner Bakery", "expected_total": "46.20",
                                         "lines": [line(product_id, quantity)]})
        return bot.gw.current
    bot.gw.add = add
    press(bot, f"p:{PID}:0")
    press(bot, f"d:{PID}:0:469549b")
    assert bot.tg.answers[-1] == "Added."
    assert "<b>Corner Bakery · 1 item" in bot.tg.edits[-1]["text"]


def test_nothing_to_add_and_a_refused_add_are_said(bot):
    bot.gw.addable_rows = []
    press(bot, f"p:{PID}:0")
    assert bot.tg.answers[-1].startswith("Nothing to add")
    bot.gw.addable_rows = [{"product_id": "469549b", "name": "Butter", "suggested_qty": "12", "unit": "ST", "addable": True}]
    press(bot, f"p:{PID}:0")
    bot.gw.error = GatewayError(409, "NOT_ADDABLE", "This product cannot be added now.")
    press(bot, f"d:{PID}:0:469549b")
    assert bot.tg.answers[-1] == "This product cannot be added now."
    bot.gw.error = None
    press(bot, f"d:{PID}:0:unknown")                                             # an old button
    assert bot.tg.answers[-1] == "This product can no longer be added. Press Add product again."


def test_add_works_after_a_restart_of_the_bot(bot):
    press(bot, f"d:{PID}:0:469549b")                                             # no list in memory
    assert ("addable", PID) in bot.gw.calls and ("add", "469549b", "12") in bot.gw.calls


# ---- found in the first live test, 2026-11-14 ---------------------------------------------
def test_a_question_is_explained_and_never_sent_to_the_buyer(bot):
    say(bot, "what does it mean active recall?")
    assert bot.gw.calls == []
    assert bot.tg.sent[-1]["text"].startswith("<b>Active recall</b>: the Finnish Food Authority")
    say(bot, "why is the sky blue")
    assert bot.tg.sent[-1]["text"].startswith("I make orders and briefs") and bot.gw.calls == []
    say(bot, "can I get 20 L oat drink for Monday?")             # a number: this is an order
    say(bot, "what the menu needs")                              # not a question form
    assert [c[0] for c in bot.gw.calls] == ["ask", "ask"]


def test_a_change_updates_the_last_brief_and_the_summary_also_after_a_restart(bot, tmp_path):
    say(bot, "20 L oat drink")
    summary_id = bot.tg.sent[0]["id"]
    say(bot, "/brief")
    brief_id = [m for m in bot.tg.sent if m["text"].startswith("One moment: I am reading")][0]["id"]
    again = Bot(FakeTelegram(), bot.gw, Links(tmp_path), site_url="https://site.example/", now=bot.now)   # restarted
    press(again, f"q:{PID}:0:0:+")
    edited = {e["id"]: e["text"] for e in again.tg.edits}
    assert "EUR 2,100.00" in edited[summary_id]                  # the order's summary
    assert "EUR 2,100.00" not in edited[brief_id]                # the brief adds up the blocks, not the fake total
    assert edited[brief_id].startswith("Evening brief · Sat 14 Nov") and "Valio Aimo: 2 items" in edited[brief_id]
    assert "<code>704 L" in edited[555]                          # and the supplier message itself


def test_a_message_that_cannot_be_edited_does_not_stop_the_change(bot):
    from bot.clients import TelegramError
    say(bot, "20 L oat drink")
    summary_id = bot.tg.sent[0]["id"]
    real = bot.tg.edit

    def edit(chat_id, message_id, text, markup=None):
        if message_id == summary_id:
            raise TelegramError("editMessageText: message is not modified")
        real(chat_id, message_id, text, markup)

    bot.tg.edit = edit
    press(bot, f"q:{PID}:0:0:+")
    assert ("change", "463380", "704") in bot.gw.calls
    assert bot.tg.edits[-1]["id"] == 555 and "704 L" in bot.tg.edits[-1]["text"]


def test_brief_lines_are_short_for_a_phone_and_an_unread_label_is_said_plainly(bot):
    assert render.tidy("check for order a39ccb6d3ba6416ab4517a0eae53c0f1: SHORT 1") == "check for order a39ccb6d: SHORT 1"
    assert render.tidy("requested for 2026-11-16.") == "requested for Mon 16 Nov."
    assert render.tidy("3.253 KG <in> stock") == "3.253 KG &lt;in&gt; stock"
    read = render.shelf({"duration_ms": 900, "rows": [{"row": "UNMATCHED", "label": "unknown"}]})
    assert "One pack with no label I can read." in read.text and "unknown" not in read.text
