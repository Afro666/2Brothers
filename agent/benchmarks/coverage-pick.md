# Optional full-coverage hint (#2021), 15 November 2026

## Shipped candidate: field only, original prompt

The final candidate retains the original `SYSTEM` byte for byte. It adds the
code-computed `covers_need_alone` field only when a quote proves full coverage and
there is no explicit alias match, requested diet or differing observed-order
history. When none of the rows has proven full coverage, no field is added either.
These complex/partial-only inputs remain byte-identical to their original model
input. The code uses the existing gateway diet-word recognizer rather than a new
set of matching rules. This is a conservative opt-in, not a general ranking proof.

The predicate checks confirmed stock against **rounded sales-unit demand**, matching
measure, known timely arrival and an explicitly unpassed cutoff. Values must be
finite and positive where appropriate. Fractional weighted sales units remain
valid. The deterministic guard computes the same proof from evidence; it never
trusts the supplied boolean. Prices, stock and approval are still checked by the
gateway. Adding the field to the pick-cache fingerprint prevents legacy IDs being
reused under a different model input, even though the system prompt is unchanged.

## Final paired trial (v3)

Each pair uses the same request and frozen quote rows. The before arm omits the
hint; the after arm follows the final opt-in rule. Conditions are interleaved in a
seeded order on the same endpoint, with one attempt each, temperature zero and
thinking off. No retries, failures, interrupted attempts, proposals or orders.

| Group | Cases / replies per arm | Raw exact before | Raw exact after | Guarded exact before / after |
|---|---:|---:|---:|---:|
| Known product-name diagnostic | 7 / 21 | 7/21 | 21/21 | 21/21 / 21/21 |
| Previous trial cases (development) | 24 / 24 | 20/24 | 22/24 | 22/24 / 22/24 |
| New valued/permuted validation snapshots | 12 / 24 | 18/24 | 19/24 | 20/24 / 20/24 |

In the original seven-name diagnostic, unnecessary alternatives fell from
**14/21 to 0/21** in this paired trial. This is not the earlier 19/35 diagnostic:
sample size, time and replies differ. The new paired control is reported alongside
the new candidate, not spliced into the earlier report.

Only **39 pairs** actually changed the model input (the rest were intentionally
left alone). Exact raw sets improved **21/39 to 38/39**; the first preference was
correct **39/39 in both arms**. On the new validation subset receiving the hint,
raw exact sets were **6/8 before and 7/8 after**, with correct first preference and
guarded exact sets **8/8 in both arms**. No paired guarded or changed-input
first-choice regressions were observed in this small trial.

The remaining hinted error was `verify-validation-full`, repeat 2: the model kept
the correct confirmed-full pear juice and added a sold-out product. The existing
guard removed it. The hint reduces errors; it does not guarantee perfect model
output. The guard must stay.

Alias/partial and diet/partial snapshot errors also remain in the untouched arms.
The inputs and prompt are identical there, and this change does not claim to fix
them. The adversarial snapshots deliberately include candidates a complete gateway
would filter; this is not evidence of a live dietary or alias guard bypass.

V3 used **138 model calls**, 183,612 prompt and 8,246 completion tokens. These are
selection-model calls only, not end-to-end purchasing timings. Three-candidate
synthetic cases and repetitions are not representative, independent real-world
samples, and the hosted provider does not expose a pinned weights/build ID.

## Rejected candidates are retained

| Trial | Known diagnostic raw exact before / after | What stopped release |
|---|---:|---|
| v1: expanded prompt + hint on every row | 11/21 / 21/21 | An alias/partial probe lost correct first preference, despite no net guarded-set gain |
| v2: stronger alias/diet instructions and eligibility | 9/21 / 21/21 | New validation guarded exact fell 22/24 to 20/24; diet-complement and history-choice regressions |
| v3: original prompt + conservative opt-in | 7/21 / 21/21 | No observed paired guarded or changed-input first-choice regressions; one hinted raw error still needs the guard |

V1/V2 fixtures and reports are immutable historical trials. Their fresh cases
became development data once results informed another candidate. V3's twelve new
validation snapshots were frozen before its calls; they vary values, names and row
order within known policy families. They are not a new real-world accuracy claim.
The older 20-case #2000 holdout and 30-case development reports were not changed.

## Reproduction

`coverage-pick-v{1,2,3}.json` contains each frozen fixture, old system prompt and
call schedule. The corresponding `coverage-pick-v{1,2,3}-report.json` contains raw
and guarded picks, scores, usage, source/fixture/prompt hashes, settings and frozen
commit. V3 additionally stores each model-input hash and whether the input changed.
Canonical fixture hashes permit checks independent of platform line endings;
resume fingerprints describe the exact recorded Windows bytes.

With matching frozen code and privately configured credentials:

```text
python -m agent.coverage_pick_bench --live --out agent/benchmarks/coverage-pick-v3-report.json
```

A matching existing report skips all recorded attempts, even failed/uncertain
ones. Changed inputs refuse to mix. To reproduce v1/v2, use their recorded commit:
the runner's default fixture and implementation changed between candidates.
Provider errors are stored by type only, never response text or credentials.
