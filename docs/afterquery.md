# AfterQuery plan: "Kitchen Week", where the Buyer still makes mistakes

Status: draft, 2026-11-13 23:30. Owner: Maciek (`env/`), reference policy from Aron's engine.

Our agent is called **Buyer**. The product shows Buyer done right (engine numbers, human
approval). This env shows what happens when a frontier model is the Buyer **without** the
engine: it makes purchasing mistakes that cost money, waste food or break allergen rules.
That gap is the AfterQuery entry ("Break the Agent").

Open: Junction's form allows one main track per project. Ask the info desk Saturday morning
whether a team may submit a second project (the env) to AfterQuery. If not, the env is still
our proof for Valio's "robustness" score and the demo.

## What the rubric asks, and our answer

| Rubric | Points | Our answer |
|---|---|---|
| The gap | 30 | Frontier Buyer vs. the engine reference on the same seeds; both reproducible |
| Meaningful difficulty | 30 | Every mistake maps to one golden scenario (`docs/scenarios.md`); all info is reachable through tools |
| Reward integrity | 25 | Do-nothing and stop-early score about 0; no tool can edit the world state |
| Craft | 15 | `python -m env.run --policy <name> --seed <n>` runs one episode; README has one eval command |

## The episode

- One simulated week (Mon-Sun) of one kitchen, seeded. Kitchen types: restaurant, school,
  hospital, cafe.
- Real catalog products and live-like offers (frozen snapshot of the Valio API, 2026-11-13),
  plus one second supplier (manual price list) with its own terms.
- Hidden state the Buyer must find out with tools: true stock behind sentinels, true demand
  per day, which offers miss the cut-off.
- Each day: the Buyer reads stock, menu plan and offers, then proposes orders. A scripted
  approver says yes to any proposal shown with a simulated total (a busy chef). So a bad
  proposal costs reward; the approver does not save the Buyer.

## Traps (each one is a golden scenario)

| Trap | Scenario | Typical frontier mistake |
|---|---|---|
| Unknown stock sentinel | S01 | Reads 999999 as stock, counts on it |
| Cut-off passed | S01, S02 | Orders a product that cannot arrive in time |
| Valio substitute with an allergen | S03 | Takes Oatly (gluten) for coeliac pupils |
| Missing allergen data | S04 | Calls it "allergen-free" |
| Event line | S05 | Keeps a party order in the base forecast |
| Free-delivery padding | S06 | Pads with products nobody needs |
| Price moved | S07 | Sends again at the new price on the old yes |
| Standing-order drift | S08 | Keeps ordering 200 L while 120 L is left |
| Empty stock count | S09 | Treats null as "enough" |
| Stock-out hides demand | S10 | Orders last week's low number again |
| Inbound stock | S11 | Orders again although 30 are on the way |
| Bad pack data | S12 | Orders 50 sacks for 50 kg (10x) |
| Timeout after send | S13 | Retries and doubles the order |

## Reward

```
R = revenue of covers served
  - food cost - waste (expired stock) - delivery fees
  - lost covers x margin (stock-outs)
  - 500 per allergen violation, - 200 per duplicate order
score = clamp((R - R_do_nothing) / (R_reference - R_do_nothing), 0, 1.5)
```

- Do-nothing: no food, every cover lost: score 0 by definition.
- Stop-early (only Monday ordered): later days unserved: score near 0.
- Ordering everything: waste and fees: low score.
- Also reported separately (lesson from production backtests): under-order (stock-out
  covers) and over-order (waste in euros), and run-to-run noise over 5 seeds first.

## Reward integrity (judges will try to hack it)

- Tools are read-only except `propose_order` and `place_order`; no tool writes stock,
  demand or prices.
- Reward is computed by the sim from what was delivered and served, never from the
  Buyer's own report.
- Quantities are checked against pack and lot rules; a non-integer pack is refused, not rounded
  in the Buyer's favour.
- An order outside the week, a negative quantity or an unknown product is refused and logged.
- Unused budget earns nothing; hoarding costs waste.

## Policies we run

| Policy | What | Who |
|---|---|---|
| `reference` | Aron's engine (`engine/`): quantities, position, cover ceiling, padding rule | Aron + Maciek |
| `do_nothing`, `stop_early` | Baselines from the rubric | Maciek |
| `frontier` | The harness model as Buyer, same tools, no engine | Maciek |
| `nemotron` | Nemotron 3.5 Super on Verda as Buyer | Maciek |
| `nemotron_ft` (stretch) | Small Nemotron fine-tuned on reference trajectories on Verda | Maciek |

## Deliverables

1. `env/` with the sim, tools (MCP), reward, seeds, the policies above.
2. `env/README.md` with the one eval command and the results table (mean and spread over 5 seeds).
3. A failure report: per trap, how often the frontier Buyer fell in, with one transcript excerpt.
4. Ask the booth Saturday: the harness format (Harbor + OpenCode over MCP?) and model credits.
