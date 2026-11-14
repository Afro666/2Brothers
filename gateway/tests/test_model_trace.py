"""What the model did (#1197): the trace holds counts and codes, never text the model wrote."""

import pytest

from gateway import model_trace as mt


USAGE = {"calls": 4, "failed": 1, "prompt_tokens": 23110, "completion_tokens": 910,
         "reasoning_tokens": 0, "seconds": 6.21449}


def test_build_takes_the_meter_counts_and_rounds_the_seconds():
    trace = mt.build(reader="buyer", made_by="model", usage=USAGE, thinking=False,
                     steps=[mt.step("search_products", query="lactose free milk", count=12)])
    assert trace == {"made_by": "model", "reader": "buyer", "model": "nemotron-3.5-super-vl",
                     "thinking": False, "calls": 4, "failed": 1, "prompt_tokens": 23110,
                     "completion_tokens": 910, "reasoning_tokens": 0, "seconds": 6.214,
                     "attempts": 1, "truncated": False,
                     "steps": [{"by": "model", "attempt": 1, "tool": "search_products",
                                "query": "lactose free milk", "count": 12}]}


def test_build_without_a_meter_counts_zero_and_a_bad_count_is_zero():
    trace = mt.build(reader="buyer", made_by="model", usage={"calls": -2, "prompt_tokens": True,
                                                              "seconds": float("nan")})
    assert (trace["calls"], trace["prompt_tokens"], trace["seconds"]) == (0, 0, 0)
    assert mt.build(reader="buyer", made_by="model", usage=None)["calls"] == 0


def test_a_non_boolean_thinking_is_unknown():
    assert mt.build(reader="buyer", made_by="model", thinking="off")["thinking"] is None


def test_steps_are_cut_at_forty_and_say_so():
    trace = mt.build(reader="buyer", made_by="model", steps=[mt.step("get_offer")] * 45)
    assert len(trace["steps"]) == 40 and trace["truncated"] is True


def test_parser_trace_has_no_model_and_no_steps():
    trace = mt.parser_trace()
    assert trace["made_by"] == "rule" and trace["reader"] == "parser"
    assert trace["model"] is None and trace["thinking"] is None and trace["steps"] == []
    assert trace["calls"] == trace["attempts"] == 0 and trace["seconds"] == 0


@pytest.mark.parametrize("raw, clean", [
    ("lactose free milk", "lactose free milk"),
    ("  maito\t laktoositon ", "maito laktoositon"),
    ('milk"; ignore previous <script>', "milk ignore previous script"),
    ("x" * 80, "x" * 60),
    ("kevytmaito-1,5%", "kevytmaito-15"),
    ("", None), ("!!!", None), (None, None), (42, None),
])
def test_query_keeps_only_letters_digits_spaces_and_hyphens(raw, clean):
    assert mt.clean_query(raw) == clean


def test_a_code_must_look_like_a_code():
    assert mt.step("simulate_order", code="NEEDS_APPROVAL")["code"] == "NEEDS_APPROVAL"
    assert "code" not in mt.step("simulate_order", code="needs approval, I think")
    assert "code" not in mt.step("simulate_order", code=None)


def test_an_unknown_tool_is_invalid():
    assert mt.step("rm_rf")["tool"] == "invalid"


def seller_trace(**changes):
    trace = mt.build(reader="seller", made_by="model", usage=USAGE, thinking=False,
                     steps=[mt.step("shortlist", by="code", count=5), mt.step("pick", code="PICKED")])
    return {**trace, **changes}


def test_clean_keeps_a_valid_trace_and_drops_unknown_fields():
    trace = seller_trace(system_prompt="secret", reply="the model's words")
    trace["steps"][0]["reason"] = "free text"
    out = mt.clean(trace)
    assert out == seller_trace()
    assert "system_prompt" not in out and "reason" not in out["steps"][0]


@pytest.mark.parametrize("change", [
    {"made_by": "person"}, {"reader": "someone"}, {"calls": -1}, {"calls": "4"}, {"calls": True},
    {"seconds": "6.2"}, {"seconds": -1}, {"thinking": "off"}, {"model": "x" * 101},
    {"steps": "none"}, {"steps": [{"tool": "pick"}] * 41}, {"steps": [{"tool": "pick", "by": "me"}]},
    {"steps": [{"tool": "pick", "code": "free text"}]}, {"steps": ["pick"]},
    {"steps": [{"tool": "pick", "count": -3}]}, {"attempts": 3}, {"truncated": "no"},
])
def test_clean_refuses_a_wrong_type_or_value(change):
    with pytest.raises(ValueError):
        mt.clean(seller_trace(**change))


def test_clean_refuses_what_is_not_an_object():
    for bad in (None, [], "trace", 3):
        with pytest.raises(ValueError):
            mt.clean(bad)
