"""The S01-S13 pass table runs end to end and never crashes (python -m gateway.scenarios)."""

import pytest

pytest.importorskip("mongomock")
pytest.importorskip("fastapi")

from gateway.scenarios import main, run, table  # noqa: E402


def test_every_scenario_runs_and_none_crashes():
    results = run()
    assert [r.id for r in results] == [f"S{n:02d}" for n in range(1, 14)]
    crashed = [f"{r.id}: {r.problems}" for r in results if r.status == "ERROR"]
    assert not crashed, crashed
    assert {r.status for r in results} <= {"PASS", "PARTIAL", "FAIL", "NOT BUILT"}


def test_a_pass_has_no_problems_and_no_missing_codes():
    for r in run():
        if r.status == "PASS":
            assert not r.problems and not r.missing_codes, r.id


def test_markdown_table_and_exit_code(capsys):
    assert main(["--markdown"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("| Case | What |") and "S13" in out
    assert table(run()).count("\n") >= 14
