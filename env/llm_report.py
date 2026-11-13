"""Summarise LLM buyer transcripts against the reference policy (issue #120).

    python -m env.llm_report                 # plain table from env/out/llm
    python -m env.llm_report --markdown      # GitHub table for env/README.md

Reads `<model>-<kitchen>-seed<N>.jsonl` written by env/llm.py; skips unfinished runs.
The reference score is recomputed per (kitchen, seed): the policy is deterministic.
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from env.run import POLICIES, run

NAME = re.compile(r"^(?P<model>.+)-(?P<kitchen>restaurant|hotel|school|hospital)-seed(?P<seed>\d+)\.jsonl$")
MODELS = ("deepseek", "kimi", "nemotron", "nemotron-nothink")
KITCHENS = ("restaurant", "hotel", "school", "hospital", "all")
HEADERS = ("model", "kitchen", "episodes", "score", "reference", "gap", "lost covers",
           "skipped approvals", "orders during stock-out", "bad replies", "tokens/episode")


def episode(rows, reference) -> dict:
    summary = rows[-1]
    report = summary["report"]
    events = summary.get("events") or []
    return {"score": report["score"], "reference": reference, "gap": report["score"] - reference,
            "lost": report["lost_covers"],
            "skipped": sum("sent without approval" in e for e in events),
            # The env logs this only for a product ordered inside Valio's announced
            # stock-out window, so it counts orders that ignored the notice.
            "violations": sum("Valio could not deliver" in e for e in events),
            "problems": summary.get("problems") or 0, "tokens": summary.get("tokens") or 0}


def load(folder: Path):
    """{(model, kitchen): [episode]} and the number of unfinished files."""
    grouped, refs, skipped = defaultdict(list), {}, 0
    for path in sorted(folder.glob("*.jsonl")):
        m = NAME.match(path.name)
        if not m:
            continue
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        if not rows or "report" not in rows[-1]:
            skipped += 1
            continue
        key = (m["kitchen"], int(m["seed"]))
        if key not in refs:
            refs[key] = run(POLICIES["reference"], key[1], key[0]).report()["score"]
        grouped[m["model"], m["kitchen"]].append(episode(rows, refs[key]))
    return grouped, skipped


def table(grouped) -> list:
    def row(model, kitchen, eps):
        mean = lambda k: sum(e[k] for e in eps) / len(eps)  # noqa: E731
        total = lambda k: sum(e[k] for e in eps)  # noqa: E731
        return [model, kitchen, str(len(eps)), f"{mean('score'):.0f}", f"{mean('reference'):.0f}",
                f"{mean('gap'):+.0f}", f"{mean('lost'):.1f}", str(total("skipped")),
                str(total("violations")), str(total("problems")), f"{mean('tokens'):.0f}"]

    order = lambda m: (MODELS.index(m) if m in MODELS else len(MODELS), m)  # noqa: E731
    out = []
    for model in sorted({m for m, _ in grouped}, key=order):
        kitchens = sorted((k for m, k in grouped if m == model), key=KITCHENS.index)
        for k in kitchens:
            out.append(row(model, k, grouped[model, k]))
        if len(kitchens) > 1:
            out.append(row(model, "all", [e for k in kitchens for e in grouped[model, k]]))
    return out


def render(rows, markdown: bool) -> str:
    if markdown:
        lines = ["| " + " | ".join(HEADERS) + " |", "|" + "---|" * len(HEADERS)]
        return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in rows])
    widths = [max(len(x) for x in col) for col in zip(HEADERS, *rows)]
    fmt = lambda r: "  ".join(v.ljust(w) if i < 2 else v.rjust(w)  # noqa: E731
                              for i, (v, w) in enumerate(zip(r, widths)))
    return "\n".join([fmt(HEADERS)] + [fmt(r) for r in rows])


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="Summarise LLM buyer transcripts")
    p.add_argument("--dir", type=Path, default=Path("env/out/llm"))
    p.add_argument("--markdown", action="store_true")
    a = p.parse_args(argv)
    grouped, skipped = load(a.dir)
    if skipped:
        print(f"skipped {skipped} unfinished run(s)", file=sys.stderr)
    print(render(table(grouped), a.markdown))


if __name__ == "__main__":
    main()
