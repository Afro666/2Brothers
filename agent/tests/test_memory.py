"""Kitchen memory (#1308): compact facts for the prompt and checked model claims."""
from decimal import Decimal
import json

from agent.memory import (RULES, TITLE, allowed_numbers, check_learned_sentences,
                          check_not_applicable, kitchen_memory, prompt_block)


def fact(fact_id, kind, *, active=True, product_id=None, supplier_id=None, name=None,
         value=0, rows=1, last="2026-11-10", **extra):
    return {
        "id": fact_id, "kind": kind, "active": active,
        "product_id": product_id, "supplier_id": supplier_id, "name": name,
        "value": value,
        "evidence": {"rows": rows, "since": "2026-10-01", "last": last},
        **extra,
    }


def ratio_fact(**change):
    values = {"fact_id": "ratio-potato", "kind": "CORRECTION_RATIO",
              "product_id": "prod-potato", "name": "Potatoes", "value": 0.5,
              "rows": 4, "from_qty": 400, "to_qty": 200}
    values.update(change)
    return fact(**values)


def test_memory_keeps_this_kitchen_and_orders_by_kind_then_evidence_then_id():
    facts = [
        fact("correction-low", "CORRECTION_RATIO", product_id="prod-1", rows=2, value=0.8),
        fact("short", "SUPPLIER_SHORT", supplier_id="sup-1", rows=4, value=0.8, fill_rate=0.8),
        fact("correction-high", "CORRECTION_RATIO", product_id="prod-1", name="Milk",
             rows=7, value=0.75, from_qty=400, to_qty=300),
        fact("declined", "DECLINED_PRODUCT", product_id="prod-1", rows=9, value=3),
        fact("late", "SUPPLIER_LATE", supplier_id="sup-1", rows=5, value=0.9,
             on_time_rate=0.9, mean_days_late=2.5, deliveries=10),
        fact("inactive", "CORRECTION_RATIO", active=False, product_id="prod-1", rows=99),
        fact("other-kitchen", "CORRECTION_RATIO", product_id="prod-2", rows=100),
        fact("other-supplier", "SUPPLIER_SHORT", supplier_id="sup-2", rows=100),
    ]

    entries = kitchen_memory(facts, {"prod-1"}, {"sup-1"})

    assert [entry["id"] for entry in entries] == [
        "correction-high", "correction-low", "declined", "late", "short"]
    assert entries[0] == {
        "id": "correction-high", "kind": "CORRECTION_RATIO", "product_id": "prod-1",
        "name": "Milk", "value": 0.75, "from_qty": 400, "to_qty": 300,
        "rows": 7, "last": "2026-11-10"}
    assert entries[3] == {
        "id": "late", "kind": "SUPPLIER_LATE", "supplier_id": "sup-1", "name": None,
        "value": 0.9, "on_time_rate": 0.9, "mean_days_late": 2.5, "deliveries": 10,
        "rows": 5, "last": "2026-11-10"}


def test_memory_caps_lines_and_the_exact_json_length():
    facts = [fact(f"fact-{number}", "DECLINED_PRODUCT", product_id="prod-1",
                  rows=number, value=number) for number in range(6, 0, -1)]
    full = kitchen_memory(facts, {"prod-1"}, set(), max_lines=99)
    assert [entry["id"] for entry in full] == [f"fact-{number}" for number in range(6, 0, -1)]

    assert kitchen_memory(facts, {"prod-1"}, set(), max_lines=2) == full[:2]
    exact = len(json.dumps(full[:2], ensure_ascii=False))
    assert kitchen_memory(facts, {"prod-1"}, set(), max_chars=exact) == full[:2]
    assert kitchen_memory(facts, {"prod-1"}, set(), max_chars=exact - 1) == full[:1]
    assert kitchen_memory(facts, {"prod-1"}, set(), max_lines=0) == []


def test_an_empty_memory_leaves_the_prompt_exactly_unchanged():
    assert prompt_block([]) == ""

    entries = kitchen_memory([ratio_fact()], {"prod-potato"}, set())
    block = prompt_block(entries)
    title, rules, encoded = block.split("\n", 2)
    assert title == TITLE and rules == RULES
    assert json.loads(encoded) == entries


def test_allowed_numbers_include_percent_forms_and_evidence_rows():
    corr = allowed_numbers(ratio_fact())
    assert {Decimal("0.5"), Decimal(50), Decimal(4), Decimal(400), Decimal(200)} <= corr
    assert Decimal(2026) not in corr                       # never dates

    late = allowed_numbers(fact("late", "SUPPLIER_LATE", supplier_id="sup-1", value=0.9,
                                rows=8, on_time_rate=0.9, mean_days_late=2.5, deliveries=8))
    assert {Decimal("0.9"), Decimal(90), Decimal("2.5"), Decimal(8)} <= late


def test_learned_sentences_accept_the_fact_numbers_and_drop_bad_ones_alone():
    ratio = ratio_fact()
    good = {"fact_id": "ratio-potato",
            "text": "You cut potatoes to 50 % in 4 of your last orders.",
            "numbers": ["50", "4"]}
    wrong = {"fact_id": "ratio-potato",
             "text": "You cut potatoes to 40 % in 4 of your last orders.",
             "numbers": ["40", "4"]}
    word = {"fact_id": "ratio-potato",
            "text": "You cut potatoes to half in 4 of your last orders.",
            "numbers": ["4"]}

    assert check_learned_sentences([good, wrong, word], [ratio], "en") == (
        [good], [{"fact_id": "ratio-potato", "reason": "NUMBER_NOT_IN_ROW"},
                 {"fact_id": "ratio-potato", "reason": "NUMBER_WORD"}])

    finnish = {"fact_id": "ratio-potato",
               "text": "Leikkasit perunat 50 %:iin 4 viimeisestä tilauksesta.",
               "numbers": ["50", "4"]}
    assert check_learned_sentences([finnish], [ratio], "fi") == ([finnish], [])


def test_unknown_and_inactive_fact_ids_are_dropped_with_fact_unknown():
    active = ratio_fact()
    inactive = ratio_fact(fact_id="ratio-off", active=False)
    sentence = {"fact_id": "ratio-potato", "text": "You cut potatoes to 50 %.",
                "numbers": ["50"]}

    kept, dropped = check_learned_sentences(
        [sentence,
         {"fact_id": "ratio-missing", "text": "No numbers.", "numbers": []},
         {"fact_id": "ratio-off", "text": "No numbers.", "numbers": []}],
        [active, inactive], "en")

    assert kept == [sentence]
    assert dropped == [{"fact_id": "ratio-missing", "reason": "FACT_UNKNOWN"},
                       {"fact_id": "ratio-off", "reason": "FACT_UNKNOWN"}]


def test_not_applicable_reasons_must_be_short_and_use_only_their_facts_numbers():
    active = ratio_fact()
    marks = [
        {"fact_id": "ratio-potato", "reason": "The correction fits a different request."},
        {"fact_id": "ratio-potato", "reason": "The 50 % correction fits a different request."},
        {"fact_id": "ratio-potato", "reason": "The 99 % correction fits a different request."},
        {"fact_id": "ratio-missing", "reason": "The fact is not known."},
        {"fact_id": "ratio-potato", "reason": "x" * 201},
    ]

    assert check_not_applicable(marks, [active], "en") == marks[:2]
