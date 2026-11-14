import pytest

pytest.importorskip("mongomock")

from agent.conformance import CASES, main, run_cases


def test_rt01_prompt_injection_is_refused_and_audited():
    [result] = run_cases(["RT01"])
    failed = [c["check"] for c in result["checks"] if not c["passed"]]
    assert result["passed"], failed
    assert len(result["checks"]) == 12
    codes = " ".join(result["audit"])
    for code in ("SCHEMA_INVALID", "TOOL_NOT_ALLOWED", "HUMAN_APPROVAL_REQUIRED"):
        assert f"reason_code={code}" in codes


def test_cli_exit_code_and_unknown_case(capsys):
    assert set(CASES) == {"RT01"}
    assert main(["RT01"]) == 0
    assert "RT01  prompt injection in catalog text  PASS" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["RT99"])
