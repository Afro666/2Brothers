import mongomock

from agent.memory_cache import KitchenFactsCache
from store.learning_revision import revision


def test_feedback_undo_and_delivery_selection_refresh_facts_before_ttl():
    db = mongomock.MongoClient().test
    cache = KitchenFactsCache(clock=lambda: 0)  # no time passes during these changes
    calls = []
    def read():
        def load():
            calls.append(True)
            return [len(calls)]
        return cache.get('a', 'day', load, revision=revision(db, 'a'))
    assert read() == read() == [1]
    db.feedback.insert_one({'meta': {'kitchen_id': 'other'}})
    assert read() == [1]
    db.feedback.insert_one({'meta': {'kitchen_id': 'a'}})
    assert read() == [2]
    db.learned_overrides.insert_one({'kitchen_id': 'a', 'active': False})
    assert read() == [3]
    db.delivery_results.insert_one({'kitchen_id': 'a', 'revision': 1})
    assert read() == [4]
    db.delivery_result_current.insert_one({'kitchen_id': 'a', 'revision': 1})
    assert read() == [5]
    db.delivery_result_current.update_one({'kitchen_id': 'a'}, {'$set': {'revision': 2}})
    assert read() == [6]
