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
