"""Versioned delivery observations (#1304): current-only history and one-tap replay."""

from datetime import datetime, timezone

import pytest

pytest.importorskip("mongomock")
import mongomock  # noqa: E402

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
