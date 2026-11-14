"""Clearing test proposals before a demo: waiting ones only, never a reject, never an order."""

from datetime import datetime, timedelta, timezone

import pytest

from demo.clear_inbox import clear

mongomock = pytest.importorskip("mongomock")
NOW = datetime(2026, 11, 14, 6, 0, tzinfo=timezone.utc)


def seed(db):
    def proposal(pid, status, minutes_ago, order=None):
        db.approvals.insert_one({"_id": "a-" + pid, "kitchen_id": "demo-kitchen",
                                 "status": "PENDING" if status == "READY" else status})
        db.proposals.insert_one({"_id": pid, "kitchen_id": "demo-kitchen", "status": status, "approval_id": "a-" + pid,
                                 "order_id": order, "created_at": NOW - timedelta(minutes=minutes_ago),
                                 "created_by": "buyer-agent", "request": {"text": "1,000 L lactose-free milk"}})
    proposal("old-1", "READY", 120)
    proposal("old-2", "READY", 60)
    proposal("approved", "APPROVED", 90, order="o1")
    proposal("rejected", "REJECTED", 80)
    proposal("fresh", "READY", -5)                       # created after the cut-off
    db.proposals.insert_one({"_id": "other", "kitchen_id": "other-kitchen", "status": "READY", "order_id": None,
                             "created_at": NOW - timedelta(minutes=30), "request": {}})


def test_dry_run_lists_and_removes_nothing():
    db = mongomock.MongoClient(tz_aware=True)["t"]
    seed(db)
    result = clear(db, "demo-kitchen", NOW, apply=False)
    assert result["found"] == 2 and result["removed"] == 0
    assert db.proposals.count_documents({}) == 6 and db.audit_log.count_documents({}) == 0


def test_apply_removes_only_waiting_proposals_before_the_cut_off():
    db = mongomock.MongoClient(tz_aware=True)["t"]
    seed(db)
    result = clear(db, "demo-kitchen", NOW, apply=True)
    assert result["removed"] == 2 and result["approvals_removed"] == 2
    left = {p["_id"] for p in db.proposals.find({})}
    assert left == {"approved", "rejected", "fresh", "other"}
    assert db.approvals.count_documents({"_id": {"$in": ["a-approved", "a-rejected", "a-fresh"]}}) == 3
    event = db.audit_log.find_one({})["event"]
    assert event["kind"] == "demo_inbox_cleared" and event["proposals_removed"] == 2
    assert clear(db, "demo-kitchen", NOW, apply=True)["removed"] == 0   # nothing left to remove


def test_a_proposal_with_no_request_text_is_listed_and_removed():
    db = mongomock.MongoClient(tz_aware=True)["t"]
    db.proposals.insert_one({"_id": "voice", "kitchen_id": "demo-kitchen", "status": "READY", "order_id": None,
                             "created_at": NOW - timedelta(minutes=10), "request": {"text": None}})
    assert clear(db, "demo-kitchen", NOW, apply=False)["proposals"][0]["text"] == ""
    assert clear(db, "demo-kitchen", NOW, apply=True)["removed"] == 1
    assert db.proposals.count_documents({}) == 0
