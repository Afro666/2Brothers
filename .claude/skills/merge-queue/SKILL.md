---
name: merge-queue
description: Test the open ai-fix (fix agent) PRs on top of main and merge the green ones, at their reviewed head. Use when bot PRs pile up, or when asked to "merge green fix PRs" or run the merge queue overnight.
---

# Merge queue for ai-fix PRs

Fix-agent PRs (branch `ai-fix/<n>`) have no auto-merge since #625, and their GitHub test runs
often wait for approval. So a session tests each one locally on top of the current main and
merges it only when green. Built and run on the night of 2026-11-14 (about 60 bot PRs merged).

## Run

From the main checkout, in Git Bash. `GATE_PY` is a Python with the test deps
(`pip install -e ".[test,signals,covers]"`, the same extras as CI in tests.yml; without `covers` the env tests fail on numpy and look red). Each gate needs its own `GATE_NAME`; the web deps are
installed once per gate worktree (`npm ci` in its `web/`).

```
GATE_PY=/path/to/venv/Scripts/python bash scripts/merge-queue/loop.sh
GATE_PY=/path/to/venv/Scripts/python GATE_NAME=b GATE_ORDER=-r bash scripts/merge-queue/loop.sh
```

One PR by hand: `bash scripts/merge-queue/gate.sh <pr>`. Results go to `$GATE_LOG/night-log.txt`
(default `$TMPDIR/merge-queue`), one log file per PR and suite.

## What a gate does

1. Skips a PR without a successful `opus-review` on its head (it retries it later).
2. Fetches main and the PR into its own refs (`refs/gate/<name>/...`): worktrees share refs,
   and two sessions fetching `origin/main` at once raced and gave a false conflict.
3. Merges the PR onto main in the gate worktree. A conflict: it closes the PR and starts the
   fix agent again on current main (only if the issue is still open).
4. Python changed: the full suite. Web changed: `tsc`, then `vitest related` for the changed
   files; a failed file is run twice more alone (5 s timeouts flake when other sessions run
   tests on the same laptop).
5. Green: squash-merge through the API at the tested head SHA (`sha=`), then delete the branch.
   Red: nothing merged; a person reads the logs. Check whether main itself is red before
   blaming the PR.

## Rules

- One gate per worktree, enforced by a lock: two loops in one worktree once merged a red PR.
- A per-PR claim, so two gates never test the same PR.
- Never edit an `ai-fix/*` branch (CLAUDE.md); close and rerun instead.
- A red main makes every PR red: fix main first, then clear `tried.txt` for the open PRs.
- When a test-only PR adds a test for a fix that is not merged yet, it is red by design: close it.
- Stopping a loop (TaskStop) can leave its child processes running: kill that exact process
  tree (`taskkill //F //T //PID <pid>`), never every bash.exe.
