from decimal import Decimal as D

from engine.fat import fat_levels_differ, fat_per_100g


def raw(fat):
    return {"synkkaData": {"nutritionalContent": [
        {"id": "FASAT", "value": 0.1, "unit": "GRM", "basisQuantity": 100.0},
        {"id": "FAT", "value": fat, "unit": "GRM", "basisQuantity": 100.0}]}}


def test_fat_comes_from_the_fat_row_only():
    assert fat_per_100g(raw(3.0)) == D("3.0")
    assert fat_per_100g({"synkkaData": {}}) is None
    assert fat_per_100g(None) is None


def test_fat_free_and_three_percent_milk_differ():
    assert fat_levels_differ([D("0"), D("3.0")])
    assert not fat_levels_differ([D("1.5"), D("1.5")])
    assert not fat_levels_differ([D("0"), None])        # unknown says nothing
    assert not fat_levels_differ([D("3.0")])
