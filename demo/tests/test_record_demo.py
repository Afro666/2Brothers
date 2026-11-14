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
