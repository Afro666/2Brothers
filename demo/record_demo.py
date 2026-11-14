"""Record the demo as a silent video with captions: the fallback for the stage (#295).

    python -m demo.record_demo                      # records, approves nothing
    python -m demo.record_demo --approve            # also takes the confirmed option and approves it
    python -m demo.record_demo --story offer --approve   # story A: Valio sees it first
    python -m demo.record_demo --story nvidia            # the NVIDIA demo: five Nemotron jobs, approves nothing
    python -m demo.record_demo --base-url https://31-22-104-201.sslip.io --out demo/out
    DEMO_PASSWORD=... python -m demo.record_demo --email approver@kitchen.example   # a site with sign-in on

It drives a real browser through the live site, the way docs/demo.md says. Each step shows a
caption, so the video explains itself without sound. A step that fails is reported and
skipped; the recording goes on. Every deploy restarts the site, so the recorder first waits
until GET /api/ping answers (at most 3 minutes), and a page load that hits a restart waits for
the site again (at most 90 s) and is tried once more.

Three stories (`--story`):

- `milk` (the default): the challenge's request (1,000 L of lactose-free milk), the proposal
  with its reasons, the approval inbox, the option that confirmed stock covers, the activity
  log, the tamper check and the two discovery files.
- `offer` (story A, "Valio sees it first"): the "Offer from Valio Aimo" tile on Home (a
  substitute Valio's selling agent offers before a predicted shortage), "Make a proposal" and
  its approval, the signed receipt of the order, the recall panel, a peanut request that the
  kitchen's allergen rule refuses, the tamper check, the two discovery files and Valio's
  demand view. Without `--approve` it shows the tile and goes on: the receipt step then shows
  the newest order that has a receipt (or is skipped).
- `nvidia` ("One model, five jobs, one buying loop, and it never sets a number"; docs/demo.md
  "NVIDIA demo"): a menu photo read into a plan proposal, the Buyer's proposal for `--text`
  and its "What Nemotron did" panel, Valio's offer tile (only shown), a shelf photo read into
  counts (never saved), a delivery-note photo read against the newest order, the About page
  model usage and the "How we improved its outputs" tables of docs/submission.md. It never
  approves, never accepts the offer and never saves a count; `--approve` is refused. A beat
  whose model did not answer says so in its caption (the parser or a rule answered) or is
  skipped; it never claims Nemotron.

When the site asks for a sign-in (GATEWAY_REQUIRE_LOGIN=true, deploy/README.md), give the
account with `--email`; the password comes from the environment variable DEMO_PASSWORD, never
from an argument, and is never printed. The recorder signs in on the sign-in page before its
first step. `--approve` needs an approver's account.

Needs Playwright with Chromium (`pip install playwright && playwright install chromium`);
it is not a dependency of the app. The video is a .webm file (browsers and VLC play it).

What it writes on the site:

- `milk`: one proposal (one request to the Buyer). With `--approve` it also approves that
  proposal, which records one order in the gateway (nothing is sent to Valio: the challenge
  API has no order endpoint). Without `--approve` nothing is decided.
- `offer`: one refused request ("15 kg peanut butter"; refused before any agent runs, nothing
  can be ordered). With `--approve` it also accepts the open offer, which makes one proposal
  and uses the offer up (a fresh one: `python -m agent.seller --apply --limit 1 --kitchen
  demo-kitchen --days 14` on the server), and approves that proposal: one order. With
  `--press-recall` it runs one recall check ("Check recalls now"); without it the panel is
  only shown.
- `nvidia`: up to two proposals stay WAITING in demo-kitchen: the menu-photo plan proposal
  (only when a matched dish needs an order) and the Buyer's proposal for `--text`. Nothing is
  approved. The photo reads store nothing but one audit entry each. Clear the two proposals
  after the recording with `python -m demo.clear_inbox --apply` on the server (a dry run
  without `--apply` lists them first).
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CAPTION_JS = """
(text) => {
  let bar = document.getElementById('demo-caption');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'demo-caption';
    bar.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:99999;padding:14px 24px;' +
      'background:rgba(15,21,19,.92);color:#fff;font:600 20px/1.35 system-ui,sans-serif;text-align:center';
    document.body.appendChild(bar);
  }
  bar.textContent = text;
}
"""

KITCHEN_ID = "demo-kitchen"               # the web app's default kitchen (VITE_GATEWAY_KITCHEN_ID)
OFFER_SUPPLIER = "Valio Aimo"
REFUSED_TEXT = "15 kg peanut butter"      # the demo kitchen excludes peanuts

# The newest order with a signed receipt, read the way the web app reads it (same origin, the
# web server adds the gateway token). None in mock mode (no gateway) or on any error.
NEWEST_RECEIPT_JS = """
async (path) => {
  try {
    const answer = await fetch(path, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    if (!answer.ok) return null;
    const body = await answer.json();
    const rows = Array.isArray(body) ? body : (body.orders || []);
    const row = rows.find((order) => order && order.receipt);
    return row ? String(row.order_id) : null;
  } catch (error) {
    return null;
  }
}
"""

SET_VALIO_ROLE_JS = "() => { try { localStorage.setItem('purchasing-role', 'valio_planner'); } catch (e) {} }"


def next_monday(today: date) -> date:
    """The Monday after today; a Monday itself gives the one a week later."""
    return today + timedelta(days=(7 - today.weekday()) or 7)


def site_needs_sign_in(base: str, opener=urllib.request.urlopen) -> bool:
    """True when the site has sign-in switched on: its session check answers 401 to a visitor.
    Any other answer, or no answer, is False: the recording itself then shows what is wrong."""
    request = urllib.request.Request(base + "/api/v1/me", headers={"User-Agent": "record-demo/0.1"})
    try:
        with opener(request, timeout=20):
            return False
    except urllib.error.HTTPError as error:
        return error.code == 401
    except OSError:
        return False


SITE_DOWN = ("the site does not answer; a deploy may be running: look at GitHub Actions, deploy "
             "(every deploy restarts the site), then run the recorder again")

# A goto that fails like this hit a site restart or a network blip (2026-11-14: a DNS blip, then
# Chrome's error page reloading by itself; six deploys in 7 minutes): worth one more try.
RETRYABLE_GOTO = ("net::ERR_", "interrupted by another navigation", "Execution context was destroyed")


def site_answers(base: str, opener=urllib.request.urlopen) -> bool:
    """True when GET <base>/api/ping answers 200. Any other answer, or no answer, is False."""
    request = urllib.request.Request(base + "/api/ping", headers={"User-Agent": "record-demo/0.1"})
    try:
        with opener(request, timeout=10) as answer:
            return getattr(answer, "status", 200) == 200
    except OSError:          # HTTPError, URLError and a refused connection are all OSErrors
        return False


def wait_for_site(base: str, limit: float = 180, every: float = 5, answers=None, sleep=None, clock=None,
                  say=print, waiting: str = "waiting for the site to answer") -> bool:
    """Polls /api/ping every `every` seconds for at most `limit` seconds. True once it answers 200;
    False when it never did. Says one line per failed poll, so a pause is never silent."""
    answers = answers or site_answers      # looked up per call, so a test can swap it
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    started = clock()
    while True:
        if answers(base):
            return True
        waited = clock() - started
        if waited + every > limit:
            return False
        say(f"      {waiting} ({base}/api/ping, {waited:.0f} of {limit:.0f} s)")
        sleep(every)


def goto(page, url: str):
    """The page goto, with one retry after a site restart: on a net::ERR_* failure, an interrupted
    navigation or a destroyed execution context it waits until the site answers (at most 90 s)
    and tries the same goto once more. Any other error, and a second failure, propagate."""
    try:
        return page.goto(url)
    except Exception as error:
        if not any(mark in str(error) for mark in RETRYABLE_GOTO):
            raise
    parts = urllib.parse.urlsplit(url)
    wait_for_site(f"{parts.scheme}://{parts.netloc}", limit=90, every=5,
                  waiting="site restarting (deploy?), waiting")
    return page.goto(url)


def sign_in(page, base: str, email: str, password: str) -> bool:
    """Signs in on the site's sign-in page. False when the site shows no sign-in page (the open
    demo sends a visitor on to Home). Raises when the site refuses: every later step would
    only record the sign-in page."""
    goto(page, base + "/sign-in")
    form = page.get_by_label("Password")
    try:
        form.wait_for(timeout=10_000)
    except Exception:
        return False
    page.get_by_label("Email").fill(email)
    form.fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()
    try:
        form.wait_for(state="detached", timeout=20_000)
    except Exception:
        alert = page.get_by_role("alert")
        reason = alert.first.inner_text().strip() if alert.count() else "the sign-in page did not go away"
        raise RuntimeError(f"sign-in as {email} failed: {reason}") from None
    return True


def approve_in(page, cards, what: str) -> None:
    """Approve inside `cards` only, never a button of another card.

    A proposal with unconfirmed stock has no Approve button a person can press: its
    "Choose option" button takes the option that confirmed stock covers and opens the
    same dialog. That button comes first; a plain Approve is the other case.
    The inbox shows the options folded: "Choose option" exists only after "Option A" is
    opened, so a folded "Option A" is opened first.
    """

    def enabled(name):
        return [b for b in cards.get_by_role("button", name=name, exact=False).all() if b.is_enabled()]

    buttons = enabled("Choose option")
    if not buttons:
        for header in enabled("Option A"):
            if header.get_attribute("aria-expanded") == "false":
                header.scroll_into_view_if_needed()
                header.click()
                page.wait_for_timeout(600)
        buttons = enabled("Choose option")
    buttons = buttons or enabled("Approve")
    if not buttons:
        raise RuntimeError(f"no proposal for {what} in the inbox can be approved")
    buttons[0].scroll_into_view_if_needed()
    page.wait_for_timeout(1200)
    buttons[0].click()
    page.get_by_role("dialog").get_by_role("button", name="Yes, approve", exact=False).click()
    page.wait_for_timeout(3500)


def offer_title(product: str | None) -> re.Pattern:
    """The inbox title of the proposal made from the offer (gateway/supplier_offers.py `accept`):
    "Offer from Valio Aimo: <product> in place of <product>". With the product read from the
    Home tile only that offer's card matches."""
    head = f"Offer from {OFFER_SUPPLIER}"
    if product and product.strip():
        return re.compile("^" + re.escape(f"{head}: {product.strip()} in place of "))
    return re.compile("^" + re.escape(head) + "\\b")


def _ask(page, base: str, text: str, needed_by: str) -> None:
    goto(page, base + "/requests")
    page.get_by_label("What do you need?").fill(text)
    for label, value in (("Covers", "180"), ("Needed by", needed_by)):
        field = page.get_by_label(label)
        if field.count():
            field.first.fill(value)
    page.wait_for_timeout(1200)
    page.get_by_role("button", name="Ask the agent").click()


def _common(base: str) -> dict:
    """Steps both stories share: the tamper check and the two discovery files."""

    def tamper(page):
        goto(page, base + "/trust")
        page.get_by_role("button", name="Verify audit chain").click()
        page.wait_for_timeout(3000)

    def llms(page):
        goto(page, base + "/llms.txt")
        page.wait_for_timeout(3500)

    def card(page):
        goto(page, base + "/.well-known/agent-card.json")
        page.wait_for_timeout(3000)

    return {
        "tamper": ("Tamper check: change one line of the log and the chain breaks.", tamper),
        "llms": ("Open to any agent: /llms.txt tells an agent how to search, get an offer and propose.", llms),
        "card": ("The agent card lists the skills. Approval is not one of them.", card),
    }


def steps(base: str, text: str, needed_by: str, approve: bool, story: str = "milk",
          press_recall: bool = False, photos: dict | None = None) -> list[tuple[str, str, object]]:
    """`(name, caption, action)`; an action takes the page and may raise. An action that returns
    a string replaces its caption with it (a beat whose model did not answer says so)."""
    if story == "offer":
        return offer_steps(base, needed_by, approve, press_recall)
    if story == "nvidia":
        return nvidia_steps(base, text, needed_by, photos)
    if story != "milk":
        raise ValueError(f"unknown story {story!r}")
    common = _common(base)

    def home(page):
        goto(page, base + "/")
        page.wait_for_timeout(1500)

    def ask(page):
        _ask(page, base, text, needed_by)

    def proposal(page):
        page.get_by_text("Why this basket", exact=False).first.wait_for(timeout=120_000)
        page.wait_for_timeout(2500)
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(3000)

    def inbox(page):
        goto(page, base + "/approvals")
        page.wait_for_timeout(3500)

    def decide(page):
        """Approve only the proposal for `text`, never another one in the inbox.

        Matching rule: an inbox card's title is the request text (trimmed by the gateway),
        so only a button inside a card whose title is exactly `text.strip()` counts.
        """
        cards = page.locator('[data-slot="card"]').filter(has=page.get_by_text(text.strip(), exact=True))
        approve_in(page, cards, f'"{text.strip()}"')

    def log(page):
        goto(page, base + "/audit")
        page.wait_for_timeout(3500)

    plan = [
        ("home", "Kitchen Buyer: a purchasing agent for a professional kitchen, on Valio Aimo's catalog.", home),
        ("ask", f'A chef asks in plain words: "{text}". No product codes.', ask),
        ("proposal", "The Buyer agent checks live Valio prices, stock and cut-offs. The engine sets every number "
                     "and says why.", proposal),
        ("inbox", "Nothing is ordered yet. Every proposal waits for a person.", inbox),
    ]
    if approve:
        plan.append(("approve", "A person takes the option Valio's stock confirms and approves its exact total. "
                                "The agent has no approve tool.", decide))
    plan += [
        ("log", "Every step is written to a hash-chained activity log.", log),
        *((name, *common[name]) for name in ("tamper", "llms", "card")),
    ]
    return plan


def offer_steps(base: str, needed_by: str, approve: bool, press_recall: bool) -> list[tuple[str, str, object]]:
    """Story A, "Valio sees it first". `seen` carries the offered product from the Home tile to
    the approve step, so only the card made from this offer is approved."""
    common = _common(base)
    seen: dict[str, str] = {}

    def tile(page):
        return page.locator('[aria-labelledby="supplier-offer-title"]')

    def offer(page):
        goto(page, base + "/")
        box = tile(page)
        box.wait_for(timeout=15_000)
        box.scroll_into_view_if_needed()
        name = box.locator("p.font-semibold")
        if name.count():
            seen["product"] = name.first.inner_text().strip()
        page.wait_for_timeout(1500)

    def accept(page):
        box = tile(page)
        if not box.count():
            goto(page, base + "/")
            box.wait_for(timeout=15_000)
        box.get_by_role("button", name="Make a proposal", exact=True).click()
        try:
            page.wait_for_url(re.compile(r"/approvals"), timeout=60_000)
        except Exception:
            status = box.get_by_role("status")
            reason = status.first.inner_text().strip() if status.count() else ""
            raise RuntimeError(f"the offer made no proposal: {reason or 'the page did not go to the inbox'}") from None
        page.wait_for_timeout(3000)

    def decide(page):
        if "/approvals" not in page.url:
            goto(page, base + "/approvals")
        title = offer_title(seen.get("product"))
        page.get_by_text(title).first.wait_for(timeout=20_000)
        cards = page.locator('[data-slot="card"]').filter(has=page.get_by_text(title))
        found = cards.count()
        if found != 1:      # two offer cards for one product: a person picks, not the recorder
            raise RuntimeError(f"{found} inbox cards match {title.pattern!r}; expected exactly one")
        approve_in(page, cards, f"the offer ({title.pattern})")

    def receipt(page):
        goto(page, base + "/orders")
        page.wait_for_timeout(1500)
        order_id = page.evaluate(NEWEST_RECEIPT_JS, f"/api/v1/kitchens/{KITCHEN_ID}/orders")
        if order_id:
            goto(page, f"{base}/orders/{order_id}")
        else:               # no gateway answer (mock mode): the newest order in the list
            link = page.locator('a[href^="/orders/"]')
            link.first.wait_for(timeout=15_000)
            link.first.click()
        heading = page.get_by_role("heading", name="Signed receipt", exact=True)
        heading.wait_for(timeout=20_000)
        if not page.get_by_text("Signed by the gateway", exact=False).count():
            raise RuntimeError("no order with a signed receipt")
        heading.scroll_into_view_if_needed()
        page.wait_for_timeout(1500)

    def recall(page):
        goto(page, base + "/approvals")
        panel = page.get_by_role("region", name="Food recalls")
        panel.wait_for(timeout=20_000)
        panel.scroll_into_view_if_needed()
        if press_recall:
            panel.get_by_role("button", name="Check recalls now", exact=True).click()
            page.wait_for_timeout(800)
            panel.get_by_role("button", name="Check recalls now", exact=True).wait_for(timeout=120_000)
            panel.scroll_into_view_if_needed()
        page.wait_for_timeout(2000)

    def refuse(page):
        _ask(page, base, REFUSED_TEXT, needed_by)
        answer = page.get_by_role("status", name="Nothing can be ordered")
        answer.wait_for(timeout=60_000)
        answer.evaluate("(el) => el.scrollIntoView({ block: 'center' })")   # clear of the caption bar
        page.wait_for_timeout(1500)

    def demand(page):
        page.evaluate(SET_VALIO_ROLE_JS)          # this browser only: the Valio side of the app
        goto(page, base + "/demand")
        page.get_by_role("heading", name="Demand", exact=True).wait_for(timeout=20_000)
        page.wait_for_timeout(3500)

    plan = [
        ("offer", "Valio's selling agent sees a shortage coming and offers this kitchen a substitute. No price "
                  "and no quantity come from the supplier: the amount is the kitchen's own forecast.", offer),
    ]
    if approve:
        plan += [
            ("accept", "A person turns the suggestion into a normal proposal. It still waits for approval.", accept),
            ("approve", "The person approves the exact total. The agent cannot approve.", decide),
        ]
    plan += [
        ("receipt", "Every order gets a receipt signed by the gateway. Anyone can check it with the public key.",
         receipt),
        ("recall", "Context.dev reads the Finnish Food Authority recall list. The recalled coffee is on this "
                   "kitchen's shelf.", recall),
        ("refuse", "This kitchen excludes peanuts: the request is refused in under a second, and no other "
                   "product is swapped in.", refuse),
        *((name, *common[name]) for name in ("tamper", "llms", "card")),
        ("demand", "Valio sees the predicted demand of kitchens that share their forecast, and the lines that "
                   "will be short.", demand),
    ]
    return plan


REPO = Path(__file__).resolve().parents[1]
NVIDIA_SENTENCE = "One model, five jobs, one buying loop, and it never sets a number."
DEFAULT_PHOTOS = {
    "menu": REPO / "demo" / "menu-photo.png",                       # demo/menu-photo.md
    "shelf": REPO / "agent" / "fixtures" / "shelf" / "demo-shelf.png",  # docs/demo.md "Photo beat"
    "note": None,                                                   # the prepared note comes with #1198
}
# Buttons the NVIDIA story must never press: each one decides, orders or writes stock.
NEVER_PRESSED = ("Approve", "Yes, approve", "Choose option", "Make a proposal", "Save count", "Save week",
                 "Propose order for this week", "Yes, received")
TRACE_TITLE = "What Nemotron did"          # the panel of #1197

NEWEST_ORDER_JS = """
async (path) => {
  try {
    const answer = await fetch(path, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    if (!answer.ok) return null;
    const body = await answer.json();
    const rows = Array.isArray(body) ? body : (body.orders || []);
    return rows.length && rows[0] && rows[0].order_id ? String(rows[0].order_id) : null;
  } catch (error) {
    return null;
  }
}
"""


def iso_week(day: str) -> str:
    """`2026-11-16` -> `2026-W47`, the Planner's `week` value."""
    year, week, _ = date.fromisoformat(day).isocalendar()
    return f"{year}-W{week:02d}"


def improved_tables(submission: Path | None = None) -> list[list[list[str]]]:
    """The tables of "How we improved its outputs" in docs/submission.md, as rows of cells.
    Read from the file at run time, so the video shows the measured numbers, never a copy."""
    source = (submission or REPO / "docs" / "submission.md").read_text(encoding="utf-8")
    start = source.find("**How we improved its outputs.**")
    if start < 0:
        raise RuntimeError("docs/submission.md has no 'How we improved its outputs' part")
    # The part ends where the next paragraph opens with a bold heading (#1722): a later
    # part with its own table is not an "improved" table.
    end = source.find("\n**", start)
    tables, current = [], []
    for line in source[start:end if end > 0 else None].splitlines():
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if not all(set(cell) <= set("-: ") for cell in cells):       # the |---| line
                current.append(cells)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    if not tables:
        raise RuntimeError("no table under 'How we improved its outputs' in docs/submission.md")
    return tables


def improved_html(tables: list[list[list[str]]]) -> str:
    import html
    parts = ["<!doctype html><meta charset='utf-8'><body style='margin:0;padding:32px 40px 120px;"
             "font:16px/1.4 system-ui,sans-serif;background:#fff;color:#0f1513'>",
             "<h1 style='font-size:24px;margin:0 0 4px'>How we improved its outputs</h1>",
             "<p style='margin:0 0 20px;color:#555'>Measured, from docs/submission.md "
             "(NVIDIA: Best Use of Nemotron)</p>"]
    for table in tables:
        parts.append("<table style='border-collapse:collapse;margin:0 0 24px'>")
        for index, row in enumerate(table):
            tag = "th" if index == 0 else "td"
            cells = "".join(f"<{tag} style='border:1px solid #ccd;padding:6px 10px;text-align:left'>"
                            f"{html.escape(cell)}</{tag}>" for cell in row)
            parts.append(f"<tr>{cells}</tr>")
        parts.append("</table>")
    return "".join(parts) + "</body>"


def _photo(photos: dict, key: str, issue: str | None = None) -> Path:
    path = photos.get(key)
    if path is None:
        raise RuntimeError(f"after #{issue}: no prepared {key} photo yet (pass --{key}-photo)" if issue
                           else f"no {key} photo given")
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"the {key} photo {path} is not there")
    return path


def _read_photo(page, section: str, input_label: str, photo: Path, busy: str, timeout: int = 120_000) -> None:
    """Gives `photo` to the hidden file input of `section` and waits until the model's answer
    (or the page's error) shows. An error raises with the page's own words: the beat is skipped,
    it never claims a reading the model did not make."""
    box = page.locator(section)
    box.wait_for(timeout=20_000)
    box.scroll_into_view_if_needed()
    box.locator(f'input[type="file"][aria-label="{input_label}"]').set_input_files(str(photo))
    page.wait_for_timeout(800)
    box.get_by_text(busy, exact=False).wait_for(state="detached", timeout=timeout)
    alert = box.get_by_role("alert")
    if alert.count():
        raise RuntimeError(f"the model did not answer: {alert.first.inner_text().strip()[:90]}")
    page.wait_for_timeout(1500)


def nvidia_steps(base: str, text: str, needed_by: str, photos: dict | None) -> list[tuple[str, str, object]]:
    """The NVIDIA demo (docs/demo.md "NVIDIA demo"). Never approves, never accepts the offer,
    never saves a count: the plan has no such step and no action presses a NEVER_PRESSED button."""
    photos = {**DEFAULT_PHOTOS, **(photos or {})}

    def intro(page):
        goto(page, base + "/")
        page.wait_for_timeout(1500)

    def plan(page):
        goto(page, f"{base}/planner?week={iso_week(needed_by)}")
        _read_photo(page, '[aria-labelledby="menu-photo-title"]', "Choose a photo of the menu",
                    _photo(photos, "menu"), "is reading the menu")

    def buy(page):
        _ask(page, base, text, needed_by)
        page.get_by_text("Why this basket", exact=False).first.wait_for(timeout=120_000)
        page.wait_for_timeout(2000)
        if page.get_by_text("request parser", exact=False).count():
            return ("The Buyer model did not answer, so the gateway's request parser made this proposal. "
                    "The engine still set every number. This beat is not Nemotron.")
        return None

    def trace(page):
        found = page.get_by_text(TRACE_TITLE, exact=False)
        if not found.count():
            raise RuntimeError(f"after #1197: no '{TRACE_TITLE}' panel on this proposal")
        found.first.scroll_into_view_if_needed()
        found.first.click()
        page.wait_for_timeout(2500)

    def sell(page):
        goto(page, base + "/")
        box = page.locator('[aria-labelledby="supplier-offer-title"]')
        box.wait_for(timeout=15_000)
        box.scroll_into_view_if_needed()
        page.wait_for_timeout(1500)
        if box.get_by_text("picked by rule", exact=False).count():
            return ("Valio's offer: a rule picked this substitute, not a model (the model did not answer "
                    "when the offer was made). No price and no quantity come from the supplier.")
        return None

    def count(page):
        goto(page, base + "/stock")
        _read_photo(page, '[aria-labelledby="shelf-photo-title"]', "Choose a photo of the shelf",
                    _photo(photos, "shelf"), "is reading the photo")

    def receive(page):
        photo = _photo(photos, "note", issue="1198")
        order_id = page.evaluate(NEWEST_ORDER_JS, f"/api/v1/kitchens/{KITCHEN_ID}/orders")
        if not order_id:
            raise RuntimeError("no order to check a delivery note against")
        goto(page, f"{base}/orders/{order_id}")
        _read_photo(page, '[aria-labelledby="delivery-note-title"]', "Choose a delivery note photo",
                    photo, "Reading the delivery note")

    def numbers(page):
        goto(page, base + "/about")
        heading = page.locator("#about-model")
        heading.wait_for(timeout=20_000)
        heading.scroll_into_view_if_needed()
        page.wait_for_timeout(2500)

    def improved(page):
        page.set_content(improved_html(improved_tables()))
        page.wait_for_timeout(2500)

    return [
        ("intro", f"{NVIDIA_SENTENCE} Nemotron 3.5 Super VL on Verda.", intro),
        ("plan", "Plan: Nemotron VL reads a photo of next week's menu and matches each dish to a recipe. "
                 "The engine sizes the order; the proposal waits for a person.", plan),
        ("buy", "Buy: Nemotron picks catalog products from a shortlist in one call; code runs the audited "
                "MCP tools. The engine sets every quantity and price.", buy),
        ("trace", "The trace: Nemotron's one pick, then each audited tool call the code made, in order. "
                  "There is no approve tool.", trace),
        ("sell", "Sell: Valio's own selling agent, also Nemotron, picks a substitute before a shortage. "
                 "The amount is the kitchen's own forecast.", sell),
        ("count", "Count: Nemotron VL counts the shelf. Unknown is never zero: the hidden pack says "
                  "'please count'. Nothing is saved until a person presses Save.", count),
        ("receive", "Receive: Nemotron VL reads the delivery note. Plain code compares it with the order "
                    "and finds the short and missing lines.", receive),
        ("numbers", "Measured, not claimed: the Buyer's model calls, tokens and seconds for this kitchen, "
                    "counted from each run.", numbers),
        ("improved", "We measured first: thinking on where the model decides numbers, off where the engine "
                     "does. It never sets a number.", improved),
    ]


def record(base: str, out: Path, text: str, needed_by: str, approve: bool, pause: float,
           email: str | None = None, password: str | None = None, story: str = "milk",
           press_recall: bool = False, photos: dict | None = None) -> Path:
    from playwright.sync_api import sync_playwright   # optional tool, not an app dependency

    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 720},
                                      record_video_dir=str(out),
                                      record_video_size={"width": 1280, "height": 720})
        page = context.new_page()
        if email:
            try:
                asked = sign_in(page, base, email, password or "")
            except Exception:
                context.close()
                browser.close()
                raise
            if asked:
                page.evaluate(CAPTION_JS, "A person signs in. Only an approver's account can approve an order.")
                page.wait_for_timeout(int(pause * 1000))
            print(f"ok    {'sign-in':9}" if asked else "      sign-in   the site is open: it asked for no sign-in")
        for name, caption, action in steps(base, text, needed_by, approve, story, press_recall, photos):
            started = time.time()
            try:
                said = action(page)
                page.evaluate(CAPTION_JS, said if isinstance(said, str) and said.strip() else caption)
                page.wait_for_timeout(int(pause * 1000))
                print(f"ok    {name:9} {time.time() - started:5.1f} s")
            except Exception as error:   # a failed step must not lose the recording
                print(f"SKIP  {name:9} {str(error).splitlines()[0][:110]}")
        video = page.video
        context.close()          # the file is complete only after the context closes
        browser.close()
        return Path(video.path())


def sign_in_problem(email: str | None, password: str | None, needs_sign_in) -> str | None:
    """Why the recording cannot start, or None. `needs_sign_in` is asked only without an email."""
    if email and not password:
        return "--email needs the password in the environment variable DEMO_PASSWORD (never as an argument)"
    if not email and needs_sign_in():
        return ("this site asks for a sign-in: pass --email <account> and put its password in the "
                "environment variable DEMO_PASSWORD")
    return None


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="https://31-22-104-201.sslip.io")
    parser.add_argument("--out", default="demo/out", help="folder for the .webm file (git-ignored)")
    parser.add_argument("--story", choices=("milk", "offer", "nvidia"), default="milk",
                        help="milk: the 1,000 L request (default); offer: story A, Valio's offer first; "
                             "nvidia: five Nemotron jobs, approves nothing (--approve is refused). It leaves "
                             "up to two WAITING proposals in demo-kitchen (the menu-photo plan and the "
                             "Buyer's proposal for --text); clear them with python -m demo.clear_inbox --apply")
    parser.add_argument("--menu-photo", default=str(DEFAULT_PHOTOS["menu"]), help="--story nvidia: the menu photo")
    parser.add_argument("--shelf-photo", default=str(DEFAULT_PHOTOS["shelf"]), help="--story nvidia: the shelf photo")
    parser.add_argument("--note-photo", default=None,
                        help="--story nvidia: the delivery-note photo (the prepared one comes with #1198); "
                             "without it the receive beat is skipped")
    parser.add_argument("--text", default="1,000 L lactose-free milk by Monday", help="the milk story's request")
    parser.add_argument("--date", default=next_monday(date.today()).isoformat(),
                        help="needed-by date; pick one whose order cut-offs are still open")
    parser.add_argument("--approve", action="store_true",
                        help="also approve the proposal (records one order); with --story offer it also "
                             "accepts the open offer, which uses it up")
    parser.add_argument("--press-recall", action="store_true",
                        help="--story offer: press 'Check recalls now' (one recall check); else only show the panel")
    parser.add_argument("--pause", type=float, default=4.0, help="seconds each caption stays")
    parser.add_argument("--email", default=None,
                        help="sign in as this account first (a site with sign-in on); "
                             "the password is read from the environment variable DEMO_PASSWORD")
    args = parser.parse_args(argv)
    if args.story == "nvidia" and (args.approve or args.press_recall):
        sys.exit("--story nvidia never approves and never runs a recall check: drop --approve and --press-recall")
    base = args.base_url.rstrip("/")
    photos = {"menu": args.menu_photo, "shelf": args.shelf_photo, "note": args.note_photo}
    password = os.environ.get("DEMO_PASSWORD") or None
    if not wait_for_site(base, limit=180, every=5):     # a deploy restarts the site: wait for it first
        sys.exit(SITE_DOWN)
    problem = sign_in_problem(args.email, password, lambda: site_needs_sign_in(base))
    if problem:
        sys.exit(problem)
    try:
        path = record(base, Path(args.out), args.text, args.date, args.approve, args.pause,
                      email=args.email, password=password, story=args.story, press_recall=args.press_recall, photos=photos)
    except ImportError:
        sys.exit("Playwright is not installed: pip install playwright && playwright install chromium")
    except RuntimeError as error:      # the sign-in was refused: nothing useful can be recorded
        sys.exit(str(error))
    print(f"video: {path}")


if __name__ == "__main__":
    main()
