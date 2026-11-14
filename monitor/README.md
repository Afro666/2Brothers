# monitor: food-recall alerts (#138)

Watches the Finnish Food Authority (Ruokavirasto) recall list with **Context.dev**
(`POST /v1/web/scrape`, JSON format with a schema): the list page, then each new
notice's detail page into products with name, brand, EAN, package size and lot or
best-before. Matches them to what a kitchen has in stock, uses in recipes or has on
an open proposal, and writes a `recall.alert` (contract: Webhooks) plus an audit
entry through `store.audit`. Standard library plus `store`; run from the repo root.

```
# live: list + detail pages, costs Context.dev credits (CONTEXT_DEV_API_KEY)
python -m monitor.recalls --record monitor/fixtures/ruokavirasto.json --since 2026-03-01 --max-details 40
# scan a recording against a Kitchen Week demo kitchen (needs vendor/valio catalog)
python -m monitor.recalls --fixture monitor/fixtures/ruokavirasto.json --kitchen-type hotel --now 2026-11-13T22:00:00
# also append the alerts to the shared audit log (MONGODB_URI); append-only, cannot be undone
python -m monitor.recalls --fixture ... --kitchen-type hotel --audit
python -m unittest discover -s monitor/tests -t .
```

**Match levels.** `exact`: the notice's EAN is one of the product's pack GTINs; stop
using it. `possible`: same brand and a shared product word (Finnish compounds count:
*suodatinkahvi* contains *kahvi*); do not use until the lot is checked. `review`: the
notice has no brand and no EAN, and names the same kind of product (the head noun of
our Finnish name, e.g. *muna*); a person checks. A notice that names a brand never
matches another brand; a foreign EAN without a brand never matches.

**Recorded demo (2026-11-13, 38 notices since 2026-03-01).** "Suodatinkahvissa
vierasesineriski" (6 Mar 2026: Kulta Katriina Perinteinen suodatinkahvi 500 g, metal
pieces, lots best before 23.8.–5.9.2027) gives a `possible` alert for 461332 Kulta
Katriina traditional filter coffee 5 x 1 kg in the hotel, hospital and restaurant
(breakfast buffet / coffee), with the recalled lots and three same-category
replacement ideas from other brands. The egg recalls (Laitilan Kanatarha, Pirkka,
Kotimaista, with EANs) correctly do not match the kitchens' Kieku eggs.

**Alert.** `event_id` (stable per notice, kitchen and product, so a repeat poll is a
replay), `type: recall.alert`, `kitchen_id`, `product_id`, `match`, `why`, `where`
(stock, recipes, proposal), `recall` (url, date, title, reason, action, recalled
product, brand, EAN, pack, lot), `next_step`, `replacement_proposal` (ideas for the
chef; nothing is ordered from an alert). `--webhook URL` POSTs it with `X-Event-Id`.

Context.dev notes: the REST API rejects the MCP-only `responseMode` field; a 429 is
retried with `Retry-After` / backoff.
# Core proposal enforcement (#358)

After recording notices, apply them to actual open proposals in one kitchen:

```powershell
python -m monitor.proposals --fixture monitor/fixtures/ruokavirasto.json --kitchen-id demo-kitchen
```

This writes holds and pending replacement proposals, never orders. It uses
Mongo through `store/`, live Valio quotes through the gateway, and the kitchen's
explicit allergen policy. Exact/possible matches block; review matches warn.
The live approval inbox shows the notice, lot and replacement link. A failed
quote or unknown policy leaves the original held. Repeated polls reuse the
recorded alert and replacement. Holds are conservative and remain until a
human reconciles the affected lot; there is no automatic expiry or release.
An order past the atomic commit point is not cancelled by a later notice.

