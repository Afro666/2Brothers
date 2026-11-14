"""Versioned delivery observations (#1304): current-only history and one-tap replay."""

from datetime import datetime, timezone

import pytest

pytest.importorskip("mongomock")
import mongomock  # noqa: E402
from pymongo.errors import AutoReconnect  # noqa: E402

from store import delivery_results  # noqa: E402

NOW = datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc)
LINE = {"supplier_id": "sup-1", "product_id": "p-1", "status": "SHORT",
        "ordered": "40", "delivered": "30", "unit": "ST"}


def db():
    return mongomock.MongoClient(tz_aware=True)["test"]


def photo(**over):
    values = dict(kitchen_id="k-1", order_id="order-1", supplier_id="sup-1",
                  requested_date="2026-11-16", ordered_at="2026-11-14T10:00:00Z",
                  delivery_date="2026-11-17", checked_by="chef-1", checked_at=NOW,
                  source="photo", lines=[LINE], not_ordered=[])
    values.update(over)
    return delivery_results.save_observation(db(), **values)


def test_a_check_saves_the_contract_shape_and_an_unknown_date_is_null():
    database = db()
    result = delivery_results.save_observation(
        database, kitchen_id="k-1", order_id="order-1", supplier_id="sup-1",
        requested_date="2026-11-16", ordered_at="2026-11-14T10:00:00Z",
        delivery_date="unknown", checked_by="chef-1", checked_at=NOW, source="photo",
        lines=[LINE], not_ordered=[{"supplier_id": "sup-1", "product_id": "p-2",
                                    "status": "EXTRA", "delivered": "2", "unit": "KI"}])
    assert result["result_id"].startswith("dr-") and result["revision"] == 1
    assert (result["delivery_date"], result["days_late"]) == (None, None)
    assert result["lines"] == [LINE]
    assert result["not_ordered"][0] == {"supplier_id": "sup-1", "product_id": "p-2",
                                        "status": "EXTRA", "delivered": "2", "unit": "KI"}
    assert "_id" not in result


def test_a_recheck_appends_revision_two_and_history_returns_only_the_current_one():
    database = db()
    first = delivery_results.save_observation(
        database, kitchen_id="k-1", order_id="order-1", supplier_id=None,
        requested_date="2026-11-16", ordered_at=None, delivery_date="2026-11-17",
        checked_by="chef-1", checked_at=NOW, source="photo",
        lines=[{**LINE, "supplier_id": "sup-1"}, {**LINE, "supplier_id": "sup-2",
                                                   "product_id": "p-2"}], not_ordered=[])
    second = delivery_results.save_observation(
        database, kitchen_id="k-1", order_id="order-1", supplier_id=None,
        requested_date="2026-11-16", ordered_at=None, delivery_date="2026-11-18",
        checked_by="chef-2", checked_at=datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc),
        source="photo", lines=[{**LINE, "status": "RECEIVED", "delivered": "40",
                                "supplier_id": "sup-1"}], not_ordered=[])
    assert (second["result_id"], second["revision"]) == (first["result_id"], 2)
    assert database.delivery_results.count_documents({}) == 2        # immutable versions
    assert [row["revision"] for row in delivery_results.delivery_history(database, "k-1")] == [2]
    assert [[line["product_id"] for line in row["lines"]]
            for row in delivery_results.delivery_history(
                database, "k-1", supplier_id="sup-1", product_id="p-1")] == [["p-1"]]
    assert delivery_results.delivery_history(database, "k-1", supplier_id="sup-2") == []


def test_manual_replay_returns_the_old_result_even_after_a_later_check():
    database = db()
    line = {**LINE, "status": "RECEIVED", "delivered": "40"}
    first, created = delivery_results.save_received(
        database, kitchen_id="k-1", order_id="order-1", idempotency_key="received-1",
        delivery_date="2026-11-17", supplier_id="sup-1", requested_date="2026-11-16",
        ordered_at="2026-11-14T10:00:00Z", checked_by="chef-1", checked_at=NOW,
        lines=[line])
    assert created is True
    delivery_results.save_observation(
        database, kitchen_id="k-1", order_id="order-1", supplier_id="sup-1",
        requested_date="2026-11-16", ordered_at="2026-11-14T10:00:00Z",
        delivery_date="2026-11-18", checked_by="chef-1",
        checked_at=datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc), source="photo",
        lines=[{**line, "status": "SHORT", "delivered": "30"}], not_ordered=[])
    replay, created_again = delivery_results.save_received(
        database, kitchen_id="k-1", order_id="order-1", idempotency_key="received-1",
        delivery_date="2026-11-17", supplier_id="sup-1", requested_date="2026-11-16",
        ordered_at="2026-11-14T10:00:00Z", checked_by="chef-1", checked_at=NOW,
        lines=[line])
    assert (replay, created_again) == (first, False)
    assert database.delivery_results.count_documents({}) == 2  # replay added no statistics row
    with pytest.raises(delivery_results.IdempotencyConflict):
        delivery_results.save_received(
            database, kitchen_id="k-1", order_id="order-1", idempotency_key="received-1",
            delivery_date="2026-11-18", supplier_id="sup-1", requested_date="2026-11-16",
            ordered_at="2026-11-14T10:00:00Z", checked_by="chef-1", checked_at=NOW,
            lines=[line])


def _check(database, **over):
    values = dict(kitchen_id="k-1", order_id="order-1", supplier_id="sup-1",
                  requested_date="2026-11-16", ordered_at="2026-11-14T10:00:00Z",
                  delivery_date="2026-11-17", checked_by="chef-1", checked_at=NOW,
                  source="photo", lines=[LINE], not_ordered=[])
    values.update(over)
    return delivery_results.save_observation(database, **values)


def test_two_saves_at_the_same_revision_store_revisions_one_and_two(monkeypatch):
    database = db()
    real_current = delivery_results._current
    stale = {}

    def racing_current(d, kitchen_id, order_id):
        # The first read of the second save sees what the first save saw: nothing.
        if not stale:
            stale["done"] = True
            return None
        return real_current(d, kitchen_id, order_id)

    first = _check(database)
    monkeypatch.setattr(delivery_results, "_current", racing_current)
    second = _check(database, checked_by="chef-2")
    assert (first["revision"], second["revision"]) == (1, 2)
    assert second["result_id"] == first["result_id"]
    current = database.delivery_result_current.find_one({"order_id": "order-1"})
    assert current["revision"] == 2

    # The same race on a recheck: both read revision 2.
    monkeypatch.setattr(delivery_results, "_current", real_current)
    seen = real_current(database, "k-1", "order-1")
    calls = []

    def stale_current(d, kitchen_id, order_id):
        calls.append(1)
        return dict(seen) if len(calls) == 1 else real_current(d, kitchen_id, order_id)

    _check(database, checked_by="chef-3")
    monkeypatch.setattr(delivery_results, "_current", stale_current)
    fourth = _check(database, checked_by="chef-4")
    assert fourth["revision"] == 4
    assert sorted(r["revision"] for r in database.delivery_results.find()) == [1, 2, 3, 4]


def test_a_refused_conflicting_received_leaves_the_current_version_unchanged(monkeypatch):
    database = db()
    line = {**LINE, "status": "RECEIVED", "delivered": "40"}
    first, _ = delivery_results.save_received(
        database, kitchen_id="k-1", order_id="order-1", idempotency_key="received-1",
        delivery_date="2026-11-17", supplier_id="sup-1", requested_date="2026-11-16",
        ordered_at=None, checked_by="chef-1", checked_at=NOW, lines=[line])
    before = database.delivery_result_current.find_one({"order_id": "order-1"})

    # A racer whose first key lookup ran before the first save reserved the key.
    real_find_one = mongomock.collection.Collection.find_one
    missed = []

    def racing_find_one(self, *args, **kwargs):
        if self.name == delivery_results.KEYS and not missed:
            missed.append(1)
            return None
        return real_find_one(self, *args, **kwargs)

    monkeypatch.setattr(mongomock.collection.Collection, "find_one", racing_find_one)
    with pytest.raises(delivery_results.IdempotencyConflict):
        delivery_results.save_received(
            database, kitchen_id="k-1", order_id="order-1", idempotency_key="received-1",
            delivery_date="2026-11-18", supplier_id="sup-1", requested_date="2026-11-16",
            ordered_at=None, checked_by="chef-1", checked_at=NOW, lines=[line])
    after = database.delivery_result_current.find_one({"order_id": "order-1"})
    assert (after["result_id"], after["revision"]) == (before["result_id"], 1)
    assert database.delivery_results.count_documents({}) == 1
    assert first["revision"] == 1


def test_only_structured_fields_are_stored():
    result = photo(delivery_date="2026-11-17")
    text = str(result)
    for forbidden in ("ORD-DEMO", "L2611A", "best_before", "image_base64", "note"):
        assert forbidden not in text


def test_unknown_identifiers_and_units_are_stored_as_null():
    result = photo(not_ordered=[{"supplier_id": "unknown", "product_id": "unknown",
                                "status": "UNREADABLE", "delivered": "1", "unit": "unknown"}])
    assert result["not_ordered"] == [{"supplier_id": None, "product_id": None,
                                      "status": "UNREADABLE", "delivered": "1", "unit": None}]


def _received(database, **over):
    values = dict(kitchen_id="k-1", order_id="order-1", idempotency_key="received-new",
                  delivery_date="2026-11-17", supplier_id="sup-1",
                  requested_date="2026-11-16", ordered_at=None, checked_by="chef-1",
                  checked_at=NOW, lines=[{**LINE, "status": "RECEIVED", "delivered": "40"}])
    values.update(over)
    return delivery_results.save_received(database, **values)


def test_failed_final_key_write_recovers_original_after_newer_photo(monkeypatch):
    database = db()
    real_update_one = mongomock.collection.Collection.update_one
    failed = []

    def lose_finalization(self, *args, **kwargs):
        if self.name == delivery_results.KEYS and not failed:
            failed.append(True)
            raise AutoReconnect("lost final key write")
        return real_update_one(self, *args, **kwargs)

    monkeypatch.setattr(mongomock.collection.Collection, "update_one", lose_finalization)
    with pytest.raises(AutoReconnect):
        _received(database)
    original = database[delivery_results.RESULTS].find_one({"source": "manual_complete"})
    newer = _check(database, delivery_date="2026-11-18",
                   checked_at=datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc))

    replay, created = _received(database)
    assert created is False
    assert replay == delivery_results._public(original)
    assert newer["revision"] == 2
    assert database[delivery_results.RESULTS].count_documents({}) == 2
    selector = database[delivery_results.CURRENT].find_one({"order_id": "order-1"})
    assert selector["revision"] == 2
    key = database[delivery_results.KEYS].find_one()
    assert key["revision"] == 1 and "pending" not in key


def test_same_key_overlap_appends_once_and_hides_operation(monkeypatch):
    database = db()
    real_append = delivery_results._append
    replayed = []

    def racing_append(d, observation):
        result = real_append(d, observation)
        if observation.get("_operation_id") and not replayed:
            replayed.append(_received(d))
        return result

    monkeypatch.setattr(delivery_results, "_append", racing_append)
    first, created = _received(database)
    raw = database[delivery_results.RESULTS].find_one()
    assert created is True
    assert database[delivery_results.RESULTS].count_documents({}) == 1
    assert raw["_operation_id"]
    assert "_operation_id" not in first
    assert replayed == [(first, False)]
    assert delivery_results.delivery_history(database, "k-1") == [first]




def test_failed_selector_write_recovers_without_appending_again(monkeypatch):
    database = db()
    original_move = delivery_results._move_current
    def fail(*args, **kwargs):
        raise AutoReconnect("simulated lost selector update")
    monkeypatch.setattr(delivery_results, "_move_current", fail)
    with pytest.raises(AutoReconnect):
        _received(database)
    monkeypatch.setattr(delivery_results, "_move_current", original_move)
    replay, created = _received(database)
    assert created is False and replay["revision"] == 1
    assert database[delivery_results.RESULTS].count_documents({}) == 1
    assert delivery_results.delivery_history(database, "k-1") == [replay]


def test_retry_before_insert_preserves_first_snapshot(monkeypatch):
    database = db()
    real_insert = mongomock.collection.Collection.insert_one
    failed = []

    def fail_once(self, *args, **kwargs):
        if self.name == delivery_results.RESULTS and not failed:
            failed.append(True)
            raise AutoReconnect("before result insert")
        return real_insert(self, *args, **kwargs)

    monkeypatch.setattr(mongomock.collection.Collection, "insert_one", fail_once)
    with pytest.raises(AutoReconnect):
        _received(database)
    replay, created = _received(database, checked_by="chef-2", supplier_id="sup-2",
                                checked_at=datetime(2026, 11, 18, tzinfo=timezone.utc))
    assert created is False and replay["revision"] == 1
    assert replay["checked_by"] == "chef-1" and replay["supplier_id"] == "sup-1"
    assert replay["checked_at"] == "2026-11-17T08:00:00Z"
    assert database[delivery_results.RESULTS].count_documents({}) == 1
    assert delivery_results.delivery_history(database, "k-1") == [replay]
    assert "observation" not in database[delivery_results.KEYS].find_one()


def test_retry_races_before_original_insert_and_returns_same_operation(monkeypatch):
    database = db()
    real_insert = mongomock.collection.Collection.insert_one
    followers = []
    entered = []

    def racing_insert(self, row, *args, **kwargs):
        if self.name == delivery_results.RESULTS and row.get("_operation_id") and not entered:
            entered.append(True)
            # Force the follower onto a different revision. The operation index, rather
            # than just the revision's _id, must stop the original insert afterward.
            _check(database)
            followers.append(_received(database))
        return real_insert(self, row, *args, **kwargs)

    monkeypatch.setattr(mongomock.collection.Collection, "insert_one", racing_insert)
    first, created = _received(database)
    assert created is True and first["revision"] == 2
    assert followers == [(first, False)]
    assert database[delivery_results.RESULTS].count_documents({}) == 2
    assert database[delivery_results.RESULTS].count_documents({"source": "manual_complete"}) == 1
    assert "_operation_id" not in first
    assert delivery_results.delivery_history(database, "k-1") == [first]
    # Sparse indexing must still allow successive observations without an operation.
    photo = _check(database)
    assert photo["revision"] == 3


def test_legacy_pending_key_without_snapshot_fails_safely():
    database = db()
    delivery_results._ensure_indexes(database)
    database[delivery_results.KEYS].insert_one({
        "kitchen_id": "k-1", "idempotency_key": "received-new", "order_id": "order-1",
        "operation_id": "legacy-operation", "pending": True,
        "payload_hash": delivery_results._payload_hash("order-1", "2026-11-17", "received-new")})
    with pytest.raises(RuntimeError, match="no valid stored snapshot"):
        _received(database)
    assert database[delivery_results.RESULTS].count_documents({}) == 0
