"""Buying note for the supplier's planner (#1176): the model writes words, every number is
checked against its own row, and one bad line drops the whole note."""
import copy
from decimal import Decimal
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.buying_note import check, pick
from gateway.claim_check import check_sentence, number_word, numbers_in
from gateway.service import Gateway, GatewayError
from gateway.tests.test_gateway_app import AGENT, HUMAN, NOW, env  # noqa: F401 (fixture)
from gateway.tests.test_supplier_routes import seed
from gateway.valio_client import ValioClient

FIXTURES = Path(__file__).resolve().parents[2] / "agent" / "fixtures" / "buying_note"
ROWS = json.loads((FIXTURES / "rows.json").read_text(encoding="utf-8"))
URL = "/v1/suppliers/sup-valio/demand/buying-note?from=2026-11-16&to=2026-11-16"


def reply(lang="en"):
    return json.loads((FIXTURES / f"{lang}.reply.json").read_text(encoding="utf-8"))


def with_line(index, **change):
    r = copy.deepcopy(reply())
    r["lines"][index].update(change)
    return r


# ---- the number reader ------------------------------------------------------------------

def test_numbers_are_read_in_the_notes_language():
    assert numbers_in("buy 1,000 L and 12.5 KG", "en") == [Decimal(1000), Decimal("12.5")]
    assert numbers_in("osta 1 000 L ja 12,5 KG", "fi") == [Decimal(1000), Decimal("12.5")]
    assert numbers_in("1 000 l", "fi") == [Decimal(1000)]
    assert numbers_in("3 kitchens, 700 L", "en") == [Decimal(3), Decimal(700)]
    assert numbers_in("no numbers here", "en") == []


def test_number_words_are_found_in_both_languages():
    assert number_word("buy two hundred litres", "en") == "two"
    assert number_word("osta kaksi laatikkoa", "fi") == "kaksi"
    assert number_word("tuhat litraa", "fi") == "tuhat"
    assert number_word("Demand 2400 L, available 1700 L", "en") is None


def test_a_product_name_with_digits_is_not_read_as_a_quantity():
    text = "Valio Eila 1 l: buy 700 L."
    assert check_sentence(text, ["700"], ["700"], "en", strip=["Valio Eila 1 l"]) is None
    assert check_sentence(text, ["700"], ["700"], "en") == "NUMBER_NOT_IN_ROW"


# ---- the check, on the recorded Nemotron replies ------------------------------------------

@pytest.mark.parametrize("lang", ["en", "fi"])
def test_the_recorded_replies_pass_and_take_name_date_and_risk_from_the_row(lang):
    note, dropped = check(reply(lang), ROWS, lang)
    assert dropped is None and len(note) == 3
    assert [line["product_id"] for line in note] == ["462775", "462921", "463335"]
    assert note[0]["date"] == "2026-11-16" and note[0]["product_name"].startswith("Valio Eila")
    assert note[2]["risk"] == "UNKNOWN"


def test_pick_orders_short_by_shortage_then_unknown_and_drops_kitchen_detail():
    rows = pick([{**ROWS[2], "row": None, "by_kitchen": [{"kitchen_name": "Hotel One"}]},
                 {**ROWS[1], "row": None}, {**ROWS[0], "row": None}])
    assert [r["product_id"] for r in rows] == ["462775", "462921", "463335"]
    assert [r["row"] for r in rows] == [0, 1, 2]
    assert "by_kitchen" not in json.dumps(rows) and "Hotel One" not in json.dumps(rows)
    many = pick([{**ROWS[0], "product_id": str(i), "shortage": str(i)} for i in range(12)])
    assert len(many) == 8 and many[0]["product_id"] == "11"


@pytest.mark.parametrize("unit, expected", [
    ("PCS", ["6025", "230", "5795"]),      # 6024, 230, 5795 did not add up (#1767)
    ("ST", ["6025", "230", "5795"]),
    ("KG", ["6024.1", "229.5", "5794.6"]),
    ("L", ["6024.1", "229.5", "5794.6"]),
])
@pytest.mark.parametrize("lang", ["en", "fi"])
def test_note_rounds_once_for_model_and_checker_without_changing_source(unit, expected, lang):
    source = {**ROWS[0], "unit": unit, "demand": "6024.083", "available": "229.5",
              "shortage": "5794.583", "suggested_buy": "5794.583"}
    before = copy.deepcopy(source)
    rows = pick([source])
    assert [rows[0][k] for k in ("demand", "available", "suggested_buy")] == expected
    nums = [v.replace(".", ",") if lang == "fi" else v for v in expected]
    text = (f"Tarve {nums[0]} {unit}, saatavilla {nums[1]} {unit}, osta {nums[2]} {unit}."
            if lang == "fi" else f"Demand {nums[0]} {unit}, available {nums[1]} {unit}, buy {nums[2]} {unit}.")
    answer = {"lines": [{"row": 0, "product_id": source["product_id"], "text": text, "numbers": nums}]}
    note, dropped = check(answer, rows, lang)
    assert dropped is None and len(note) == 1
    assert source == before
    unrounded = "6024,083" if lang == "fi" else "6024.083"
    answer["lines"][0].update(text=f"{unrounded} {unit}", numbers=[unrounded])
    assert check(answer, rows, lang) == (None, "NUMBER_NOT_IN_ROW")


def test_note_rounding_preserves_unknowns_kitchen_count_and_original_priority():
    unknown = {**ROWS[2], "unit": "PCS", "demand": "380.5", "available": None,
               "shortage": None, "suggested_buy": None, "kitchens": 3}
    short = {**ROWS[0], "unit": "L", "product_id": "a", "shortage": "10.01"}
    larger = {**short, "product_id": "z", "shortage": "10.04"}
    rows = pick([unknown, short, larger])
    assert [r["product_id"] for r in rows] == ["z", "a", unknown["product_id"]]
    assert rows[0]["shortage"] == rows[1]["shortage"] == "10.1"       # a gap rounds up (#1730)
    assert rows[2]["demand"] == "381" and rows[2]["kitchens"] == 3
    assert all(rows[2][k] is None for k in ("available", "shortage", "suggested_buy"))


@pytest.mark.parametrize("unit, demand, available, shortage", [
    ("PCS", "6024.083", "229.5", "5794.583"), ("ST", "12.5", "3.5", "9"), ("PCS", "5.04", "5", "0.04"),
    ("KG", "6024.083", "229.5", "5794.583"), ("L", "1250", "1012.44", "237.56"), ("KG", "0.44", "0.4", "0.04"),
    ("BOX", "10.25", "4.125", "6.125"),
])
def test_the_printed_shortage_adds_up_and_buy_keeps_the_source_recommendation(unit, demand, available, shortage):
    """#1767: "Demand 6024, available 230, buy 5795" was each figure rounded on its own."""
    whole = str(Decimal(shortage).to_integral_value(rounding="ROUND_CEILING"))
    row = pick([{**ROWS[0], "unit": unit, "demand": demand, "available": available,
                 "shortage": shortage, "suggested_buy": whole}])[0]
    assert Decimal(row["demand"]) - Decimal(row["available"]) == Decimal(row["shortage"])
    assert row["suggested_buy"] == whole and Decimal(row["suggested_buy"]) >= Decimal(row["shortage"])
    assert Decimal(row["available"]) >= 0
    assert abs(Decimal(row["demand"]) - Decimal(demand)) < 1 and abs(Decimal(row["available"]) - Decimal(available)) < 1


def test_one_product_on_many_days_is_one_row_with_the_days_summed():
    """#1767: rye bread stood in the note seven times, once per day."""
    days = [{**ROWS[0], "product_id": "rye", "unit": "PCS", "date": f"2026-11-{16 + i}", "demand": "100.3",
             "available": "40.1", "shortage": "60.2", "suggested_buy": "61", "kitchens": 2,
             "by_kitchen": [{"kitchen_id": "K1", "demand": "50"}, {"kitchen_id": f"K{2 + i % 2}", "demand": "50.3"}]}
            for i in range(7)]
    before = copy.deepcopy(days)
    other = {**ROWS[1], "date": "2026-11-18"}
    unknown = [{**ROWS[2], "date": f"2026-11-{17 + i}", "kitchens": 3} for i in range(2)]
    rows = pick([*reversed(days), other, *unknown])
    assert [r["product_id"] for r in rows] == ["rye", other["product_id"], ROWS[2]["product_id"]]
    assert [r["row"] for r in rows] == [0, 1, 2]
    rye = rows[0]
    assert rye["date"] == "2026-11-16" and rye["risk"] == "SHORT" and rye["kitchens"] == 3
    assert (rye["demand"], rye["available"], rye["shortage"], rye["suggested_buy"]) == ("703", "281", "422", "427")
    assert rows[2]["demand"] == "761" and rows[2]["kitchens"] == 3 and rows[2]["date"] == "2026-11-17"
    assert days == before and "by_kitchen" not in json.dumps(rows)


@pytest.mark.parametrize("lang", ["en", "fi"])
def test_note_and_table_share_the_rounded_buy_without_replacing_it_with_the_gap(lang):
    source = {**ROWS[1], "demand": "1250", "available": "1012.44", "shortage": "237.56",
              "suggested_buy": "238", "unit": "L"}
    rows = pick([source])
    assert rows[0]['shortage'] == '237.6' and rows[0]['suggested_buy'] == source['suggested_buy']
    gap = '237,6' if lang == 'fi' else '237.6'
    text = (f"Vaje {gap} L, ostoehdotus 238 L, pyöristetty päivittäin."
            if lang == 'fi' else f"Shortage {gap} L; suggested buy 238 L, rounded up per day.")
    answer = {'lines': [{'row': 0, 'product_id': source['product_id'], 'text': text,
                         'numbers': [gap, '238']}]}
    assert check(answer, rows, lang)[1] is None


def test_a_product_with_short_and_unknown_days_is_one_short_row_of_its_short_days():
    short = {**ROWS[0], "unit": "L", "date": "2026-11-17"}
    unknown = {**short, "date": "2026-11-16", "available": None, "shortage": None, "suggested_buy": None,
               "risk": "UNKNOWN"}
    rows = pick([unknown, short])
    assert len(rows) == 1 and rows[0]["risk"] == "SHORT" and rows[0]["date"] == "2026-11-17"
    assert (rows[0]["demand"], rows[0]["available"], rows[0]["suggested_buy"]) == ("2400", "1700", "700")


def test_a_correct_number_moved_to_another_product_drops_the_note():
    """Aron's review: "1250 L" is a real number, but of the cream row, not the milk row."""
    moved = with_line(0, text="Demand 1250 L, available 1700 L, suggested buy 700 L.",
                      numbers=["1250", "1700", "700"])
    assert check(moved, ROWS, "en") == (None, "NUMBER_NOT_IN_ROW")


def test_a_line_about_a_product_that_is_not_in_the_rows_drops_the_note():
    assert check(with_line(0, product_id="999999"), ROWS, "en") == (None, "PRODUCT_MISMATCH")
    assert check(with_line(0, row=7), ROWS, "en") == (None, "ROW_UNKNOWN")


def test_a_number_of_its_own_drops_the_note():
    own = with_line(0, text="Demand 2400 L, available 1700 L, buy about 750 L.", numbers=["2400", "1700", "750"])
    assert check(own, ROWS, "en") == (None, "NUMBER_NOT_IN_ROW")


def test_unknown_availability_is_never_written_as_a_gap():
    """Aron's review: an UNKNOWN row must read as "unknown, check", never as a gap of the
    whole forecast. Demand 380.5 KG for the potato row must not appear in its line."""
    gap = with_line(2, text="Short by 380.5 KG for 3 kitchens.", numbers=["380.5", "3"])
    assert check(gap, ROWS, "en") == (None, "GAP_FOR_UNKNOWN")
    other = with_line(2, text="Unknown, 40 KG may be missing.", numbers=["40"])
    assert check(other, ROWS, "en") == (None, "NUMBER_NOT_IN_ROW")


def test_number_words_a_wrong_numbers_list_and_a_repeated_row_drop_the_note():
    words = with_line(0, text="Demand 2400 L, available 1700 L, buy seven hundred L.", numbers=["2400", "1700"])
    assert check(words, ROWS, "en") == (None, "NUMBER_WORD")
    listed = with_line(0, numbers=["2400", "1700"])
    assert check(listed, ROWS, "en") == (None, "NUMBERS_LIST_MISMATCH")
    twice = copy.deepcopy(reply())
    twice["lines"][1] = copy.deepcopy(twice["lines"][0])
    assert check(twice, ROWS, "en") == (None, "ROW_REPEATED")
    assert check({"lines": "x"}, ROWS, "en") == (None, "REPLY_INVALID")


def test_finnish_number_format_passes_in_a_finnish_note():
    fi = copy.deepcopy(reply("fi"))
    fi["lines"][0].update(text="Tarve 2 400 L, saatavilla 1 700 L, ostoehdotus 700 L.", numbers=["2 400", "1 700", "700"])
    fi["lines"][1].update(text="Tarve 1 250 L, saatavilla 1012,4 L, ostoehdotus 238 L.", numbers=["1 250", "1012,4", "238"])
    assert check(fi, ROWS, "fi")[1] is None


# ---- the route --------------------------------------------------------------------------

def app_for(env, worker):
    _, fake, db = env
    gw = Gateway(db, ValioClient("test-key", transport=fake.transport, ttl=0, now=lambda: NOW), now=lambda: NOW)
    return TestClient(create_app(gw, buying_note_worker=worker))


def echo_worker(calls):
    """A worker that writes one correct line per row, from the row's own values."""
    async def worker(supplier_id, lang, rows):
        calls.append((supplier_id, lang, rows))
        lines = []
        for r in rows:
            if r["risk"] == "SHORT":
                text, nums = f"Demand {r['demand']} L, available {r['available']} L, buy {r['suggested_buy']} L.", \
                    [r["demand"], r["available"], r["suggested_buy"]]
            else:
                text, nums = f"Available amount unknown for {r['kitchens']} kitchens; check it.", [str(r["kitchens"])]
            lines.append({"row": r["row"], "product_id": r["product_id"], "text": text, "numbers": nums})
        return {"model": "nemotron-3.5-super-vl", "lines": lines}
    return worker


def test_route_shows_a_checked_note_caches_it_and_never_sends_kitchen_names(env):
    _, _, db = env
    seed(db)
    calls = []
    client = app_for(env, echo_worker(calls))
    r = client.get(URL, headers=HUMAN)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["dropped"] is None and data["cached"] is False and data["note"]
    assert {line["risk"] for line in data["note"]} <= {"SHORT", "UNKNOWN"}
    assert data["rows_used"] == len(calls[0][2]) == len(data["note"])
    sent = json.dumps(calls[0][2])
    assert "by_kitchen" not in sent and "Hotel One" not in sent and "School Two" not in sent
    again = client.get(URL, headers=HUMAN).json()
    assert again["cached"] is True and again["note"] == data["note"] and len(calls) == 1
    fi = client.get(URL + "&lang=fi", headers=HUMAN).json()
    assert fi["lang"] == "fi" and len(calls) == 2                      # the cache key holds the language


def test_route_drops_the_note_when_a_line_fails_and_writes_nothing(env):
    _, _, db = env
    seed(db)
    audit_before = db.audit_log.count_documents({})
    async def worker(supplier_id, lang, rows):
        good = await echo_worker([])(supplier_id, lang, rows)
        good["lines"][0]["text"] += " Also 99999 L more."
        return good
    data = app_for(env, worker).get(URL, headers=HUMAN).json()
    assert data["note"] is None and data["dropped"] == "NUMBER_NOT_IN_ROW"
    assert db.audit_log.count_documents({}) == audit_before
    assert db.supplier_offers.count_documents({}) == 0 and db.orders.count_documents({}) == 0


def test_route_scope_language_and_worker_errors(env):
    from gateway import users
    _, _, db = env
    seed(db)
    async def down(*args):
        raise GatewayError(503, "BUYING_NOTE_UNAVAILABLE", "down")
    client = app_for(env, down)
    assert client.get(URL + "&lang=sv", headers=HUMAN).status_code == 422
    assert client.get(URL, headers=AGENT).status_code == 403
    r = client.get(URL, headers=HUMAN)
    assert r.status_code == 503 and r.json()["error"]["code"] == "BUYING_NOTE_UNAVAILABLE"
    users.create_user(db, "chef@k1.example", "chef pass 1234", name="C", role="approver", kitchen_id="K1")
    client.post("/v1/auth/login", json={"email": "chef@k1.example", "password": "chef pass 1234"})
    r = client.get(URL)
    assert r.status_code == 403 and r.json()["error"]["code"] == "SCOPE_REQUIRED"


def test_route_with_no_risk_rows_makes_no_model_call(env):
    _, _, db = env
    seed(db)
    db.forecasts.delete_many({})
    calls = []
    data = app_for(env, echo_worker(calls)).get(URL, headers=HUMAN).json()
    assert data["note"] == [] and data["rows_used"] == 0 and calls == []


def test_dropped_note_cools_down_then_recovers_while_valid_notes_keep_five_minutes(env, monkeypatch):
    import gateway.buying_note as module
    original_mount = module.mount_buying_note
    clock = [0.0]
    monkeypatch.setattr(module, 'mount_buying_note',
                        lambda *a, **kw: original_mount(*a, **kw, clock=lambda: clock[0]))
    seed(env[2])
    calls = []
    good = echo_worker(calls)
    async def worker(*args):
        reply = await good(*args)
        if len(calls) == 1:
            reply['lines'][0]['text'] += ' Also 99999 L.'
        return reply
    client = app_for(env, worker)
    first = client.get(URL, headers=HUMAN).json()
    assert first['note'] is None and not first['cached']
    clock[0] = 29.9
    assert client.get(URL, headers=HUMAN).json()['cached'] and len(calls) == 1
    clock[0] = 30
    recovered = client.get(URL, headers=HUMAN).json()
    assert recovered['note'] and not recovered['cached'] and len(calls) == 2
    clock[0] = 329.9
    assert client.get(URL, headers=HUMAN).json()['cached'] and len(calls) == 2
    clock[0] = 330
    assert not client.get(URL, headers=HUMAN).json()['cached'] and len(calls) == 3
