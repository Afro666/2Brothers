from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from gateway.app import create_app
from gateway.service import GatewayError
from monitor.proposals import apply_notices
from monitor.tests.test_proposals import setup, NOTICES
from store import recalls
from store.audit import list_events, verify_chain

REASON = 'Checked the packs: affected lot is not held here'


def held():
    db, gw, proposal = setup()
    apply_notices(gw, 'hotel', NOTICES)
    current = gw.get_proposal('hotel', proposal['proposal_id'])
    return db, gw, current, current['recall_alerts'][0]['event_id']


def test_human_closes_held_basket_without_clearing_recall():
    db, gw, p, event_id = held()
    gw.reject('hotel', p['proposal_id'], {'reason': 'Use replacement instead'}, human='chef')
    again = gw.reject('hotel', p['proposal_id'], {'reason': 'second reason'}, human='other chef')
    assert again['status'] == 'REJECTED'
    assert db.approvals.find_one({'_id': p['approval_id']})['status'] == 'REJECTED'
    assert '461332' in recalls.blocked_ids(db, 'hotel')
    entries = [e for e in list_events(db, kitchen_id='hotel') if e['event'].get('kind') == 'proposal_rejected']
    assert len(entries) == 1
    assert entries[0]['event']['actor'] == 'chef'
    assert db.orders.count_documents({}) == 0


def test_dismissal_unblocks_new_quote_but_does_not_release_original_or_reapply_on_poll():
    db, gw, p, event_id = held()
    first = gw.dismiss_recall('hotel', event_id, {'reason': REASON}, human='chef')
    assert first['status'] == 'dismissed'
    assert gw.dismiss_recall('hotel', event_id, {'reason': 'A different reason provided'}, human='second') == first
    assert '461332' not in recalls.blocked_ids(db, 'hotel')
    old = gw.get_proposal('hotel', p['proposal_id'])
    assert old['status'] == 'BLOCKED_BY_RECALL'
    assert old['recall_alerts'][0]['status'] == 'dismissed'
    with pytest.raises(GatewayError):
        gw.approve('hotel', p['proposal_id'], {'expected_total': p['expected_total'], 'idempotency_key': 'no'}, human='chef')
    new = gw.create_proposal('hotel', {**p['request'], 'idempotency_key': 'fresh-after-check'}, 'chef')
    assert new['status'] == 'READY' and new['lines'][0]['product_id'] == '461332'
    apply_notices(gw, 'hotel', NOTICES)
    assert gw.get_proposal('hotel', new['proposal_id'])['status'] == 'READY'
    entries = [e for e in list_events(db, kitchen_id='hotel') if e['event'].get('kind') == 'recall_dismissed']
    assert len(entries) == 1 and entries[0]['event']['actor'] == 'chef'
    assert verify_chain(db)['ok'] and db.orders.count_documents({}) == 0


def test_another_active_notice_still_blocks_same_product():
    db, gw, p, event_id = held()
    second = deepcopy(p['recall_alerts'][0])
    second['event_id'] = 'second-notice'
    recalls.remember(db, second)
    gw.dismiss_recall('hotel', event_id, {'reason': REASON}, human='chef')
    assert '461332' in recalls.blocked_ids(db, 'hotel')


@pytest.mark.parametrize('reason', [None, '', 'short', True, [], 'x' * 501])
def test_bad_dismissal_reasons_are_rejected(reason):
    db, gw, _, event_id = held()
    with pytest.raises(GatewayError) as exc:
        gw.dismiss_recall('hotel', event_id, {'reason': reason}, human='chef')
    assert exc.value.status == 422
    assert '461332' in recalls.blocked_ids(db, 'hotel')


def test_http_requires_human_and_scopes_the_event(monkeypatch):
    db, gw, _, event_id = held()
    monkeypatch.setenv('GATEWAY_HUMAN_TOKEN', 'human-test')
    monkeypatch.setenv('GATEWAY_AGENT_TOKEN', 'agent-test')
    client = TestClient(create_app(gw))
    path = f'/v1/kitchens/hotel/recalls/{event_id}/dismiss'
    assert client.post(path, headers={'Authorization': 'Bearer agent-test'}, json={'reason': REASON}).status_code == 403
    headers = {'Authorization': 'Bearer human-test', 'X-User': 'chef'}
    assert client.post(path.replace('/hotel/', '/other/'), headers=headers, json={'reason': REASON}).status_code == 404
    assert client.post(path, headers=headers, json={'reason': REASON}).status_code == 200


def test_rejection_cannot_steal_an_approval_claim():
    # The state transition itself is enough to model the concurrent owner.
    db, gw, p, _ = held()
    db.proposals.update_one({'_id': p['proposal_id']}, {'$set': {'status': 'APPROVING'}})
    with pytest.raises(GatewayError) as error:
        gw.reject('hotel', p['proposal_id'], {'reason': 'too late'}, human='chef')
    assert error.value.code == 'NOT_PENDING'
    assert db.proposals.find_one({'_id': p['proposal_id']})['status'] == 'APPROVING'
