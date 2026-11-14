"""Record the demo as a silent video with captions: the fallback for the stage (#295).

    python -m demo.record_demo                      # records, approves nothing
    python -m demo.record_demo --approve            # also approves the small order
    python -m demo.record_demo --base-url https://31-22-104-201.sslip.io --out demo/out

It drives a real browser through the live site, the way docs/demo.md says: a small request
the Buyer can fill from confirmed stock, the proposal with its reasons, the approval inbox,
the activity log, the tamper check and the two discovery files. Each step shows a caption,
so the video explains itself without sound. A step that fails is reported and skipped; the
recording goes on.

Needs Playwright with Chromium (`pip install playwright && playwright install chromium`);
it is not a dependency of the app. The video is a .webm file (browsers and VLC play it).

What it writes on the site: one proposal (one request to the Buyer). With `--approve` it
also approves that proposal, which records one order in the gateway (nothing is sent to
Valio: the challenge API has no order endpoint). Without `--approve` nothing is decided.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import sys
import time

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
        buttons = [b for b in page.get_by_role("button", name="Approve", exact=False).all() if b.is_enabled()]
        if not buttons:
            raise RuntimeError("no proposal in the inbox can be approved (unconfirmed stock on each)")
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
        plan.append(("approve", "A person approves the exact total. The agent has no approve tool.", decide))
    plan += [
        ("log", "Every step is written to a hash-chained activity log.", log),
        ("tamper", "Tamper check: change one line of the log and the chain breaks.", tamper),
        ("llms", "Open to any agent: /llms.txt tells an agent how to search, get an offer and propose.", llms),
        ("card", "The agent card lists the skills. Approval is not one of them.", card),
    ]
    return plan


def record(base: str, out: Path, text: str, needed_by: str, approve: bool, pause: float) -> Path:
    from playwright.sync_api import sync_playwright   # optional tool, not an app dependency

    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 720},
                                      record_video_dir=str(out),
                                      record_video_size={"width": 1280, "height": 720})
        page = context.new_page()
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="https://31-22-104-201.sslip.io")
    parser.add_argument("--out", default="demo/out", help="folder for the .webm file (git-ignored)")
    parser.add_argument("--text", default="200 L lactose-free milk by Monday")
    parser.add_argument("--date", default=next_monday(date.today()).isoformat(),
                        help="needed-by date; pick one whose order cut-offs are still open")
    parser.add_argument("--approve", action="store_true", help="also approve the proposal (records one order)")
    parser.add_argument("--pause", type=float, default=4.0, help="seconds each caption stays")
    args = parser.parse_args()
    try:
        path = record(args.base_url.rstrip("/"), Path(args.out), args.text, args.date, args.approve, args.pause)
    except ImportError:
        sys.exit("Playwright is not installed: pip install playwright && playwright install chromium")
    print(f"video: {path}")


if __name__ == "__main__":
    main()
