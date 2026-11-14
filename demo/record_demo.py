"""Record the demo as a silent video with captions: the fallback for the stage (#295).

    python -m demo.record_demo                      # records, approves nothing
    python -m demo.record_demo --approve            # also takes the confirmed option and approves it
    python -m demo.record_demo --base-url https://31-22-104-201.sslip.io --out demo/out
    DEMO_PASSWORD=... python -m demo.record_demo --email approver@kitchen.example   # a site with sign-in on

It drives a real browser through the live site, the way docs/demo.md says: the challenge's
request (1,000 L of lactose-free milk), the proposal with its reasons, the approval inbox,
the option that confirmed stock covers, the activity log, the tamper check and the two
discovery files. Each step shows a caption,
so the video explains itself without sound. A step that fails is reported and skipped; the
recording goes on.

When the site asks for a sign-in (GATEWAY_REQUIRE_LOGIN=true, deploy/README.md), give the
account with `--email`; the password comes from the environment variable DEMO_PASSWORD, never
from an argument, and is never printed. The recorder signs in on the sign-in page before its
first step. `--approve` needs an approver's account.

Needs Playwright with Chromium (`pip install playwright && playwright install chromium`);
it is not a dependency of the app. The video is a .webm file (browsers and VLC play it).

What it writes on the site: one proposal (one request to the Buyer). With `--approve` it
also approves that proposal, which records one order in the gateway (nothing is sent to
Valio: the challenge API has no order endpoint). Without `--approve` nothing is decided.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
import os
from pathlib import Path
import sys
import time
import urllib.error
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


def sign_in(page, base: str, email: str, password: str) -> bool:
    """Signs in on the site's sign-in page. False when the site shows no sign-in page (the open
    demo sends a visitor on to Home). Raises when the site refuses: every later step would
    only record the sign-in page."""
    page.goto(base + "/sign-in")
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


def steps(base: str, text: str, needed_by: str, approve: bool) -> list[tuple[str, str, object]]:
    """`(name, caption, action)`; an action takes the page and may raise."""

    def home(page):
        page.goto(base + "/")
        page.wait_for_timeout(1500)

    def ask(page):
        page.goto(base + "/requests")
        page.get_by_label("What do you need?").fill(text)
        for label, value in (("Covers", "180"), ("Needed by", needed_by)):
            field = page.get_by_label(label)
            if field.count():
                field.first.fill(value)
        page.wait_for_timeout(1200)
        page.get_by_role("button", name="Ask the agent").click()

    def proposal(page):
        page.get_by_text("Why this basket", exact=False).first.wait_for(timeout=120_000)
        page.wait_for_timeout(2500)
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(3000)

    def inbox(page):
        page.goto(base + "/approvals")
        page.wait_for_timeout(3500)

    def decide(page):
        """Approve only the proposal for `text`, never another one in the inbox.

        Matching rule: an inbox card's title is the request text (trimmed by the gateway),
        so only a button inside a card whose title is exactly `text.strip()` counts.
        A proposal with unconfirmed stock has no Approve button a person can press: its
        "Choose option" button takes the option that confirmed stock covers and opens the
        same dialog. That button comes first; a plain Approve is the other case.
        """
        cards = page.locator('[data-slot="card"]').filter(has=page.get_by_text(text.strip(), exact=True))
        buttons = [b for name in ("Choose option", "Approve")
                   for b in cards.get_by_role("button", name=name, exact=False).all() if b.is_enabled()]
        if not buttons:
            raise RuntimeError(f'no proposal for "{text.strip()}" in the inbox can be approved')
        buttons[0].scroll_into_view_if_needed()
        page.wait_for_timeout(1200)
        buttons[0].click()
        page.get_by_role("dialog").get_by_role("button", name="Yes, approve", exact=False).click()
        page.wait_for_timeout(3500)

    def log(page):
        page.goto(base + "/audit")
        page.wait_for_timeout(3500)

    def tamper(page):
        page.goto(base + "/trust")
        page.get_by_role("button", name="Verify audit chain").click()
        page.wait_for_timeout(3000)

    def llms(page):
        page.goto(base + "/llms.txt")
        page.wait_for_timeout(3500)

    def card(page):
        page.goto(base + "/.well-known/agent-card.json")
        page.wait_for_timeout(3000)

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
        ("tamper", "Tamper check: change one line of the log and the chain breaks.", tamper),
        ("llms", "Open to any agent: /llms.txt tells an agent how to search, get an offer and propose.", llms),
        ("card", "The agent card lists the skills. Approval is not one of them.", card),
    ]
    return plan


def record(base: str, out: Path, text: str, needed_by: str, approve: bool, pause: float,
           email: str | None = None, password: str | None = None) -> Path:
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
        for name, caption, action in steps(base, text, needed_by, approve):
            started = time.time()
            try:
                action(page)
                page.evaluate(CAPTION_JS, caption)
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
    parser.add_argument("--text", default="1,000 L lactose-free milk by Monday")
    parser.add_argument("--date", default=next_monday(date.today()).isoformat(),
                        help="needed-by date; pick one whose order cut-offs are still open")
    parser.add_argument("--approve", action="store_true", help="also approve the proposal (records one order)")
    parser.add_argument("--pause", type=float, default=4.0, help="seconds each caption stays")
    parser.add_argument("--email", default=None,
                        help="sign in as this account first (a site with sign-in on); "
                             "the password is read from the environment variable DEMO_PASSWORD")
    args = parser.parse_args(argv)
    base = args.base_url.rstrip("/")
    password = os.environ.get("DEMO_PASSWORD") or None
    problem = sign_in_problem(args.email, password, lambda: site_needs_sign_in(base))
    if problem:
        sys.exit(problem)
    try:
        path = record(base, Path(args.out), args.text, args.date, args.approve, args.pause,
                      email=args.email, password=password)
    except ImportError:
        sys.exit("Playwright is not installed: pip install playwright && playwright install chromium")
    except RuntimeError as error:      # the sign-in was refused: nothing useful can be recorded
        sys.exit(str(error))
    print(f"video: {path}")


if __name__ == "__main__":
    main()
