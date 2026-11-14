import asyncio
from datetime import date
import json

import httpx
import pytest

from agent.menu_photo import match_dishes, menu_day
from agent.menu_photo_service import MenuPhotoReader
from agent.receiving import RecordedModel
from agent.service import WorkerError, create_app

START, END = date(2026, 11, 16), date(2026, 11, 22)
RECIPES = [{'recipe_id': 'soup', 'name': 'Salmon soup'}]
PHOTO = b'\x89PNG synthetic fixture'


def test_matching_is_unambiguous_and_uses_only_printed_or_user_supplied_covers():
    dishes = match_dishes({'dishes': [
        {'day': 'Monday', 'dish': '  SALMON  soup ', 'covers': 120},
        {'day': 'Tuesday', 'dish': 'Salmon soup', 'covers': 'unknown'},
        {'day': 'Friday', 'dish': 'Not a recipe', 'covers': 80},
        {'day': 'unknown', 'dish': 'Salmon soup', 'covers': 20}]}, RECIPES, START, END)
    assert dishes[0]['day'] == '2026-11-16' and dishes[0]['in_proposal'] is True
    assert dishes[1]['covers'] is None and dishes[1]['in_proposal'] is False
    assert dishes[2]['status'] == 'NOT_KNOWN' and dishes[2]['recipe_id'] is None
    assert dishes[3]['day'] is None and dishes[3]['in_proposal'] is False
    supplied = match_dishes({'dishes': [{'day': 'ma', 'dish': 'Salmon soup', 'covers': 'unknown'}]}, RECIPES, START, END, 50)
    assert supplied[0]['covers'] == 50
    duplicate = match_dishes({'dishes': [{'day': 'Monday', 'dish': 'Salmon soup', 'covers': 1}]},
                            RECIPES + [{'recipe_id': 'another', 'name': 'salmon soup'}], START, END)
    assert duplicate[0]['status'] == 'NOT_KNOWN'


def test_ambiguous_or_outside_days_are_never_guessed():
    assert menu_day('maanantai', START, END) == '2026-11-16'
    assert menu_day('2026-12-01', START, END) is None
    assert menu_day('Monday', START, date(2026, 11, 30)) is None


def test_reader_uses_one_schema_constrained_photo_call():
    model = RecordedModel({'content': json.dumps({'dishes': [{'day': 'Monday', 'dish': 'Salmon soup', 'covers': 120}]})})
    model.close = lambda: asyncio.sleep(0)
    result = asyncio.run(MenuPhotoReader(WorkerError, model_factory=lambda: model).read(PHOTO))
    assert result['dishes'][0]['covers'] == 120
    assert len(model.requests) == 1
    message = model.requests[0]['messages'][1]['content']
    assert message[1]['type'] == 'image_url' and message[1]['image_url']['url'].startswith('data:image/png;base64,')


@pytest.mark.parametrize('covers', [True, -1, None, '120'])
def test_invalid_model_fields_are_refused_whole(covers):
    model = RecordedModel({'content': json.dumps({'dishes': [{'day': 'Monday', 'dish': 'Salmon soup', 'covers': covers}]})})
    model.close = lambda: asyncio.sleep(0)
    with pytest.raises(WorkerError) as err:
        asyncio.run(MenuPhotoReader(WorkerError, model_factory=lambda: model).read(PHOTO))
    assert err.value.code == 'VISION_REPLY_INVALID'


def test_worker_auth_and_kitchen_scope(monkeypatch):
    import base64
    monkeypatch.setenv('GATEWAY_AGENT_TOKEN', 'test-agent')
    monkeypatch.setenv('GATEWAY_KITCHEN_ID', 'k1')
    class Reader:
        async def read(self, image):
            return {'dishes': []}
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(menu_photo=Reader())), base_url='http://worker') as client:
            body = {'kitchen_id': 'k1', 'image_base64': base64.b64encode(PHOTO).decode()}
            assert (await client.post('/menu-photo', json=body)).status_code == 401
            assert (await client.post('/menu-photo', headers={'Authorization': 'Bearer test-agent'}, json={**body, 'kitchen_id': 'other'})).status_code == 403
    asyncio.run(run())
