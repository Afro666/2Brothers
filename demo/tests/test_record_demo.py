"""The demo recorder's plan (demo/record_demo.py). The browser run itself is not a unit test."""

from datetime import date

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
                   ("role", "button", "Choose option"), ("role", "button", "Approve")]


class _Button:
    def __init__(self, name, clicks, enabled=True):
        self.name, self.clicks, self.enabled = name, clicks, enabled

    def is_enabled(self):
        return self.enabled

    def scroll_into_view_if_needed(self):
        pass

    def click(self):
        self.clicks.append(self.name)


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
