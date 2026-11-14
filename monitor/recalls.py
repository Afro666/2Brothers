"""Food-recall monitor (issue #138).

Watches the Finnish Food Authority (Ruokavirasto) recall list with Context.dev,
reads each new notice's detail page into structured products (name, brand, EAN,
lot or best-before), and matches them against what a kitchen has in stock, uses in
its recipes or has on an open proposal. A match becomes a `recall.alert` (contract:
Webhooks) and an audit entry through `store.audit`.

    python -m monitor.recalls --record monitor/fixtures/ruokavirasto.json   # live, Context.dev credits
    python -m monitor.recalls --fixture monitor/fixtures/ruokavirasto.json --kitchen-type hotel
    python -m monitor.recalls --fixture ... --kitchen-type hotel --audit    # also writes the audit log

Match levels, strongest first. A barcode (EAN/GTIN) equal to one of the product's
pack GTINs is `exact`. Same brand and a shared product word is `possible`: the
kitchen must check the lot or best-before on its packs. A notice without brand and
barcode only matches on product words, as `review`. A notice that names a brand
never matches another brand's product.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

LIST_URL = "https://www.ruokavirasto.fi/elintarvikkeet/ohjeita-kuluttajille/takaisinvedot/"
API = "https://api.context.dev/v1/web/scrape"

LIST_SCHEMA = {"type": "object", "required": ["recalls"], "properties": {"recalls": {
    "type": "array", "items": {"type": "object", "required": ["title", "url"], "properties": {
        "date": {"type": "string", "description": "publication date YYYY-MM-DD"},
        "title": {"type": "string"}, "url": {"type": "string"}}}}}}
DETAIL_SCHEMA = {"type": "object", "required": ["title", "products"], "properties": {
    "date": {"type": "string"}, "title": {"type": "string"},
    "reason": {"type": ["string", "null"]},
    "action": {"type": ["string", "null"], "description": "what businesses or consumers must do"},
    "products": {"type": "array", "items": {"type": "object", "required": ["product_name"], "properties": {
        "product_name": {"type": "string"}, "brand": {"type": ["string", "null"]},
        "company": {"type": ["string", "null"]},
        "gtin": {"type": ["string", "null"], "description": "EAN barcode digits exactly as printed"},
        "package_size": {"type": ["string", "null"]},
        "best_before_or_lot": {"type": ["string", "null"]}}}}}}
NEVER_GUESS = "Use null when a field is not printed on the page. Never guess a barcode."

FI_MONTHS = {m: i for i, m in enumerate(
    "tammikuuta helmikuuta maaliskuuta huhtikuuta toukokuuta kesäkuuta heinäkuuta "
    "elokuuta syyskuuta lokakuuta marraskuuta joulukuuta".split(), 1)}
# Words that say nothing about which product it is.
STOP = {"ja", "tai", "the", "and", "of", "with", "in", "for", "kg", "g", "l", "ml", "dl",
        "pcs", "kpl", "rac", "x", "ulko", "suomi", "finland", "frozen", "pakaste"}


# ---------- fetching (Context.dev) ----------

class ContextDev:
    def __init__(self, key: str | None = None):
        self.key = key or os.environ.get("CONTEXT_DEV_API_KEY") or _dotenv("CONTEXT_DEV_API_KEY")
        if not self.key:
            raise RuntimeError("CONTEXT_DEV_API_KEY is not set")

    def scrape_json(self, url: str, schema: dict, *, attempts: int = 6, timeout: float = 180) -> dict:
        """`attempts=1` with a short `timeout` is one bounded call (the gateway's check now)."""
        body = {"url": url, "formats": {"json": True}, "sharedParams": {"mainContentOnly": True},
                "jsonParams": {"schema": schema, "instructions": NEVER_GUESS},
                "tags": ["recall-monitor"]}
        req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": "Bearer " + self.key, "Content-Type": "application/json",
            "User-Agent": "2brothers-recall-monitor/0.1"})
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.load(r)
                break
            except urllib.error.HTTPError as e:
                # 429 = plan concurrency/rate limit; wait as told, else back off. A GET-like
                # read, so retrying is safe; other 4xx are our mistake and are not retried.
                if (e.code != 429 and e.code < 500) or attempt == attempts - 1:
                    raise RuntimeError(f"Context.dev HTTP {e.code} for {url}") from None
                wait = e.headers.get("Retry-After") if e.headers else None
                time.sleep(float(wait) if wait and wait.replace(".", "", 1).isdigit() else 2 ** (attempt + 1))
        out = data.get("json")
        if isinstance(out, dict) and isinstance(out.get("data"), dict):
            out = out["data"]  # REST wraps the object; the MCP tool does not
        if not isinstance(out, dict):
            raise RuntimeError(f"Context.dev returned no JSON for {url}")
        return out


def _dotenv(name: str) -> str | None:
    for path in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    return None


def record(client: ContextDev, since: date, max_details: int = 15) -> dict:
    """Fetch the list and the detail pages of notices published on or after `since`."""
    listing = client.scrape_json(LIST_URL, LIST_SCHEMA).get("recalls") or []
    notices = []
    for item in listing:
        published = parse_date(item.get("date"))
        if published is None or published < since or len(notices) >= max_details:
            continue
        detail = client.scrape_json(item["url"], DETAIL_SCHEMA)
        notices.append({"url": item["url"], **detail, "date": published.isoformat()})
    return {"source": LIST_URL, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "via": "Context.dev /v1/web/scrape (json)", "notices": notices}


def parse_date(text) -> date | None:
    """'2026-10-09' or '9. lokakuuta 2026' -> date."""
    if not isinstance(text, str):
        return None
    try:
        return date.fromisoformat(text.strip()[:10])
    except ValueError:
        pass
    m = re.match(r"\s*(\d{1,2})\.\s*([a-zäö]+)\s+(\d{4})", text.lower())
    if m and m.group(2) in FI_MONTHS:
        return date(int(m.group(3)), FI_MONTHS[m.group(2)], int(m.group(1)))
    return None


# ---------- matching ----------

def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"[^\w]+", " ", text).strip()


def _words(text: str) -> set:
    return {w for w in _norm(text).split() if len(w) >= 4 and w not in STOP and not w.isdigit()}


def _gtin(value) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.lstrip("0") or None if 8 <= len(digits) <= 14 else None


def _shared(a: set, b: set) -> list:
    """Words in common, counting Finnish compounds ('suodatinkahvi' contains 'kahvi')."""
    out = set()
    for x in a:
        for y in b:
            if x == y or (len(x) >= 5 and x in y) or (len(y) >= 5 and y in x):
                out.add(x if len(x) <= len(y) else y)
    return sorted(out)


def match(notice_product: dict, product: dict):
    """(level, why) when a recalled product may be this catalog product, else None.
    `product` is a store `products` document: names{en,fi,sv}, brand, units[].gtin."""
    gtins = {_gtin(u.get("gtin")) for u in product.get("units") or []} - {None}
    recalled_gtin = _gtin(notice_product.get("gtin"))
    if recalled_gtin and recalled_gtin in gtins:
        return "exact", f"EAN {notice_product['gtin']} is a pack of this product"
    names = " ".join((product.get("names") or {}).values())
    brand = _norm(product.get("brand") or "")
    recalled_brand = _norm(notice_product.get("brand") or "")
    words = _words(names) - _words(brand)
    recalled_words = _words(notice_product.get("product_name") or "") - _words(recalled_brand)
    if recalled_brand:
        if not brand or recalled_brand != brand:
            return None
        common = _shared(words, recalled_words)
        if common:
            return "possible", f"same brand {product['brand']}, shared word(s) {', '.join(common)}"
        return None
    if recalled_gtin:
        return None  # a barcode that is not ours, and no brand to go on
    # No brand, no barcode: only the same kind of product counts. The head noun of our
    # Finnish name (the last real word: 'muna', 'kaurahiutale') must be in a recalled
    # word; adjectives such as 'kanan' or 'täysjyvä' alone are noise.
    head = _head_noun((product.get("names") or {}).get("fi") or "")
    if head and any(head in w for w in recalled_words):
        return "review", f"no brand or barcode in the notice; same kind of product ({head})"
    return None


def _head_noun(name: str) -> str | None:
    words = [w for w in _norm(name).split()
             if len(w) >= 4 and w not in STOP and not any(c.isdigit() for c in w)]
    return words[-1] if words else None


def scan(notices: list, kitchen: dict, now: datetime, lookback_days: int = 365) -> list:
    """Alerts for one kitchen. `kitchen` = {kitchen_id, name, products: [store product
    docs], stock: {pid: (qty, unit)}, recipes: {pid: [recipe]}, proposal: [pid],
    replacements: {pid: [product doc]}}."""
    alerts = []
    oldest = (now - timedelta(days=lookback_days)).date()
    used = set(kitchen.get("stock") or {}) | set(kitchen.get("recipes") or {}) | set(kitchen.get("proposal") or [])
    for notice in notices:
        published = parse_date(notice.get("date"))
        if published is None or published < oldest:
            continue
        for item in notice.get("products") or []:
            for product in kitchen["products"]:
                pid = product["product_id"]
                if pid not in used:
                    continue
                hit = match(item, product)
                if hit is None:
                    continue
                alerts.append(_alert(notice, item, product, hit, kitchen, now))
    return alerts


def _where(pid: str, kitchen: dict) -> list:
    out = []
    if pid in (kitchen.get("stock") or {}):
        qty, unit = kitchen["stock"][pid]
        out.append(f"in stock: {qty:g} {unit}")
    if pid in (kitchen.get("recipes") or {}):
        out.append("in recipes: " + ", ".join(kitchen["recipes"][pid]))
    if pid in (kitchen.get("proposal") or []):
        out.append("on the open purchase proposal")
    return out


def _alert(notice, item, product, hit, kitchen, now) -> dict:
    level, why = hit
    pid = product["product_id"]
    key = f"{notice['url']}|{kitchen['kitchen_id']}|{pid}|{item.get('product_name')}"
    lot = item.get("best_before_or_lot")
    check = (f"Check your packs: only {lot} are recalled." if lot else "Check your packs.")
    step = {"exact": "Stop using it now. " + check,
            "possible": "Do not use it until checked. " + check,
            "review": "A person checks whether this notice is about your product."}[level]
    replacements = [
        {"product_id": r["product_id"], "name": (r.get("names") or {}).get("en"), "brand": r.get("brand")}
        for r in (kitchen.get("replacements") or {}).get(pid, [])[:3]]
    return {
        "event_id": "recall-" + hashlib.sha256(key.encode()).hexdigest()[:24],
        "type": "recall.alert",
        "kitchen_id": kitchen["kitchen_id"],
        "product_id": pid,
        "product_name": (product.get("names") or {}).get("en"),
        "match": level,
        "why": why,
        "where": _where(pid, kitchen),
        "recall": {"url": notice["url"], "date": notice.get("date"), "title": notice.get("title"),
                   "reason": notice.get("reason"), "action": notice.get("action"),
                   "recalled_product": item.get("product_name"), "brand": item.get("brand"),
                   "gtin": item.get("gtin"), "package_size": item.get("package_size"), "lot": lot},
        "next_step": step,
        # The buyer proposes; the chef decides. Nothing is ordered from an alert.
        "replacement_proposal": replacements,
        "detected_at": now.isoformat(timespec="seconds"),
    }


# ---------- output: audit log and webhook ----------

def audit(db, alerts: list, now: datetime) -> list:
    """One audit entry per alert, through the shared repository module. A repeat run
    is an exact replay of the same event_id and appends nothing."""
    from store.audit import append_event  # only store talks to Mongo
    entries = []
    for a in alerts:
        event = {"event_id": a["event_id"], "run_id": "recall-monitor", "type": "recall.alert",
                 "tool": "recall_monitor", "arguments": {"recall_url": a["recall"]["url"],
                                                          "product_id": a["product_id"]},
                 # Snapshot-changing stock/recipes/replacement ideas are not part
                 # of a stable notice event (#238). Proposal effects have own events.
                 "result": {k: a[k] for k in ("type", "kitchen_id", "product_id", "product_name",
                                              "match", "why", "recall", "next_step")}}
        entries.append(append_event(db, event, server={"kitchen_id": a["kitchen_id"],
                                                       "principal": "recall-monitor", "at": now}))
    return entries


def deliver(url: str, alert: dict) -> int:
    """POST one recall.alert webhook. Receivers treat a repeat event_id as a replay."""
    req = urllib.request.Request(url, data=json.dumps(alert).encode(), method="POST", headers={
        "Content-Type": "application/json", "X-Event-Id": alert["event_id"],
        "User-Agent": "2brothers-recall-monitor/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


# ---------- demo kitchen from the Kitchen Week sim ----------

def demo_kitchen(kitchen_type: str, seed: int, catalog_path: Path) -> dict:
    """A Kitchen Week kitchen with its opening stock and recipes; product data from the
    local Valio catalog (vendor/valio, git-ignored) through store.products.flatten."""
    from env.kitchens import RECIPES
    from env.week import KitchenWeek
    from store.products import flatten
    env = KitchenWeek(seed=seed, kitchen_type=kitchen_type)
    obs = env.reset()
    k = env.kitchen
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    docs = {}
    by_category = {}
    for r in raw:
        doc = flatten(r)
        doc["product_id"] = doc.pop("_id")
        docs[doc["product_id"]] = doc
        by_category.setdefault(doc.get("category"), []).append(doc)
    recipes = {}
    for recipe, items in RECIPES.items():
        if any(recipe == m for t in k.type.fixed for m in t[:1]) or recipe in k.type.mains:
            for pid in items:
                recipes.setdefault(pid, []).append(recipe)
    products = [docs[p] for p in k.products if p in docs]
    replacements = {p["product_id"]: sorted(
        (d for d in by_category.get(p.get("category"), [])
         if d["product_id"] != p["product_id"] and d.get("brand") != p.get("brand")),
        key=lambda d: (d.get("names") or {}).get("en") or "") for p in products}
    return {"kitchen_id": k.id, "name": k.name, "products": products,
            "stock": {pid: (s["on_hand"], s["unit"]) for pid, s in obs["stock"].items() if s["on_hand"] > 0},
            "recipes": recipes, "proposal": [], "replacements": replacements}


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Ruokavirasto recall monitor (Context.dev)")
    p.add_argument("--record", type=Path, help="fetch live with Context.dev and save the notices here")
    p.add_argument("--since", type=date.fromisoformat, default=None, help="with --record: oldest notice date")
    p.add_argument("--max-details", type=int, default=15, help="with --record: most detail pages to fetch")
    p.add_argument("--fixture", type=Path, help="recorded notices to scan")
    p.add_argument("--kitchen-type", default="hotel", choices=["restaurant", "hotel", "school", "hospital"])
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--catalog", type=Path, default=Path("vendor/valio/valio_aimo_junction26_product_data.json"))
    p.add_argument("--now", type=datetime.fromisoformat, default=None, help="scan time (default: now)")
    p.add_argument("--audit", action="store_true", help="write alerts to the audit log (MONGODB_URI)")
    p.add_argument("--webhook", help="POST each recall.alert to this URL")
    a = p.parse_args(argv)
    now = a.now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if a.record:
        since = a.since or (now - timedelta(days=365)).date()
        data = record(ContextDev(), since, a.max_details)
        a.record.parent.mkdir(parents=True, exist_ok=True)
        a.record.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"recorded {len(data['notices'])} notices since {since} -> {a.record}")
        if not a.fixture:
            return
    notices = json.loads(a.fixture.read_text(encoding="utf-8"))["notices"]
    kitchen = demo_kitchen(a.kitchen_type, a.seed, a.catalog)
    alerts = scan(notices, kitchen, now)
    print(f"{kitchen['name']} ({kitchen['kitchen_id']}): {len(notices)} notices, {len(alerts)} alert(s)")
    for al in alerts:
        print(f"- [{al['match']}] {al['product_name']} <- {al['recall']['title']} ({al['recall']['date']})")
        print(f"    why: {al['why']}; {'; '.join(al['where'])}")
        print(f"    next: {al['next_step']}")
        for r in al["replacement_proposal"]:
            print(f"    replacement idea: {r['product_id']} {r['name']}")
    if a.audit and alerts:
        from store.db import get_db
        entries = audit(get_db(), alerts, now)
        print(f"audit log: {len(entries)} entr(y/ies), seq {', '.join(str(e['seq']) for e in entries)}")
    if a.webhook:
        for al in alerts:
            print(f"webhook {al['event_id']}: HTTP {deliver(a.webhook, al)}")


if __name__ == "__main__":
    main()
