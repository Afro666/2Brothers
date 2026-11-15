# Fresh 20-case selection holdout, 15 November 2026 (#2000)

The fixture and runner were committed before live calls (`a23a795`; fixture first
committed in `a1d3f88`). The production prompt, guard and fixture were not tuned
against these replies. Kimi reviewed the oracles before calls; answer-like stock
and diet labels and instructions that restated ranking policy were removed before
freezing. Names and structured evidence, not expected answers, go into the model.

This is a narrow **synthetic selection holdout**: 20 new requests, three candidates
each, six known policy families with fresh combinations. It is not a live-catalog,
whole-Buyer, real-photo or representative real-world accuracy test. All candidates
arrive on time; cutoff failures, large shortlists, candidate permutations and run
stability are not covered. There was one attempt per case, no retries, failures or
interrupted attempts. The hosted endpoint supplies no immutable weights/build ID.

| Selection stage | Exact expected product sets |
|---|---:|
| Raw Nemotron selection | 19/20 |
| Same replies plus the existing reason/full-coverage guard | 20/20 |
| Engine offer sizing alone, before semantic filtering | 8/20 |

The first preference was correct in all 20 replies. All 20 passed the JSON schema
and production numeric-claim reason check; that check is not a proof of every
qualitative claim. Raw and guarded scores reuse the same replies, not independent
model calls. Expected sets require exact equality: extra products fail.

| Family | Cases | Raw exact | Guarded exact | Engine-only exact |
|---|---:|---:|---:|---:|
| Comparable price | 2 | 2 | 2 | 2 |
| Observed prior orders | 2 | 2 | 2 | 0 |
| Product kind | 4 | 4 | 4 | 0 |
| Requested diet claims | 4 | 4 | 4 | 0 |
| Partial coverage and complement | 4 | 4 | 4 | 4 |
| Feedback / alias precedence | 4 | 3 | 4 | 2 |

The raw miss was `feedback-cover`: the model chose the confirmed-full orange juice
and an unnecessary unknown-stock alternative. The existing guard retained only
the first product because the exact quote proved full coverage. This is code's
contribution, not a claim that the raw model made 20 exact choices.

The engine comparator uses the same synthetic offers but **does not run the full
parser's kind, diet or alias filters**. Those candidates would often be filtered
before offer sizing in production. Its 8/20 is not evidence that Nemotron beats the
full parser. The optional offline reference on the original development fixture is
6/30 (`pick-context-v1-engine-reference.json`), one deterministic pass and zero
model calls. Do not compare its denominator with the older 90 model replies as if
they were the same number of independent experiments.

Model round trip: median **0.250 s**, excluding gateway/search/database/approval
work. Usage: **20 calls, 25,869 prompt tokens, 1,149 completion tokens**, thinking
off, temperature zero, at most 512 output tokens. Sequential calls reduce load on
the team's shared endpoint. No proposal, approval, order or stock count was made.

The older **27/90 -> 54/90 -> 69/90** remains development-set evidence. The new
19/20 -> 20/20 must not be presented as a measured improvement over those figures:
the cases, prompt version and repeat counts differ.

## Reproduction and interruption

The JSON report holds per-case picks, scores, timing and provider usage, plus the
fixture SHA-256, source hashes, prompt hash, model/endpoint/settings and frozen
commit. It contains no provider exception text or credentials. Source and fixture
hashes describe the bytes of the recorded Windows checkout; line-ending changes
can legitimately make a different checkout fail the resume fingerprint check.

With the matching frozen source and privately configured `VERDA_INFERENCE_KEY`:

```text
python -m agent.pick_holdout_bench --live --out agent/benchmarks/pick-holdout-20-v1-report.json
```

An existing matching report skips every recorded attempt, including failures and
uncertain interrupted attempts. It does not try again for a better score. A case
is saved as started before network I/O; an interrupted result remains explicit.
Changed inputs/settings refuse to mix with the saved report. A fresh output path
makes new model calls and constitutes a separate run, not a replacement result.

## What remains open

The user confirmed that genuine phone photos are not available yet. The shelf,
menu and delivery-note assets in the repo are prepared images. This evaluation
provides no new vision-accuracy evidence, so #2000 stays open for five to ten real
photos with independent expected text/counts and per-item right/wrong/please-count
results. The old recorded shelf fixture has five COUNTED rows and one UNMATCHED
Edam label; the demo-video run's duplicate butter observation is a different run,
not a ground-truth count or a real-photo accuracy result.
