"""Token meter (#365): how much Nemotron each role uses, from the endpoint's own `usage`.

    docker compose logs buyer | python -m agent.usage      # table per role, from the worker log
    python -m agent.usage .local/usage.jsonl               # the same from a file

`agent/model.py` records every model call on `Nemotron.meter`: calls, failed calls, prompt
tokens, completion tokens, reasoning tokens (a part of the completion tokens) and seconds.
A role is who asked: `buyer` (the tool loop), `vl_delivery_note`, `vl_shelf_count`.
At the end of a run the caller writes one line, `NEMOTRON_USAGE {json}`, to stderr and,
when `NEMOTRON_USAGE_LOG` names a file, to that file too. The line holds counts only:
no request text, no reply text, no key.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

MARK = "NEMOTRON_USAGE "
FIELDS = ("calls", "failed", "prompt_tokens", "completion_tokens", "reasoning_tokens", "seconds")


def _count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def read_usage(usage) -> dict:
    """The token counts of one reply. A missing or malformed field counts as 0."""
    usage = usage if isinstance(usage, dict) else {}
    details = usage.get("completion_tokens_details")
    reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else usage.get("reasoning_tokens")
    return {"prompt_tokens": _count(usage.get("prompt_tokens")),
            "completion_tokens": _count(usage.get("completion_tokens")),
            "reasoning_tokens": _count(reasoning)}


def add(total: dict, row: dict) -> dict:
    for field in FIELDS:
        value = row.get(field, 0)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total[field] = round(total.get(field, 0) + value, 3)
    return total


class Meter:
    """Counts per role for one model client."""

    def __init__(self):
        self.roles: dict[str, dict] = {}

    def record(self, role: str, usage, seconds: float, *, ok: bool = True) -> None:
        row = {"calls": 1, "failed": 0 if ok else 1, "seconds": seconds, **read_usage(usage)}
        add(self.roles.setdefault(role, dict.fromkeys(FIELDS, 0)), row)

    def total(self) -> dict:
        total = dict.fromkeys(FIELDS, 0)
        for row in self.roles.values():
            add(total, row)
        return total


def emit(meter, **facts) -> None:
    """Write the run's usage line. Never raises: a meter must not break a run."""
    if not isinstance(meter, Meter) or not meter.roles:
        return
    line = MARK + json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              **facts, "roles": meter.roles})
    try:
        print(line, file=sys.stderr, flush=True)
        path = os.environ.get("NEMOTRON_USAGE_LOG")
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8", newline="\n") as stream:
                stream.write(line + "\n")
    except (OSError, ValueError):
        pass


def collect(lines) -> tuple[dict, int]:
    """Sum the usage lines found in `lines` (other log lines are skipped): (per role, runs)."""
    roles, runs = {}, 0
    for line in lines:
        start = line.find(MARK)
        if start < 0:
            continue
        try:
            found = json.loads(line[start + len(MARK):])["roles"]
            rows = [(str(role), row) for role, row in found.items() if isinstance(row, dict)]
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        runs += 1
        for role, row in rows:
            add(roles.setdefault(role, dict.fromkeys(FIELDS, 0)), row)
    return roles, runs


def table(roles: dict, runs: int) -> str:
    head = ("role", "calls", "failed", "prompt tok", "completion tok", "of which reasoning", "seconds")
    total = dict.fromkeys(FIELDS, 0)
    for row in roles.values():
        add(total, row)
    body = [(role, *(row[f] for f in FIELDS)) for role, row in sorted(roles.items())]
    body.append(("all", *(total[f] for f in FIELDS)))
    cells = [head] + [(r[0], *(f"{v:.1f}" if isinstance(v, float) else str(v) for v in r[1:])) for r in body]
    out = ["| " + " | ".join(row) + " |" for row in cells]
    out.insert(1, "|" + "---|" * len(head))
    out.append(f"\n{runs} run(s), {total['prompt_tokens'] + total['completion_tokens']} tokens in all.")
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Sum Nemotron usage lines into a table per role")
    p.add_argument("files", nargs="*", type=Path, help="log files; none = read stdin")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    lines = []
    for path in a.files:
        lines += path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not a.files:
        lines = sys.stdin.read().splitlines()
    roles, runs = collect(lines)
    print(json.dumps({"runs": runs, "roles": roles}, indent=2) if a.json else table(roles, runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
