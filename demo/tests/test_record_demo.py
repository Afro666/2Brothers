"""The demo recorder's plan (demo/record_demo.py). The browser run itself is not a unit test."""

from datetime import date
from pathlib import Path

import pytest

from demo.record_demo import next_monday, steps


def test_next_monday_is_always_ahead():
    assert next_monday(date(2026, 11, 14)) == date(2026, 11, 16)      # Saturday
    assert next_monday(date(2026, 11, 15)) == date(2026, 11, 16)      # Sunday
    assert next_monday(date(2026, 11, 16)) == date(2026, 11, 23)      # a Monday: the next one


def test_nothing_is_approved_unless_asked():
    plain = [name for name, _, _ in steps("https://x", "200 L milk", "2026-11-16", approve=False)]
    assert "approve" not in plain
    assert plain == ["home", "ask", "proposal", "inbox", "log", "tamper", "llms", "card"]
    asked = [name for name, _, _ in steps("https://x", "200 L milk", "2026-11-16", approve=True)]
    assert asked.index("approve") == asked.index("inbox") + 1


def test_every_step_has_a_caption_and_the_module_needs_no_browser_to_import():
    for name, caption, action in steps("https://x", "200 L milk", "2026-11-16", approve=True):
        assert caption.strip() and callable(action), name


class _Fake:
    """A stand-in for Playwright's page and locators that records how `decide` scopes its click."""

    def __init__(self, log):
        self.log = log

    def locator(self, selector):
        self.log.append(("locator", selector))
        return self

    def get_by_text(self, text, exact=False):
        self.log.append(("text", text, exact))
        return self

    def filter(self, has=None):
        self.log.append(("filter",))
        return self

    def get_by_role(self, role, name=None, exact=False):
        self.log.append(("role", role, name))
        return self

    def all(self):
        return []


def test_approve_is_scoped_to_the_card_of_the_request_it_sent():
    decide = {n: a for n, _, a in steps("https://x", " 200 L milk ", "2026-11-16", approve=True)}["approve"]
    log = []
    with pytest.raises(RuntimeError, match="200 L milk"):
        decide(_Fake(log))     # no card for this request: nothing is clicked
    assert log == [("locator", '[data-slot="card"]'), ("text", "200 L milk", True), ("filter",),
                   ("role", "button", "Choose option"), ("role", "button", "Option A"),
                   ("role", "button", "Choose option"), ("role", "button", "Approve")]


class _Button:
    def __init__(self, name, clicks, enabled=True, expanded=None, reveals=None):
        self.name, self.clicks, self.enabled = name, clicks, enabled
        self.expanded, self.reveals = expanded, reveals      # a folded option header and what it shows

    def get_attribute(self, name):
        assert name == "aria-expanded"
        return self.expanded

    def is_enabled(self):
        return self.enabled

    def scroll_into_view_if_needed(self):
        pass

    def click(self):
        self.clicks.append(self.name)
        if self.reveals:
            group, button = self.reveals
            group.append(button)
            self.expanded = "true"


class _Group:
    """A locator that answers `get_by_role("button", name=...)` from a fixed set of buttons."""

    def __init__(self, buttons):
        self.buttons = buttons

    def filter(self, has=None):
        return self

    def get_by_role(self, role, name=None, exact=False):
        return _Group([b for b in self.buttons if name in b.name])

    def all(self):
        return list(self.buttons)


class _Dialog:
    def __init__(self, button):
        self.button = button

    def get_by_role(self, role, name=None, exact=False):
        assert role == "button" and name in self.button.name
        return self.button


class _Page:
    """One inbox card with the given buttons, and the confirm dialog with "Yes, approve"."""

    def __init__(self, card_buttons, clicks):
        self.cards = _Group(card_buttons)
        self.dialog = _Dialog(_Button("Yes, approve", clicks))

    def locator(self, selector):
        return self.cards

    def get_by_text(self, text, exact=False):
        return None

    def get_by_role(self, role, name=None, exact=False):
        assert role == "dialog"
        return self.dialog

    def wait_for_timeout(self, ms):
        pass


def test_a_folded_option_a_is_opened_to_reach_choose_option():
    """The inbox folds the options (seen live on 2026-11-14): "Choose option A" is not on the
    page until "Option A" is opened, and the plain Approve is disabled."""
    clicks, buttons = [], []
    choose = _Button("Choose option A: approve", clicks)
    buttons += [_Button("Option A: 698 ST 463380", clicks, expanded="false", reveals=(buttons, choose)),
                _Button("Option B: 698 ST + 302 ST", clicks, expanded="false"),
                _Button("Approve", clicks, enabled=False)]
    _decide()(_Page(buttons, clicks))
    assert clicks == ["Option A: 698 ST 463380", "Choose option A: approve", "Yes, approve"]


def test_an_open_option_a_is_not_folded_again():
    clicks = []
    buttons = [_Button("Option A: 100 ST", clicks, expanded="true"), _Button("Approve", clicks)]
    _decide()(_Page(buttons, clicks))
    assert clicks == ["Approve", "Yes, approve"]


def _decide():
    return {n: a for n, _, a in steps("https://x", "200 L milk", "2026-11-16", approve=True)}["approve"]


def test_choose_option_is_pressed_before_approve():
    clicks = []
    page = _Page([_Button("Approve", clicks), _Button("Choose option A", clicks)], clicks)
    _decide()(page)
    assert clicks == ["Choose option A", "Yes, approve"]


def test_a_plain_approve_is_pressed_when_there_is_no_option_to_choose():
    clicks = []     # the 200 L backup request: only an enabled Approve
    page = _Page([_Button("Approve", clicks)], clicks)
    _decide()(page)
    assert clicks == ["Approve", "Yes, approve"]


# ---- story A, "Valio sees it first" (--story offer) -------------------------------------

def _offer_plan(approve=False, press_recall=False):
    return steps("https://x", "ignored", "2026-11-16", approve=approve, story="offer", press_recall=press_recall)


def test_the_milk_story_stays_the_default():
    default = [n for n, _, _ in steps("https://x", "200 L milk", "2026-11-16", False)]
    assert default == [n for n, _, _ in steps("https://x", "200 L milk", "2026-11-16", False, story="milk")]
    with pytest.raises(ValueError):
        steps("https://x", "200 L milk", "2026-11-16", False, story="other")


def test_story_a_plan_in_order_and_the_offer_is_used_only_with_approve():
    assert [n for n, _, _ in _offer_plan()] == [
        "offer", "receipt", "recall", "refuse", "tamper", "llms", "card", "demand"]
    assert [n for n, _, _ in _offer_plan(approve=True)] == [
        "offer", "accept", "approve", "receipt", "recall", "refuse", "tamper", "llms", "card", "demand"]
    for name, caption, action in _offer_plan(approve=True, press_recall=True):
        assert caption.strip() and callable(action), name


def test_the_offer_title_matches_only_the_card_made_from_this_offer():
    from demo.record_demo import offer_title
    title = offer_title(" Valio Eila lactose-free milk drink 1 L ")
    assert title.search("Offer from Valio Aimo: Valio Eila lactose-free milk drink 1 L in place of Arla milk 1 L")
    assert not title.search("Offer from Valio Aimo: Valio oat drink 1 L in place of Arla milk 1 L")
    assert not title.search("1,000 L lactose-free milk by Monday")
    assert not title.search("Re: Offer from Valio Aimo: Valio Eila lactose-free milk drink 1 L in place of x")
    loose = offer_title(None)          # the tile was not read: any card made from a Valio offer
    assert loose.search("Offer from Valio Aimo: oat drink in place of milk")
    assert not loose.search("Offer from Valio Aimotion")


class _Card(_Group):
    def __init__(self, title, buttons):
        super().__init__(buttons)
        self.title = title


class _Found:
    """What `get_by_text(pattern)` answers: something to wait for."""

    def __init__(self):
        self.first = self

    def wait_for(self, timeout=None):
        pass


class _OfferPage(_Page):
    """The inbox with several cards; `filter(has=get_by_text(pattern))` keeps the cards whose
    title the pattern matches, as Playwright does."""

    def __init__(self, cards, clicks):
        super().__init__([], clicks)
        self.all_cards, self.url, self.matched = cards, "https://x/approvals", []

    def goto(self, url):
        self.url = url

    def get_by_text(self, pattern, exact=False):
        self.matched = [card for card in self.all_cards if pattern.search(card.title)]
        return _Found()

    def locator(self, selector):
        assert selector == '[data-slot="card"]'
        return _InboxCards(self)


class _InboxCards(_Group):
    """Read live, so a button an opened Option A reveals is found on the next look."""

    def __init__(self, page):
        self.page = page

    @property
    def buttons(self):
        return [b for card in self.page.matched for b in card.buttons]

    def filter(self, has=None):
        return self

    def count(self):
        return len(self.page.matched)


def _offer_decide():
    return {n: a for n, _, a in _offer_plan(approve=True)}["approve"]


def test_approve_in_story_a_clicks_only_the_offer_card():
    clicks = []
    milk = _Card("1,000 L lactose-free milk by Monday", [_Button("Approve milk", clicks)])
    offer = _Card("Offer from Valio Aimo: oat drink in place of milk", [_Button("Approve offer", clicks)])
    _offer_decide()(_OfferPage([milk, offer], clicks))
    assert clicks == ["Approve offer", "Yes, approve"]


def test_story_a_opens_a_folded_option_a_on_the_offer_card():
    clicks, buttons = [], []
    choose = _Button("Choose option A: approve", clicks)
    buttons += [_Button("Option A: 42 L", clicks, expanded="false", reveals=(buttons, choose)),
                _Button("Approve", clicks, enabled=False)]
    other = _Card("1,000 L lactose-free milk by Monday", [_Button("Choose option A: other", clicks)])
    page = _OfferPage([other, _Card("Offer from Valio Aimo: oat drink in place of milk", buttons)], clicks)
    _offer_decide()(page)
    assert clicks == ["Option A: 42 L", "Choose option A: approve", "Yes, approve"]


def test_story_a_approves_nothing_without_exactly_one_offer_card():
    clicks = []
    milk = _Card("1,000 L lactose-free milk by Monday", [_Button("Approve", clicks)])
    with pytest.raises(RuntimeError, match="0 inbox cards"):
        _offer_decide()(_OfferPage([milk], clicks))
    two = [_Card("Offer from Valio Aimo: oat drink in place of milk", [_Button("Approve", clicks)]),
           _Card("Offer from Valio Aimo: rye in place of wheat", [_Button("Approve", clicks)])]
    with pytest.raises(RuntimeError, match="2 inbox cards"):
        _offer_decide()(_OfferPage(two, clicks))
    assert clicks == []


class _TilePage:
    """Home with the offer tile: records which locator each click went through."""

    def __init__(self, product):
        self.log, self.url, self.product = [], "https://x/", product

    def goto(self, url):
        self.log.append(("goto", url))
        self.url = url

    def wait_for_timeout(self, ms):
        pass

    def wait_for_url(self, pattern, timeout=None):
        self.url = "https://x/approvals"

    def locator(self, selector):
        return _TileLocator(self, selector)


class _TileLocator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector
        self.first = self

    def wait_for(self, timeout=None):
        pass

    def scroll_into_view_if_needed(self):
        pass

    def count(self):
        return 1

    def locator(self, selector):
        return _TileLocator(self.page, f"{self.selector} >> {selector}")

    def inner_text(self):
        return f" {self.page.product} "

    def get_by_role(self, role, name=None, exact=False):
        return _Press(self.page, self.selector, role, name)


class _Press:
    def __init__(self, page, scope, role, name):
        self.page, self.scope, self.role, self.name = page, scope, role, name

    def click(self):
        self.page.log.append(("click", self.scope, self.role, self.name))

    def wait_for(self, timeout=None):
        pass


def test_make_a_proposal_is_pressed_inside_the_offer_tile_and_feeds_the_approve_step():
    plan = {n: a for n, _, a in _offer_plan(approve=True)}
    page = _TilePage(product="oat drink")
    plan["offer"](page)
    plan["accept"](page)
    assert page.log[-1] == ("click", '[aria-labelledby="supplier-offer-title"]', "button", "Make a proposal")
    clicks = []
    inbox = _OfferPage([_Card("Offer from Valio Aimo: rye in place of wheat", [_Button("Approve rye", clicks)]),
                        _Card("Offer from Valio Aimo: oat drink in place of milk", [_Button("Approve oat", clicks)])],
                       clicks)
    plan["approve"](inbox)      # two offer cards, but the tile named the product: only one matches
    assert clicks == ["Approve oat", "Yes, approve"]


class _RecallPage:
    """The inbox with the recall panel; records the buttons pressed inside the panel."""

    def __init__(self):
        self.log = []

    def goto(self, url):
        pass

    def wait_for_timeout(self, ms):
        pass

    def get_by_role(self, role, name=None, exact=False):
        assert (role, name) == ("region", "Food recalls")
        return _Panel(self)


class _Panel:
    def __init__(self, page):
        self.page = page

    def wait_for(self, timeout=None):
        pass

    def scroll_into_view_if_needed(self):
        pass

    def get_by_role(self, role, name=None, exact=False):
        return _Press(self.page, "panel", role, name)


def test_check_recalls_is_pressed_only_with_press_recall():
    page = _RecallPage()
    {n: a for n, _, a in _offer_plan()}["recall"](page)
    assert page.log == []
    {n: a for n, _, a in _offer_plan(press_recall=True)}["recall"](page)
    assert page.log == [("click", "panel", "button", "Check recalls now")]


def test_story_a_asks_the_peanut_request():
    from demo.record_demo import REFUSED_TEXT
    assert REFUSED_TEXT == "15 kg peanut butter"
    assert "peanut" in {n: c for n, c, _ in _offer_plan()}["refuse"]


def test_story_a_options_on_the_command_line(monkeypatch):
    from demo import record_demo
    seen = {}
    monkeypatch.setattr(record_demo, "site_needs_sign_in", lambda base: False)
    monkeypatch.setattr(record_demo, "record", lambda *a, **k: seen.update(k) or "video.webm")
    record_demo.main(["--story", "offer", "--approve"])
    assert seen["story"] == "offer" and seen["press_recall"] is False
    record_demo.main([])
    assert seen["story"] == "milk" and seen["press_recall"] is False
    record_demo.main(["--story", "offer", "--press-recall"])
    assert seen["press_recall"] is True


# ---- sign-in (a site with GATEWAY_REQUIRE_LOGIN=true) ------------------------------------

class _Field:
    def __init__(self, page, label):
        self.page, self.label = page, label

    def wait_for(self, state="visible", timeout=None):
        self.page.log.append(("wait", self.label, state))
        if state == "visible" and self.page.open_site:
            raise TimeoutError("no sign-in page")
        if state == "detached" and not self.page.accepts:
            raise TimeoutError("still there")

    def fill(self, value):
        self.page.filled[self.label] = value

    def click(self):
        self.page.log.append(("click", self.label))


class _Alert:
    def __init__(self, text):
        self.text = text
        self.first = self

    def count(self):
        return 1 if self.text else 0

    def inner_text(self):
        return self.text


class _SignInPage:
    """The sign-in page: it goes away when the site accepts, else it shows `alert`."""

    def __init__(self, accepts, alert="", open_site=False):
        self.accepts, self.alert, self.log, self.filled, self.open_site = accepts, alert, [], {}, open_site

    def goto(self, url):
        self.log.append(("goto", url))

    def get_by_label(self, label):
        return _Field(self, label)

    def get_by_role(self, role, name=None, exact=False):
        return _Alert(self.alert) if role == "alert" else _Field(self, name)


def test_sign_in_fills_the_form_on_the_sign_in_page_and_waits_until_it_is_gone():
    from demo.record_demo import sign_in
    page = _SignInPage(accepts=True)
    assert sign_in(page, "https://x", "approver@example.test", "a-long-password") is True
    assert page.log[0] == ("goto", "https://x/sign-in")
    assert page.filled == {"Email": "approver@example.test", "Password": "a-long-password"}
    assert page.log[-2:] == [("click", "Sign in"), ("wait", "Password", "detached")]


def test_an_open_site_shows_no_sign_in_page_and_nothing_is_typed():
    from demo.record_demo import sign_in
    page = _SignInPage(accepts=True, open_site=True)
    assert sign_in(page, "https://x", "approver@example.test", "a-long-password") is False
    assert page.filled == {}


def test_a_refused_sign_in_stops_with_the_sites_message_and_never_the_password():
    from demo.record_demo import sign_in
    page = _SignInPage(accepts=False, alert="wrong email or password")
    with pytest.raises(RuntimeError) as error:
        sign_in(page, "https://x", "approver@example.test", "a-long-password")
    assert "wrong email or password" in str(error.value) and "approver@example.test" in str(error.value)
    assert "a-long-password" not in str(error.value)


def test_the_password_comes_from_the_environment_and_a_closed_site_is_named():
    from demo.record_demo import sign_in_problem
    assert "DEMO_PASSWORD" in sign_in_problem("a@b.c", None, lambda: False)
    assert sign_in_problem("a@b.c", "a-long-password", lambda: pytest.fail("not asked")) is None
    assert "--email" in sign_in_problem(None, None, lambda: True)       # the site has sign-in on
    assert sign_in_problem(None, None, lambda: False) is None            # the open demo: as before


def test_there_is_no_password_argument(monkeypatch, capsys):
    from demo import record_demo
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    with pytest.raises(SystemExit):
        record_demo.main(["--email", "a@b.c", "--password", "x"])
    assert "unrecognized arguments" in capsys.readouterr().err
    with pytest.raises(SystemExit) as stop:
        record_demo.main(["--email", "a@b.c"])                          # no browser is started
    assert "DEMO_PASSWORD" in str(stop.value)


def test_site_needs_sign_in_reads_the_session_check():
    import urllib.error
    from demo.record_demo import site_needs_sign_in

    def answers(code):
        def opener(request, timeout=None):
            assert request.full_url == "https://x/api/v1/me"
            if code == 200:
                class _Ok:
                    def __enter__(self):
                        return self

                    def __exit__(self, *exc):
                        return False
                return _Ok()
            if code is None:
                raise OSError("no connection")
            raise urllib.error.HTTPError(request.full_url, code, "refused", {}, None)
        return opener

    assert site_needs_sign_in("https://x", answers(401)) is True
    assert site_needs_sign_in("https://x", answers(200)) is False        # the open demo
    assert site_needs_sign_in("https://x", answers(502)) is False
    assert site_needs_sign_in("https://x", answers(None)) is False


# ---- the NVIDIA demo (--story nvidia, #1196) ---------------------------------------------

class _Any:
    """A permissive stand-in for Playwright's page and locators. Every lookup gives another
    `_Any` that knows its chain, so a click records exactly which button it went through.
    `texts` are the texts the page shows; `alert` is an error the page shows; `uploads` and
    `clicks` record what the actions did."""

    url = "https://x/"

    def __init__(self, page=None, chain=(), texts=(), alert=""):
        self.page = page or self
        self.chain = chain
        if page is None:
            self.texts, self.alert, self.clicks, self.uploads, self.urls = set(texts), alert, [], [], []
            self.order_id, self.content = "ord-1", None
        self.first = self

    def _child(self, *link):
        return _Any(self.page, self.chain + link)

    def goto(self, url):
        self.page.urls.append(url)

    def wait_for_timeout(self, ms):
        pass

    def wait_for(self, state="visible", timeout=None):
        pass

    def scroll_into_view_if_needed(self):
        pass

    def evaluate(self, script, arg=None):
        return self.page.order_id if "order_id" in script else None

    def set_content(self, html):
        self.page.content = html

    def locator(self, selector):
        return self._child(("locator", selector))

    def get_by_label(self, label):
        return self._child(("label", label))

    def get_by_text(self, text, exact=False):
        return self._child(("text", text))

    def get_by_role(self, role, name=None, exact=False):
        return self._child(("role", role, name))

    def count(self):
        kind = self.chain[-1] if self.chain else None
        if kind and kind[0] == "text":
            return int(any(kind[1] in shown for shown in self.page.texts))
        if kind and kind[:2] == ("role", "alert"):
            return int(bool(self.page.alert))
        return 1

    def inner_text(self):
        return self.page.alert

    def fill(self, value):
        pass

    def click(self):
        self.page.clicks.append(self.chain)

    def set_input_files(self, path):
        self.page.uploads.append((self.chain, path))


def _nvidia(photos=None, approve=False):
    return steps("https://x", "1,000 L lactose-free milk by Monday", "2026-11-16", approve=approve,
                 story="nvidia", photos=photos)


def _note(tmp_path):
    note = tmp_path / "note.png"
    note.write_bytes(b"png")
    return {"note": note}


def test_nvidia_plan_has_the_five_jobs_in_order_and_ends_on_the_numbers():
    plan = _nvidia()
    assert [n for n, _, _ in plan] == [
        "intro", "plan", "buy", "trace", "sell", "count", "receive", "numbers", "improved"]
    for name, caption, action in plan:
        assert caption.strip() and callable(action), name
    assert "never sets a number" in {n: c for n, c, _ in plan}["intro"]


def test_nvidia_never_approves_even_when_asked():
    for flag in (False, True):
        names = {n for n, _, _ in _nvidia(approve=flag)}
        assert not {"approve", "accept"} & names


def test_no_nvidia_action_presses_a_button_that_decides_orders_or_saves(tmp_path):
    from demo.record_demo import NEVER_PRESSED
    page = _Any(texts={"What Nemotron did", "Why this basket"})
    for _, _, action in _nvidia(_note(tmp_path)):
        action(page)
    pressed = [link for chain in page.clicks for link in chain if link[0] == "role"]
    for link in pressed:
        assert not any(word in (link[2] or "") for word in NEVER_PRESSED), link
    assert pressed == [("role", "button", "Ask the agent")]      # the only button pressed by name
    assert page.content and "How we improved its outputs" in page.content


def test_the_photos_go_to_their_own_file_inputs(tmp_path):
    page = _Any()
    plan = {n: a for n, _, a in _nvidia(_note(tmp_path))}
    for name in ("plan", "count", "receive"):
        plan[name](page)
    inputs = [(chain[0][1], chain[-1][1], Path(path).name) for chain, path in page.uploads]
    assert inputs == [
        ('[aria-labelledby="menu-photo-title"]', 'input[type="file"][aria-label="Choose a photo of the menu"]',
         "menu-photo.png"),
        ('[aria-labelledby="shelf-photo-title"]', 'input[type="file"][aria-label="Choose a photo of the shelf"]',
         "demo-shelf.png"),
        ('[aria-labelledby="delivery-note-title"]', 'input[type="file"][aria-label="Choose a delivery note photo"]',
         "note.png"),
    ]
    assert "https://x/planner?week=2026-W47" in page.urls
    assert "https://x/orders/ord-1" in page.urls


def test_the_default_photos_are_in_the_repo():
    from demo.record_demo import DEFAULT_PHOTOS
    assert DEFAULT_PHOTOS["menu"].is_file() and DEFAULT_PHOTOS["shelf"].is_file()
    assert DEFAULT_PHOTOS["note"] is None            # the prepared note comes with #1198


def test_a_beat_whose_model_did_not_answer_is_skipped_with_the_pages_words():
    page = _Any(alert="The model is not answering right now. Plan the week by hand or try again later.")
    plan = {n: a for n, _, a in _nvidia()}
    with pytest.raises(RuntimeError, match="model did not answer: The model is not answering"):
        plan["plan"](page)
    with pytest.raises(RuntimeError, match="model did not answer"):
        plan["count"](page)


def test_the_receive_beat_waits_for_the_prepared_note_and_for_an_order(tmp_path):
    with pytest.raises(RuntimeError, match="after #1198"):
        {n: a for n, _, a in _nvidia()}["receive"](_Any())
    page = _Any()
    page.order_id = None
    with pytest.raises(RuntimeError, match="no order"):
        {n: a for n, _, a in _nvidia(_note(tmp_path))}["receive"](page)
    with pytest.raises(RuntimeError, match="is not there"):
        {n: a for n, _, a in _nvidia({"note": tmp_path / "gone.png"})}["receive"](_Any())


def test_the_trace_beat_waits_for_the_panel_of_1197():
    trace = {n: a for n, _, a in _nvidia()}["trace"]
    with pytest.raises(RuntimeError, match="after #1197"):
        trace(_Any())
    page = _Any(texts={"What Nemotron did"})
    trace(page)
    assert page.clicks == [(("text", "What Nemotron did"),)]


def test_a_fallback_answer_is_said_and_never_credited_to_nemotron():
    plan = {n: a for n, _, a in _nvidia()}
    assert plan["buy"](_Any(texts={"Why this basket", "Proposed by the Buyer agent (Nemotron 3.5 Super VL)"})) is None
    said = plan["buy"](_Any(texts={"Why this basket", "Proposed by the gateway’s request parser, not the Buyer model"}))
    assert "request parser" in said and "not Nemotron" in said
    assert plan["sell"](_Any(texts={"written by Valio's selling agent (Nemotron 3.5 Super VL)"})) is None
    said = plan["sell"](_Any(texts={"written by Valio's selling agent (picked by rule, not by a model)"}))
    assert "rule" in said and "Nemotron" not in said


def test_the_improved_tables_are_read_from_submission_md():
    from demo.record_demo import improved_html, improved_tables
    tables = improved_tables()
    assert len(tables) == 2
    assert tables[0][0][:2] == ["Setting", "Score EUR/week"]
    assert ["Nemotron, thinking on", "4395", "-2817", "0", "1"] in tables[0]
    assert tables[1][0][0] == "Live loop" and any("289" in row for row in tables[1])
    page = improved_html([[["a<b", "c"], ["1", "2"]]])
    assert "a&lt;b" in page and "<th" in page and "<td" in page


def test_improved_tables_name_a_missing_part(tmp_path):
    from demo.record_demo import improved_tables
    other = tmp_path / "submission.md"
    other.write_text("# nothing here\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="How we improved"):
        improved_tables(other)


def test_iso_week_is_the_planners_week():
    from demo.record_demo import iso_week
    assert iso_week("2026-11-16") == "2026-W47"
    assert iso_week("2027-01-01") == "2026-W53"


def test_record_shows_the_caption_an_action_returns(monkeypatch, tmp_path):
    """The caption bar shows the fallback sentence an action returns, not the planned one."""
    import sys
    import types
    from demo import record_demo
    shown = []

    class _Video:
        def path(self):
            return str(tmp_path / "v.webm")

    class _RecPage:
        video = _Video()

        def evaluate(self, script, arg=None):
            if script == record_demo.CAPTION_JS:
                shown.append(arg)

        def wait_for_timeout(self, ms):
            pass

    class _Ctx:
        def new_page(self):
            return _RecPage()

        def close(self):
            pass

    class _Browser:
        def new_context(self, **kw):
            return _Ctx()

        def close(self):
            pass

    class _PW:
        chromium = types.SimpleNamespace(launch=lambda: _Browser())

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = lambda: _PW()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    monkeypatch.setattr(record_demo, "steps", lambda *a, **k: [
        ("one", "planned", lambda page: None), ("two", "planned", lambda page: "the parser answered")])
    record_demo.record("https://x", tmp_path, "t", "2026-11-16", False, 0)
    assert shown == ["planned", "the parser answered"]


def test_nvidia_on_the_command_line(monkeypatch):
    from demo import record_demo
    seen = {}
    monkeypatch.setattr(record_demo, "site_needs_sign_in", lambda base: False)
    monkeypatch.setattr(record_demo, "record", lambda *a, **k: seen.update(k) or "video.webm")
    record_demo.main(["--story", "nvidia", "--note-photo", "n.png"])
    assert seen["story"] == "nvidia" and seen["photos"]["note"] == "n.png"
    assert seen["photos"]["menu"].endswith("menu-photo.png")
    for refused in (["--approve"], ["--press-recall"]):
        seen.clear()
        with pytest.raises(SystemExit) as stop:
            record_demo.main(["--story", "nvidia", *refused])
        assert "never approves" in str(stop.value) and not seen       # nothing was recorded
