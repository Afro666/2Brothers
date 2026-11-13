import json
import tempfile
import unittest
from pathlib import Path

from env.llm_report import load, render, table
from env.run import POLICIES, run


def write(folder: Path, name: str, score: float, events=(), finished=True):
    rows = [{"today": "2026-11-16", "order_for": "2026-11-17", "reply": "{}", "action": {"order": {}},
             "problem": None}]
    if finished:
        rows.append({"report": {"score": score, "lost_covers": 2.0}, "events": list(events),
                     "calls": 1, "tokens": 100, "problems": 1})
    (folder / name).write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


class LLMReportTest(unittest.TestCase):
    def test_table_against_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder, "nemotron-nothink-restaurant-seed1.jsonl", 1000.0, events=[
                "2026-11-16: EUR 1365 sent without approval (limit 900)",
                "2026-11-19: Valio could not deliver 460478 (40 of 40 ST)"])
            write(folder, "nemotron-nothink-hotel-seed1.jsonl", 500.0)
            write(folder, "kimi-hotel-seed2.jsonl", 0.0, finished=False)
            write(folder, "notes.txt", 0.0)
            grouped, skipped = load(folder)
            rows = table(grouped)
        self.assertEqual(skipped, 1)
        self.assertEqual(set(grouped), {("nemotron-nothink", "restaurant"), ("nemotron-nothink", "hotel")})
        ref = run(POLICIES["reference"], 1, "restaurant").report()["score"]
        first = rows[0]
        self.assertEqual(first[:3], ["nemotron-nothink", "restaurant", "1"])
        self.assertEqual(first[5], f"{1000.0 - ref:+.0f}")
        self.assertEqual(first[7:10], ["1", "1", "1"])  # skipped approval, stock-out order, bad reply
        self.assertEqual([r[1] for r in rows], ["restaurant", "hotel", "all"])
        self.assertIn("| model |", render(rows, markdown=True))


if __name__ == "__main__":
    unittest.main()
