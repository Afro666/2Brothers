"""The demo recorder's plan (demo/record_demo.py). The browser run itself is not a unit test."""

from datetime import date

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
