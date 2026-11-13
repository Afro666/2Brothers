# demo/

Synthetic demo data (#275), built on `env/` (real Valio products and prices).

```
python -m demo.seed --dry-run      # counts only, writes nothing
python -m demo.seed                # loads into MONGODB_URI; safe to run again
```

- 20 kitchens, history from Mon 2026-08-17 up to yesterday; `demo-kitchen` is a hotel.
- 4 weeks ahead: menu plans and the engine's forecast, never actuals.
- Every past week keeps the forecast as made the Monday before, for the engine and for a
  weekday-average baseline, so `GET /v1/kitchens/{k}/forecast-accuracy` can prove it.

Proof on seed 1 (weeks 2026-09-07 to 2026-11-14, weekly error per product):

| | engine (menu x covers x recipe) | weekday average |
|---|---|---|
| demo-kitchen WAPE / bias | 4.4% / +0.1% | 6.7% / +4.5% |
| all 20 kitchens WAPE / bias | 4.7% / -0.2% | 11.4% / +0.8% |
| all 20: under-order / over-order (kitchen units) | 13,354 / 12,347 | 28,663 / 33,032 |
