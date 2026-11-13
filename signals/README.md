# Kitchen signals

Install with `python -m pip install -e ".[signals,test]"`.

```powershell
python -m signals.weather --kitchen-id demo-helsinki --latitude 60.1699 --longitude 24.9384 --store
python -m unittest discover -s signals/tests -t .
```

One row per kitchen/local day/issue date: the previous 84 completed days and 14
days starting today, in the kitchen's timezone. Finnish public holidays come
from `python-holidays`, using the public category and English names; weekend
and holiday flags are separate. No demand uplift/drop is assumed: these are
features for forecast #33 to learn and validate, not purchasing instructions.

Weather fields are daily max/min temperature (Celsius), precipitation (mm),
and WMO weather code. Null measurements remain null and set
`weather_complete: false`. Bad date windows, units and non-finite values stop
ingestion. Rows include coordinates, issue date, fetch time, units and sources.

Open-Meteo's past data in this endpoint is **archived weather model output**,
not station observations. It is labelled `model_history`; future days are
`forecast`. Do not use today's retrieved history as an as-issued historical
forecast in a backtest. Forecast vintages from distinct issue dates are retained;
`store.signals.list_daily` requires an explicit `as_of` to prevent mixing them.
`fetched_at` records when this snapshot became available to this application.

`signals/out/` JSONL snapshots are ignored by Git. `--store` loads local `.env`
and upserts into `daily_signals` only through `store.signals`, with a unique
`(kitchen_id,date,as_of)` key. Repeat runs on one issue date update that snapshot;
new issue dates retain the old snapshot. Physical weather values use floats;
they are not money. The demo ID is separate from real kitchen records.

Tests read the recorded Helsinki API response and mock network/storage behavior;
they make no live API or MongoDB calls. To collect real data, run the command
above; no Open-Meteo API key is required.

Live verification on 2026-11-13: collected and read back 98 rows for
`demo-helsinki` in MongoDB: 84 historical model days (2026-08-21 through
2026-11-12) and 14 forecast days (2026-11-13 through 2026-11-26).
The recorded test fixture was captured on the same date for Helsinki.

Sources: [Open-Meteo Forecast API](https://open-meteo.com/en/docs) (CC BY 4.0;
attribution: weather data by Open-Meteo),
[python-holidays](https://pypi.org/project/holidays/).

## Finnish seasonal calendar

`finland_seasons.json` contains 11 ingredient records with source URLs, retrieval
date, harvest/catch months, separately sourced peak months, and storage months.
An empty peak/storage list means no period established by these sources, not
that the ingredient cannot be stored. Month boundaries are approximate: a
late-July harvest makes July eligible, not every day in July. Weather, locality,
variety and supplier handling still matter. `peak` describes a regional calendar
peak, not verified freshness of any catalog product.

```python
from datetime import date
from signals.seasons import in_season, season_info, chef_suggestions

in_season("mansikka", date(2026, 7, 15))  # True
season_info("porkkana", date(2026, 12, 1))  # storage, not fresh harvest
chef_suggestions([
    {"product_id": "demo-berry", "names": {"fi": "Mansikka 5kg"}, "country": "FI"}
], date(2026, 7, 15))
```

Lookups accept ingredient strings or `store.products` rows (`names`, `brand`,
`country`, `temperature`, `category`). Matching uses exact English/Finnish/Swedish
aliases after removing known packaging and quality words. Specific textual
categories can match when no name is present; broad categories and numeric
category codes cannot establish an ingredient. Conflicting localized names,
frozen rows, imported products and unmatched names return `None`, which means
unknown, not out of season. Strict matching can miss valid branded or prepared
ingredients; add reviewed aliases rather than broad substring matches.

For fish products, `production_method="wild_caught"` is required. This field is
optional caller enrichment: the current catalog does not establish it. Plain
fish ingredient strings refer to wild-catch season, not farmed fish. Fishing
regulations must be checked separately.

`chef_suggestions` additionally requires explicit Finnish origin. It produces
advisory candidates with `requires_chef_approval=True`; it does not change a
recipe, call purchasing tools or authorize a swap. The caller must still check
stock, price, allergens and culinary suitability with the chef. No cheaper or
fresher claim follows from this calendar. Buyer can call the helper with catalog
rows; it is not wired into the order loop or a new MCP tool.

Sources (each item records its applicable URLs):

- [Satokausi strawberry](https://satokausi.fi/raaka-aineet/mansikka/),
  [carrot](https://satokausi.fi/raaka-aineet/porkkana/), and
  [chanterelle](https://satokausi.fi/raaka-aineet/kantarelli/): harvest/peak/storage periods.
- [Kotipuutarha harvest calendar](https://www.kotipuutarha.fi/sadonkorjuukalenteri/): cabbage and beetroot harvests.
- [Martat potato guide](https://www.martat.fi/wp-content/uploads/2017/05/Martat_peruna2017_lores-Parasta-perunasta-arkeen-ja-juhlaan-vihkonen.pdf): approximate midsummer early-potato harvest.
- Arctic Flavours: [bilberry](https://www.arktisetaromit.fi/en/natural-products/berries/wild-berries/bilberry/),
  [lingonberry](https://www.arktisetaromit.fi/en/natural-products/berries/wild-berries/lingonberry/),
  [chanterelle](https://www.arktisetaromit.fi/en/natural-products/mushrooms/wild-mushrooms/chanterelle/): picking windows.
- [Pro Kala wild-catch calendar](https://prokala.fi/wp-content/uploads/2021/07/kalenteri-printable-3.pdf): perch, burbot and vendace catch seasons.
