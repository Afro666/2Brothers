# Junction 2026 – team rules for every agent

Team: Aron, Tymon, Maciek. Agents: Claude Code (all three), Codex (Maciek).
Codex reads `AGENTS.md`, which points here. One rule set for all agents.

## How we work

- One task = one GitHub issue = one owner = one branch = one PR.
- Branch name: `<name>/<issue>-<short>` (example: `aron/12-voice-api`).
- `main` is protected: no direct push. Every change is a PR.
- Every PR gets an automatic **Sonnet review** (`sonnet-review` check). No human review.
- Open the PR with auto-merge on, so it merges by itself when the review passes:
  `gh pr create --fill` then `gh pr merge --auto --squash --delete-branch`.
- Review says BLOCK: read its PR comment, fix, push again. It re-runs by itself.
- Small PRs, merged often (aim: every 1–2 hours). Long branches cause conflicts.
- Pull `main` before you start a task: `git pull --rebase origin main`.
- Stay inside your area folder (see "Areas"). Touching another area: say it in the issue first.
- Conventional commit messages: `feat:`, `fix:`, `docs:`, `chore:`.

## Areas (who owns which folder)

Filled in after the idea is picked. Until then, ask before you create a top-level folder.

| Folder | Owner | What |
|---|---|---|
| `TBD` | Aron | |
| `TBD` | Tymon | |
| `TBD` | Maciek | |

## Contracts

- Interfaces between areas live in `docs/contract.md` (API routes, message
  formats, pin maps). Change it only in its own small PR, and tell the team.
- Build against the contract with mock data. Do not wait for the other side.

## Secrets

- Keys go in `.env` (git-ignored). `.env.example` lists the key names only.
- Never print a key in a log, a commit, an issue or a PR.

## Decisions

- A decision that other people must know goes in `docs/decisions.md`:
  one line, the date and time, who, and why.
- Before a large change, read `docs/decisions.md` so you do not undo a choice.
