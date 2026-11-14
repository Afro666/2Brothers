# Codex session notes from Maciek's conversation

These are exact user prompts visible in this session, not reconstructed detailed
prompts. The selected issue text and preceding conversation supplied the detail.

| Exact prompt | Selected scope | Implementation evidence |
|---|---|---|
| `Finish those tasks` | #170, #358, #364, #368, #376 | #436, #455, #476, #493; the scope also included review/decision work |
| `Go on` | #443, #459, #447 | #527, #536, #539; contract and implementation were separate PRs |
| `go on` | #433, #548, #731 | #1031: reviewed/fixed the local forecast work and reran its backtest. #1029 and #1030 were merged by Claude while this session ran; Codex reviewed/tested them rather than claiming their implementation |

The last row is a useful limit on attribution: being assigned an issue does not
mean Codex wrote every merged change. #433 also began as local work by another
agent; this session supplied review fixes, validation and the PR.

## Model routing

The historical implementation episodes reported by this OpenAI-hosted Codex
session did not invoke Kimi or DeepSeek as coding workers. That statement does
not establish an exact historical model ID, nor validate every PR in the
repository's author/trailer heuristic. No contemporaneous per-PR model ledger is
available for the entire 42-PR list, so we do not certify that list from memory.
Claude handoffs, including the final rebase for #85/#87, remain Claude's work.

The new #372 CLI experiment explicitly selected **`gpt-6.1-sol`** with ChatGPT
browser login. Its first failed configuration selected `gpt-5.4`, unsupported by
that login; this must not be hidden. The CI reviewer uses the separately billed
OpenAI API and defaults to **`gpt-5.4`**, configurable through
`CODEX_REVIEW_MODEL`. These are different authentication paths.

## Mistakes and how they were found

- The label/recall implementation passed source-tree tests while its modules and
  fixture data were absent from the deployed image. Codex's live smoke check saw
  the label endpoint fail with HTTP 500. #503 fixed packaging and added an image
  smoke check. A source-tree test pass had been insufficient evidence of deployment.
- The label evidence page used the Hyvää Suomesta heading for unsupported schemes.
  Codex reported and fixed the misleading heading in #514, with a regression test.
  Unsupported evidence stayed unknown. The retained handoff does not identify
  who first noticed the heading, so we do not assign that discovery from memory.

These are the session's reported findings, supported by the linked fixes and the
[original handoff](https://github.com/Afro666/2Brothers/issues/360#issuecomment-6869546826),
not a claim that Opus found them first.

## Timing limits

Historical hands-on coding time and manual comparison times were not measured.
GitHub issue/PR timestamps measure elapsed workflow time, not time spent coding.
We do not manufacture six paired speed-up estimates after the fact. The #372
manifest records a new measurement: 70.7 s for the successful generation and
408.6 s operator-inclusive across four invocations through the live result.

The recording distinguishes generated code from operator review/execution and
the PR merge. No live supplier order or supplier acceptance is claimed.
