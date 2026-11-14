# How we used Codex

Evidence for the OpenAI "Best Use of Codex" prize (#360). Every number and every
episode below comes from this repo, its git history or the GitHub API, and names its
source. What only Maciek can supply is in "For Maciek to fill in" at the end.

Snapshot: PRs merged up to 2026-11-14 03:30 UTC. The first PR opened 2026-11-13 18:15 UTC.

## The short version

- Three developers. Maciek is the one who works with OpenAI Codex CLI. He also runs a
  Claude Code session next to it. Aron and Tymon use Claude Code only.
- Codex follows the same rules as every other agent: one issue, one branch, one PR, an
  automatic review on every PR, auto-merge on PASS.
- 42 merged PRs came from Maciek's Codex session: 11% of the 368 merged PRs, 6,478 added
  lines, 40% of them in test files.
- 41 of the 42 passed the first review. The one that did not (#87) broke the
  contract-first rule, and the review stopped it twice.
- Codex also worked as a second reviewer: on #120 it found six failing cases in code that
  a Claude Code session wrote.
- We have no measured speed-up, so we state none.

## How we tell a Codex PR from a Claude Code PR

Maciek opens all his PRs from one GitHub account. Git separates the two agents:

- Claude Code adds a `Co-authored-by: Claude` trailer to its commits. 15 of Maciek's 57
  squash commits on `main` have it. Their PR bodies also end with "Generated with Claude Code".
- The other 42 have no Claude trailer. We count these as Codex.

Check: `git log origin/main --author=Maciej --format='%s | %(trailers:key=Co-authored-by,valueonly,separator=;)'`

Other sources agree with the split:

- `agent/README.md:409`: "Codex implemented #20's upstream adapter, #21's MCP integration
  and this loop using separate issue branches and Opus-reviewed PRs." These are PRs #45,
  #54 and #63, all in the 42.
- Maciek's Codex session lists PRs #436, #455, #476, #493 and #527 as its own in a comment
  on #360 (2026-11-14 01:40 UTC). All five are in the 42.
- Issue #32, comment by Maciek's Claude session: "started (Maciek's Claude session,
  worktree 2Brothers-claude [...]). Codex: I stay inside env/". Its PR #62 has the trailer.

Limit: "no Claude trailer" is strong evidence, not proof. Maciek confirms the list below.

## Numbers

Command: `python docs/codex_metrics.py --until 2026-11-14T03:30:00Z` (it calls `gh api
graphql`; the script documents each rule it applies).

| Who opened the PR | Merged PRs | Lines + | Lines - | Median open to merge (min) | First review PASS | PRs reviewed more than once | PRs with a BLOCK |
|---|---|---|---|---|---|---|---|
| Maciek, Codex | 42 | 6,478 | 200 | 2.7 | 41 of 42 | 13 | 1 (#87) |
| Maciek, Claude Code | 15 | 5,469 | 74 | 1.6 | 15 of 15 | 0 | 0 |
| Aron, Claude Code | 133 | 31,042 | 878 | 1.6 | 132 of 133 | 6 | 1 (#636) |
| Tymon, Claude Code | 69 | 24,117 | 1,885 | 1.7 | 69 of 69 | 6 | 0 |
| Fix bot, Claude | 109 | 2,981 | 377 | 28.8 | 109 of 109 | 18 | 0 |

How to read it:

- "Open to merge" is the time from `gh pr create` to the squash merge. The work is done
  before the PR opens, so this number shows the review and merge step, not the coding time.
- The review verdict is the first line of the bot's PR comment (`Opus review: PASS` or
  `Opus review: BLOCK`, `.github/workflows/ai-review.yml`).
- The review runs again on every push. "Reviewed more than once" means a push came after
  the first review. Codex did this on 13 of 42 PRs: it opens the PR, then pushes tests or
  a fix as separate commits. Example: #455 has three commits and three reviews in 5 minutes.
- Closed, unmerged PRs are not counted.

### Where the Codex PRs landed

| Folder | Codex PRs that touch it | Lines added by Codex |
|---|---|---|
| `gateway/` | 18 | 1,229 |
| `docs/` | 14 | 469 |
| `web/` | 10 | 782 |
| `agent/` | 8 | 1,602 |
| `store/` | 8 | 230 |
| `monitor/` | 4 | 760 |
| `signals/` | 2 | 1,338 |
| `deploy/`, `demo/`, `.github/`, root | 11 | 68 |

2,613 of the 6,478 added lines are in test files (`tests/` folders, `test_*.py`, `*.test.*`).

What Codex built, by PR:

- The Valio client (#45), the MCP tools (#54) and the Nemotron Buyer loop (#63).
- Weather and holiday signals (#183) and the Finnish seasonal calendar (#207).
- The human approval flow from proposal to recorded order (#165, #247, #258, #436, #508, #527).
- Recall holds, replacement baskets and label evidence on top of the recall monitor
  (#455, #476, #493, #539).
- Twelve `docs:` PRs for contracts and decisions (for example #51, #92, #441, #536).

What Codex did not build: `env/` (the Kitchen Week simulator and the benchmark, #62, #70,
#203, #294) and the first version of the recall monitor (#235). Maciek's Claude Code
session wrote those. All of `env/` is in the "Maciek, Claude Code" row.

## The process Codex works in

`AGENTS.md` is the file Codex reads. It has one instruction:

> Read and follow `CLAUDE.md` in this folder. It is the one rule set for every
> agent on this team (Claude Code and Codex).

The rules it then follows, from `CLAUDE.md`:

> One task = one GitHub issue = one owner = one branch = one PR.

> Every PR gets an automatic **Opus review** (`opus-review` check). No human review.

> Interfaces between areas live in `docs/contract.md` [...]. Change it only in its own
> small PR, and tell the team.

> A decision that other people must know goes in `docs/decisions.md`: one line, the date
> and time, who, and why.

The loop for one task:

1. An issue describes the task. Many issues come from the review bot itself (label `todo`).
2. Codex works on a branch named `maciej/<issue>-<short>` and opens a PR with `Closes #<n>`.
3. The Opus review reads the diff and posts PASS or BLOCK. It opens up to three follow-up issues.
4. On PASS the PR merges by itself. On BLOCK, Codex (or its owner) fixes and pushes.
5. A choice that others must know goes into `docs/decisions.md`. Five entries are tagged
   Codex: #48, #67, #96, #364 and #459.

## Episodes

### 1. The Buyer loop, then two rounds of hardening from review issues

- Built: the bounded, audited Nemotron Buyer loop, 600 lines (PR #63, issue #22).
- Review: PASS. It opened #67: "decide whether the model may recover from policy
  rejections of read-only tools instead of ending the run."
- After: Codex closed #67 with PR #94, 23 minutes after the issue opened. That review
  opened #96 ("add a fixed reason code to POLICY_REJECTED feedback"). Codex closed #96
  with PR #113, 33 minutes later.
- Decisions logged: `docs/decisions.md`, "Maciek (Codex), #67" and "Maciek (Codex), #96".
- Shows: the review turns each PR into the next small task. Codex takes the `todo` issue,
  ships a small PR and records the rule it chose.

### 2. The unknown-stock rule

- Problem: Valio reports stock 999999 for some products. The review bot opened #48:
  "Terminal products (stock 999999) are never orderable: decide the rule".
- Built: PR #83 wrote the rule down with tests. The third review of that PR said: "put
  the unknown-stock rule into docs/contract.md so web/ and agent/ build against it"
  (#90). PR #92 did that 8 minutes later. PRs #247 and #258 then enforced it in the
  approval flow.
- Decision logged: "Unknown stock remains visible for proposals but is not orderable until
  supplier availability is confirmed; human approval alone does not confirm stock".
- Shows: Codex made a product decision in a docs PR first, then in the contract, then in code.

### 3. The one BLOCK: code ahead of the contract (#87)

- Built: PR #87 moved the approval idempotency key from an HTTP header to the JSON body.
  The matching contract change was PR #85, opened one minute earlier and still waiting
  for Aron's agreement.
- Review: BLOCK, twice. "If this merges alone, the code breaks the contract [...].
  Fix: merge #85 first (after Aron agrees on #53), then rebase this PR."
- After: Maciek's Claude Code session took over both branches ("Codex: please don't push
  here", PR comment). #85 merged at 21:01 UTC. The branch was rebased, the third review
  passed, and #87 merged at 21:04, 35 minutes after it opened.
- Shows: the review enforces the contract-first rule on Codex. The code was correct; the
  order was wrong. The rebase that fixed it was done by Claude Code, not Codex.

### 4. Recall holds and replacement baskets (#455)

- Built: a recalled product puts the proposal on hold, the engine sizes a replacement
  basket, and a person approves it (PR #455, issue #358, 308 lines).
- Review: three reviews, all PASS, with four follow-up issues. One of them, #456: "a
  proposal stays stuck in COMMITTING if record_attempt fails".
- After: Codex fixed #456 in PR #508, 18 minutes after the issue opened. It closed #459
  ("a BLOCKED_BY_RECALL proposal can't be rejected, and recall blocks never expire") with
  contract PR #536 and code PR #539. The Claude fix bot took the two small ones (#457 in
  PR #695, #468 in PR #509).
- Decision logged: "Maciek/Codex, #459 - Recall holds never expire automatically. A human
  may dismiss one notice after checking packs and recording a reason".
- Shows: a PASS is not the end. The review splits follow-ups between the fix bot (small,
  clear) and Codex (needs a decision).

### 5. Codex as the second reviewer (#120)

- Context: Maciek's Claude Code session was writing the LLM buyer baseline for Kitchen Week.
- What Codex did (issue #120, comments at 21:22 to 21:30 UTC on 2026-11-13): it ran its
  own offline checks against the Claude worktree without changing files. "Six independent
  offline regression checks currently fail". Examples: a quantity of `1e999` raised
  `OverflowError`, and a credential echoed by the model was written to the transcript.
- After: the Claude session fixed all six and added them as tests. Codex ran its checks
  again: "all 32 env tests and all 6 external regression checks now pass". PR #294 lists
  the fixes as "Hardening from Codex's review on #120".
- Shows: two agents from two vendors check each other. Codex found six defects before the
  PR opened, among them a possible key leak. The Opus review then passed the PR on its
  first run.

### 6. Two mistakes Codex made, and how they were found

Maciek's Codex session reported both in its comment on #360.

- Packaging: the recall and label modules were missing from the gateway image. Tests
  passed in the source tree, but the live label endpoint returned 500. Fix: PR #503
  (issue #502). It adds the package data and a CI step that imports the modules from the
  built image.
- Wrong heading: the label UI showed the "Hyvää Suomesta" heading for label schemes it
  does not support. Fix: PR #514 (issue #513), with a regression test.
- Shows: the Opus review reads a diff. It cannot see a file that is missing from an
  image. A live smoke test found the first mistake; the review did not.

## What Maciek's Codex session reported itself

Source: the comment on #360 by Maciek's Codex session, 2026-11-14 01:40 UTC. We repeat
it here; we did not see the session.

- The prompts for PRs #434, #436, #455, #476 and #493 were short: "Finish those tasks", after
  Maciek selected issues #170, #358, #364, #368 and #376. Later "Go on" selected #443,
  #459 and #447 (PRs #527, #539, #536). The detail came from the issue text.
- These sessions ran on the OpenAI-hosted Codex agent. Kimi and DeepSeek were not used as
  coding workers for them.

## Honest limits

- Codex is one of three developers and 11% of the merged PRs. Aron and Tymon use Claude
  Code. The review bot is Claude Opus (`ai-review.yml`). The fix bot is Claude (`ai-fix.yml`).
- Maciek uses both agents. 15 of his 57 PRs, with all of `env/`, came from Claude Code.
- A non-blocking OpenAI Codex CI reviewer is merged in #1075. Runtime verification
  and the first genuine model comment are tracked in #361 / #1088; a green workflow
  with an unavailable comment is not evidence of a successful review.
- Codex generated a Buyer client from public docs alone in the recorded [#372 experiment](evidence/codex-372/README.md).
  An operator reviewed and executed it once: a live PENDING proposal, with no approval/order.
  The successful generation took 70.7 seconds; all setup/retries/review took 6 min 49 s.
- We did not measure time saved. Open-to-merge time measures the review, not the coding.
- The repo has Codex CLI profiles for Kimi and DeepSeek on Verda (`CLAUDE.md`, "Multi-model
  coding"). The repo cannot show which model wrote which PR.
- The [#372 generation recording](evidence/codex-372/generation.mp4) is available.
  It records generation, not the separate operator-executed proposal write.

## Session evidence and remaining unknowns

The [session notes](codex-session-notes.md) give three exact prompts, the selected
issues/PRs, two mistakes, known model routing and the limits of historical attribution.
The 42-PR author/trailer classification above is a repository heuristic, not a
per-session model ledger. Exact old model IDs and hands-on/manual comparison times
were not retained; they remain unknown rather than retroactively invented.

[Watch the 82-second issue-to-merge recording](evidence/codex-360/issue-to-merge.mp4)
([editing and scope notes](evidence/codex-360/README.md)). It shows actual #372
client generation, a live read of the result, and PR #1083 passing review and
merging. Excerpts play at 1.25x with waiting removed. The separately executed
proposal write is evidenced by its saved result, not claimed to be filmed.

Why #85/#87 changed hands: the contract had to merge before the implementation;
Maciek's Claude session requested ownership of those branches in the PR discussion.
Codex stopped pushing, and Claude performed the final rebase/merge. This is a
process handoff, not evidence of a model capability difference.
