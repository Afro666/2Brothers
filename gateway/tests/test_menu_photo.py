"""Menu reads are untrusted; recipes and the engine alone size a pending proposal."""
import asyncio
import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.service import Gateway, GatewayError
from gateway.tests.test_gateway_app import AGENT, HUMAN, K, NOW, env  # noqa: F401
from gateway.tests.test_plan_proposal import WINDOW, setup
from gateway.valio_client import ValioClient

PHOTO = base64.b64encode(b'\x89PNG synthetic menu').decode()
BODY = {**WINDOW, 'image_base64': PHOTO, 'idempotency_key': 'photo-1'}
READ = {'dishes': [{'day': 'Monday', 'dish': 'Latte', 'covers': 50},
                   {'day': 'Tuesday', 'dish': 'Unknown handwritten meal', 'covers': 10}]}


def app_for(env, worker):
    _, fake, db = env
    gw = Gateway(db, ValioClient('test-key', transport=fake.transport, ttl=0, now=lambda: NOW), now=lambda: NOW)
    return create_app(gw, menu_photo_worker=worker)


def test_photo_sizes_only_matched_dishes_keeps_plan_and_replays_without_model(env):
    client, _, db = env
    setup(client)
    before = list(db.menu_plans.find())
    calls = []
    async def worker(kitchen, image):
        calls.append((kitchen, image))
        return READ
    client = TestClient(app_for(env, worker))
    result = client.post(K + '/menu-photo', headers=HUMAN, json=BODY)
    assert result.status_code == 200, result.text
    result = result.json()
    proposal = client.get(K + '/proposals/' + result['proposal']['proposal_id'], headers=HUMAN).json()
    assert proposal['status'] == 'READY' and proposal['request']['made_by'] == 'menu_plan'
    assert [(n['product_id'], n['quantity']) for n in proposal['request']['needs']] == [('462775', '10')]
    assert result['dishes'][1]['status'] == 'NOT_KNOWN'
    assert list(db.menu_plans.find()) == before
    assert db.orders.count_documents({}) == 0
    again = client.post(K + '/menu-photo', headers=HUMAN, json=BODY)
    assert again.json()['proposal'] == result['proposal'] and len(calls) == 1
    for change in ({'to': '2026-11-21'}, {'covers': 99}, {'image_base64': base64.b64encode(b'\x89PNG changed').decode()}):
        r = client.post(K + '/menu-photo', headers=HUMAN, json={**BODY, **change})
        assert r.status_code == 409, r.text
    assert len(calls) == 1 and db.proposals.count_documents({}) == 1
    audit = client.get(K + '/audit', headers=HUMAN).json()
    assert 'Unknown handwritten meal' not in json.dumps(audit)
    assert PHOTO not in json.dumps(audit)
    assert PHOTO not in str(list(db.proposals.find()))


@pytest.mark.parametrize('dish,day,covers,stock,status,reason', [
    ('Unlisted recipe', 'Monday', 20, None, 422, 'NOTHING_MATCHED'),
    ('Latte', 'Monday', 'unknown', None, 200, 'NOT_SIZED'),
    ('Latte', 'unknown', 20, None, 200, 'NOT_SIZED'),
    ('Latte', 'Monday', 20, '500', 200, 'NOTHING_NEEDED')])
def test_unmatched_unsized_and_stock_covered_do_not_create_proposals(env, dish, day, covers, stock, status, reason):
    setup(env[0], None if stock is None else [{'product_id': '462775', 'on_hand': stock, 'unit': 'L'}])
    async def worker(*args):
        return {'dishes': [{'dish': dish, 'day': day, 'covers': covers}]}
    r = TestClient(app_for(env, worker)).post(K + '/menu-photo', headers=HUMAN, json=BODY)
    assert r.status_code == status, r.text
    if status == 422:
        assert r.json()['error']['code'] == reason
        assert r.json()['error']['dishes'][0]['status'] == 'NOT_KNOWN'
    else:
        assert r.json()['proposal'] is None and r.json()['no_proposal_reason'] == reason
    assert env[2].proposals.count_documents({}) == 0
    assert env[2].orders.count_documents({}) == 0


def test_no_proposal_success_is_replayed_and_consumes_key(env):
    setup(env[0])
    calls = []
    async def worker(*args):
        calls.append(1)
        return {'dishes': [{'dish': 'Latte', 'day': 'Monday', 'covers': 'unknown'}]}
    client = TestClient(app_for(env, worker))
    first = client.post(K + '/menu-photo', headers=HUMAN, json=BODY)
    assert first.json()['no_proposal_reason'] == 'NOT_SIZED'
    second = client.post(K + '/menu-photo', headers=HUMAN, json=BODY)
    assert second.json()['dishes'] == first.json()['dishes'] and len(calls) == 1
    changed = client.post(K + '/menu-photo', headers=HUMAN, json={**BODY, 'covers': 10})
    assert changed.status_code == 409 and len(calls) == 1


@pytest.mark.parametrize('change', [{'from': 'bad'}, {'to': '2027-01-01'}, {'covers': True},
                                    {'covers': -1}, {'idempotency_key': ''}, {'image_base64': 'bad'}])
def test_bad_input_and_agent_scope_do_not_reach_model(env, change):
    async def worker(*args):
        pytest.fail('invalid request reached model')
    client = TestClient(app_for(env, worker))
    assert client.post(K + '/menu-photo', headers=HUMAN, json={**BODY, **change}).status_code == 422
    assert client.post(K + '/menu-photo', headers=AGENT, json=BODY).status_code == 403


@pytest.mark.parametrize('reply', [[], {'dishes': [{'day': 'Monday', 'dish': 'Latte', 'covers': 50, 'quantity': 100}]},
                                   {'dishes': [{'day': 'Monday', 'dish': 'Latte', 'covers': True}]}])
def test_invalid_worker_answer_is_refused(env, reply):
    setup(env[0])
    async def worker(*args):
        return reply
    r = TestClient(app_for(env, worker)).post(K + '/menu-photo', headers=HUMAN, json=BODY)
    assert r.status_code == 502 and r.json()['error']['code'] == 'VISION_REPLY_INVALID'
    assert env[2].proposals.count_documents({}) == 0


def test_busy_read_and_timeout_release_guard_without_retry(env):
    setup(env[0])
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def worker(*args):
            calls.append(1)
            entered.set()
            await release.wait()
            raise GatewayError(504, 'VISION_TIMEOUT', 'timeout')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(env, worker)), base_url='http://test') as client:
            first = asyncio.create_task(client.post(K + '/menu-photo', headers=HUMAN, json=BODY))
            await entered.wait()
            busy = await client.post(K + '/menu-photo', headers=HUMAN, json=BODY)
            assert busy.status_code == 429 and busy.json()['error']['code'] == 'MENU_PHOTO_BUSY'
            release.set()
            assert (await first).status_code == 504
            assert len(calls) == 1
            assert (await client.post(K + '/menu-photo', headers=HUMAN, json=BODY)).status_code == 504
            assert len(calls) == 2
    asyncio.run(run())


def test_openapi_documents_the_upload_body(env):
    schema = app_for(env, None).openapi()['paths'][K.replace('demo-kitchen', '{kitchen_id}') + '/menu-photo']['post']
    assert 'requestBody' in schema
