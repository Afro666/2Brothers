import mongomock
import pytest
from store.buyer_context import excluded_allergens, product, seed_demo_policy


def test_demo_seed_enables_explicit_policy_only_for_synthetic_demo():
    db = mongomock.MongoClient().test
    with pytest.raises(ValueError):
        seed_demo_policy(db)
    db.kitchens.insert_one({'_id': 'demo-kitchen', 'synthetic': True})
    assert seed_demo_policy(db) == ['AP', 'AN', 'AS']
    assert seed_demo_policy(db) == ['AP', 'AN', 'AS']
    assert db.kitchen_settings.count_documents({}) == 1


@pytest.mark.parametrize('existing', [[], ['AW'], None])
def test_demo_seed_preserves_explicit_settings(existing):
    db = mongomock.MongoClient().test
    db.kitchens.insert_one({'_id': 'demo-kitchen', 'synthetic': True})
    db.kitchen_settings.insert_one({'_id': 'demo-kitchen', 'excluded_allergens': existing, 'engine': {'max_days': 3}})
    seed_demo_policy(db)
    row = db.kitchen_settings.find_one({})
    assert row['excluded_allergens'] == existing
    assert row['engine'] == {'max_days': 3}


def test_catalog_lookup_never_returns_another_kitchens_own_product():
    db = mongomock.MongoClient().test
    db.products.insert_one({'_id': 'private', 'kitchen_id': 'other'})
    assert product(db, 'demo-kitchen', 'private') is None
    assert excluded_allergens(db, 'demo-kitchen') is None
