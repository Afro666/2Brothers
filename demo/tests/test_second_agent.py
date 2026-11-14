"""The second agent's small helpers (demo/second_agent.py). The live run itself is not a unit test."""

from datetime import date
from types import SimpleNamespace

from demo.second_agent import error_code, next_monday, pick_products, tool_json


def test_next_monday_is_always_ahead():
    assert next_monday(date(2026, 11, 14)) == date(2026, 11, 16)
    assert next_monday(date(2026, 11, 16)) == date(2026, 11, 23)


def test_products_that_can_arrive_come_first_and_no_quantity_is_chosen():
    rows = [{"product_id": "1", "can_arrive": False}, {"product_id": "2", "can_arrive": True},
            {"product_id": "3"}, {"product_id": "4", "can_arrive": True}, {"name": "no id"}]
    assert pick_products(rows) == ["2", "4", "1"]
    assert pick_products([]) == []


def test_a_tool_result_is_read_from_structured_content_or_text():
    assert tool_json(SimpleNamespace(structuredContent={"offer_id": "a"}, content=[])) == {"offer_id": "a"}
    assert tool_json(SimpleNamespace(structuredContent={"result": {"offer_id": "b"}}, content=[])) == {"offer_id": "b"}
    text = SimpleNamespace(text='{"status": "PENDING"}')
    assert tool_json(SimpleNamespace(structuredContent=None, content=[text])) == {"status": "PENDING"}
    assert tool_json(SimpleNamespace(structuredContent=None, content=[SimpleNamespace(text="not json")])) == {"text": "not json"}
    assert tool_json(SimpleNamespace(structuredContent=None, content=[])) == {}


def test_the_error_code_of_a_refusal():
    assert error_code({"error": {"code": "HUMAN_SESSION_REQUIRED", "message": "x"}}) == "HUMAN_SESSION_REQUIRED"
    assert error_code({}) == "" and error_code({"error": "text"}) == ""


def test_the_module_needs_no_mcp_library_to_import():
    import demo.second_agent as module
    assert "mcp" not in {name.split(".")[0] for name in vars(module) if not name.startswith("_")}
