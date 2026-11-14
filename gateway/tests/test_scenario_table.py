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


# The status each case has today. A change (PASS -> PARTIAL/FAIL) means a number or
# a reason code stopped matching docs/scenarios.md. When a case gets better (a
# PARTIAL starts emitting its codes), update this table in the same PR.
EXPECTED_STATUS = {
    "S01": "PASS",
    "S02": "PASS",
    "S03": "PASS",
    "S04": "PASS",
    "S05": "PASS",
    "S06": "PASS",
    "S07": "PASS",
    "S08": "PASS",
    "S09": "PASS",
    "S10": "PASS",
    "S11": "PASS",
    "S12": "PASS",
    "S13": "PASS",
}


def test_every_case_keeps_its_pinned_status():
    results = {r.id: r for r in run()}
    changed = [
        f"{case}: {want} -> {results[case].status} {results[case].problems}"
        for case, want in EXPECTED_STATUS.items()
        if results[case].status != want
    ]
    assert not changed, changed


def test_strict_exit_code_fails_on_fail(monkeypatch, capsys):
    import gateway.scenarios as scenarios

    results = scenarios.run()
    results[0].status = "FAIL"
    monkeypatch.setattr(scenarios, "run", lambda: results)
    assert scenarios.main([]) == 0
    assert scenarios.main(["--strict"]) == 1
