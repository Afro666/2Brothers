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
