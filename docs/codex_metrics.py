"""Numbers for docs/codex.md, from the GitHub API only.

Run from the repo root (needs the `gh` CLI, logged in):

    python docs/codex_metrics.py --until 2026-11-14T03:30:00Z

Groups merged PRs by who opened them. Maciek's PRs are split in two by the
squash commit on main: a `Co-authored-by: Claude` trailer means a Claude Code
session wrote it; no trailer means his Codex session (Claude Code adds the
trailer, Codex does not). The review verdict is the first line of each
`Opus review: PASS|BLOCK` comment that .github/workflows/ai-review.yml posts.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

QUERY = """
query($c: String) {
  repository(owner: "Afro666", name: "2Brothers") {
    pullRequests(states: MERGED, first: 25, after: $c,
                 orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number createdAt mergedAt additions deletions
        author { login }
        mergeCommit { message }
        files(first: 100) { nodes { path additions } }
        comments(first: 40) { nodes { body } }
      }
    }
  }
}
"""

GROUPS = [
    "Maciek, Codex",
    "Maciek, Claude Code",
    "Aron, Claude Code",
    "Tymon, Claude Code",
    "Fix bot, Claude",
]


def fetch() -> list[dict]:
    prs, cursor = [], None
    while True:
        cmd = ["gh", "api", "graphql", "-f", "query=" + QUERY]
        if cursor:
            cmd += ["-f", "c=" + cursor]
        for _ in range(4):  # the venue network drops calls: retry
            run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            if run.returncode == 0:
                break
            time.sleep(5)
        else:
            sys.exit("gh api failed: " + run.stderr[:300])
        page = json.loads(run.stdout)["data"]["repository"]["pullRequests"]
        prs += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return prs
        cursor = page["pageInfo"]["endCursor"]


def group(pr: dict) -> str:
    login = pr["author"]["login"]
    if login == "maciejczerniak":
        message = (pr["mergeCommit"] or {}).get("message", "")
        claude = "co-authored-by: claude" in message.lower()
        return "Maciek, Claude Code" if claude else "Maciek, Codex"
    return {"Afro666": "Aron, Claude Code", "Tymonoman": "Tymon, Claude Code"}.get(
        login, "Fix bot, Claude"
    )


def verdicts(pr: dict) -> list[str]:
    out = []
    for comment in pr["comments"]["nodes"]:
        first = comment["body"].lstrip().split("\n")[0]
        if first.startswith("Opus review:"):
            out.append("BLOCK" if "BLOCK" in first else "PASS")
    return out


def top(path: str) -> str:
    return path.split("/")[0] if "/" in path else "(root)"


def is_test(path: str) -> bool:
    name = path.split("/")[-1]
    return "/tests/" in path or name.startswith("test_") or ".test." in name


def minutes(pr: dict) -> float:
    def ts(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    return (ts(pr["mergedAt"]) - ts(pr["createdAt"])).total_seconds() / 60


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--until", default="9999", help="count PRs merged up to this UTC time")
    args = parser.parse_args()

    prs = [pr for pr in fetch() if pr["mergedAt"] <= args.until]
    by_group = defaultdict(list)
    for pr in prs:
        by_group[group(pr)].append(pr)

    print(f"Merged PRs up to {args.until}: {len(prs)}")
    print(f"First opened {min(p['createdAt'] for p in prs)}, last merged {max(p['mergedAt'] for p in prs)}\n")
    print("| Who opened the PR | Merged PRs | Lines + | Lines - | Median open to merge (min) "
          "| First review PASS | PRs reviewed more than once | PRs with a BLOCK |")
    print("|---|---|---|---|---|---|---|---|")
    for name in GROUPS:
        rows = by_group[name]
        if not rows:
            continue
        seen = [verdicts(pr) for pr in rows]
        first_pass = sum(1 for v in seen if v and v[0] == "PASS")
        blocked = [f"#{pr['number']}" for pr, v in zip(rows, seen) if "BLOCK" in v]
        print(f"| {name} | {len(rows)} | {sum(p['additions'] for p in rows)} "
              f"| {sum(p['deletions'] for p in rows)} "
              f"| {statistics.median(minutes(p) for p in rows):.1f} "
              f"| {first_pass} of {len(rows)} | {sum(1 for v in seen if len(v) > 1)} "
              f"| {len(blocked)} {' '.join(blocked)} |")

    for name in ("Maciek, Codex", "Maciek, Claude Code"):
        rows = by_group[name]
        touched, added, tests = Counter(), Counter(), 0
        for pr in rows:
            files = pr["files"]["nodes"]
            touched.update({top(f["path"]) for f in files})
            for f in files:
                added[top(f["path"])] += f["additions"]
                tests += f["additions"] if is_test(f["path"]) else 0
        print(f"\n{name}: PR numbers {' '.join(str(p['number']) for p in rows)}")
        print(f"Lines added in test files: {tests}\n")
        print("| Folder | PRs that touch it | Lines added |")
        print("|---|---|---|")
        for folder, count in touched.most_common():
            print(f"| `{folder}` | {count} | {added[folder]} |")


if __name__ == "__main__":
    main()
