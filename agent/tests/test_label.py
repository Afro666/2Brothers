"""A package's allergen label from a photo (#1175): the word table, the comparison and the
reader. A wrong read must never look safe: no green outcome, unknown words and missing
statements are "please check", and "may contain" counts like "contains"."""
import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import ValidationError

from agent.label import code_of, compare, map_terms, product_check
from agent.label_service import LabelReader
from agent.receiving import RecordedModel
from agent.service import WorkerError, create_app
from store.allergen_groups import excluded_allergen_codes

ROOT = Path(__file__).resolve().parents[2]
REPLY = json.loads((ROOT / 'agent' / 'fixtures' / 'label' / 'demo.reply.json').read_text(encoding='utf-8'))
PHOTO = (ROOT / 'demo' / 'label-photo.png').read_bytes()
BUN = {'product_id': 'own-cinnamon-bun', 'names': {'en': 'Cinnamon bun'}, 'units': [{'unit': 'ST', 'gtin': None}],
       'allergens': {'contains': [], 'may_contain': [], 'undeclared': []}, 'allergen_data_known': False}
CREAM = {'product_id': '462921', 'names': {'fi': 'Valio kuohukerma 38 %', 'en': 'Valio whipping cream 38%'},
         'units': [{'unit': 'ST', 'gtin': '06408430012345'}],
         'allergens': {'contains': ['AM', 'ML'], 'may_contain': [], 'undeclared': []}, 'allergen_data_known': True}
PEANUTS = excluded_allergen_codes(['peanuts'])


def read(**kw):
    return {'product_name': 'Valio kuohukerma 38 %', 'ean': '6408430012345', 'statement': 'printed',
            'contains': ['KERMA'], 'may_contain': [], **kw}


def test_the_recorded_demo_label_warns_about_peanuts_in_the_may_contain_line():
    out = compare({k: v for k, v in REPLY.items() if k != 'model'}, BUN, PEANUTS)
    assert out['outcome'] == 'EXCLUDED_ALLERGEN' and out['excluded_hits'] == [{'code': 'AP', 'level': 'MAY_CONTAIN'}]
    assert [c['code'] for c in out['label']['contains']] == ['UW', 'AM', 'AE']
    assert [c['code'] for c in out['label']['may_contain']] == ['AP', 'AS']     # "Voi sisältää" is not butter
    assert out['product_check'] == 'CONFIRMED_BY_NAME' and out['please_check'] == []
    assert out['catalog_allergen_data'] == 'UNKNOWN' and out['differences'] == []


@pytest.mark.parametrize('word,code', [('MAITO', 'AM'), ('maidosta', 'AM'), ('voi', 'AM'), ('kermaa', 'AM'),
                                       ('VEHNÄJAUHO', 'UW'), ('ruisjauho', 'NR'), ('kauraa', 'GO'),
                                       ('kananmunaa', 'AE'), ('manteli', 'SA'), ('manteleita', 'SA'), ('pistaasipähkinöitä', 'ST'), ('pekaaneja', 'SP'), ('pähkinöitä', 'AN'),
                                       ('maapähkinää', 'AP'), ('hasselpähkinä', 'SH'), ('seesaminsiemeniä', 'AS'),
                                       ('mjölk', 'AM'), ('vetemjöl', 'UW'), ('jordnötter', 'AP'), ('senap', 'BM'),
                                       ('milk', 'AM'), ('wheat', 'UW'), ('sesame', 'AS'), ('soijalesitiini', 'AY')])
def test_the_word_table(word, code):
    assert code_of(word) == code


@pytest.mark.parametrize('word', ['kookosmaito', 'munakoiso', 'kookospähkinä', 'sokeri', 'kardemumma'])
def test_compounds_whose_head_is_another_food_do_not_match(word):
    assert code_of(word) is None


def test_the_may_contain_phrase_is_not_read_as_an_allergen():
    for sentence, codes in (('Voi sisältää pieniä määriä maapähkinää ja seesaminsiemeniä.', ['AP', 'AS']),
                            ('Kan innehålla spår av mandel och hasselnötter.', ['SA', 'SH']),
                            ('May contain traces of milk and egg.', ['AM', 'AE'])):
        found, unknown = map_terms([sentence], may=True)
        assert [f['code'] for f in found] == codes and unknown == [], sentence


def test_an_unknown_allergen_word_is_please_check():
    """Aron's added case."""
    out = compare(read(contains=['KERMA', 'LUPIINIJAUHO', 'KASTANJA']), CREAM, ())
    assert out['outcome'] == 'PLEASE_CHECK' and 'WORD_UNKNOWN' in out['please_check']
    assert out['label']['unknown_words'] == ['kastanja']


def test_a_label_of_another_product_is_please_check():
    """Aron's added case: an EAN that is not this product's GTIN, or a name that does not match."""
    assert compare(read(ean='6400000099999'), CREAM, ())['please_check'] == ['PRODUCT_MISMATCH']
    other = compare(read(ean='unknown', product_name='Arla Lactofree milk'), CREAM, ())
    assert other['outcome'] == 'PLEASE_CHECK' and other['please_check'] == ['PRODUCT_NOT_CONFIRMED']
    assert other['message'].startswith('Please check')


def test_no_statement_read_is_never_no_allergens():
    for data in (read(statement='not_printed', contains=[]), read(statement='unreadable', contains=[]),
                 read(contains=[])):
        out = compare(data, CREAM, ())
        assert out['outcome'] == 'PLEASE_CHECK' and out['please_check'] == ['NO_STATEMENT_READ']
        assert 'does not mean there are no allergens' in out['message']


def test_may_contain_an_excluded_allergen_warns_like_contains():
    out = compare(read(may_contain=['Voi sisältää manteleita.']), CREAM, excluded_allergen_codes(['nuts']))
    assert out['outcome'] == 'EXCLUDED_ALLERGEN' and out['excluded_hits'] == [{'code': 'SA', 'level': 'MAY_CONTAIN'}]


def test_both_directions_of_difference_with_the_catalog():
    """Review point 7: the catalog lists an allergen we did not read; the label adds one."""
    out = compare(read(contains=['SOIJA']), CREAM, ())
    assert out['outcome'] == 'DIFFERS'
    kinds = {(d['code'], d['kind']) for d in out['differences']}
    assert kinds == {('AY', 'LABEL_ADDS'), ('AM', 'CATALOG_ADDS'), ('ML', 'CATALOG_ADDS')}
    milk = next(d for d in out['differences'] if d['code'] == 'AM')
    assert milk['text'] == 'The catalog lists milk; we did not read it on the label.'


def test_agreement_is_never_a_safe_outcome_and_groups_do_not_make_noise():
    out = compare(read(), CREAM, ())
    assert out['outcome'] == 'AGREES' and out['differences'] == []          # milk on the label covers lactose
    assert out['message'] == 'The label we read agrees with the catalog. Read the label yourself before use.'
    wheat = dict(CREAM, allergens={'contains': ['AW'], 'may_contain': [], 'undeclared': []})
    assert compare(read(contains=['VEHNÄ']), wheat, ())['differences'] == [
        {'code': 'UW', 'kind': 'LABEL_ADDS', 'text': 'The label lists wheat; the catalog does not.'}]


def test_product_check_rules():
    assert product_check('x', '06408430012345', CREAM) == 'CONFIRMED_BY_EAN'
    assert product_check('Valio kuohukerma 38 % 2 dl', 'unknown', CREAM) == 'CONFIRMED_BY_NAME'
    assert product_check('Cinnamon bun 80 g', '2000000000017', BUN) == 'CONFIRMED_BY_NAME'     # no GTIN: the name
    assert product_check('Rye bread', 'unknown', BUN) == 'NOT_CONFIRMED'


def test_the_photo_never_changes_the_catalog_row():
    before = json.dumps(CREAM, sort_keys=True)
    compare(read(contains=['SOIJA']), CREAM, PEANUTS)
    assert json.dumps(CREAM, sort_keys=True) == before


def test_a_reply_outside_the_schema_is_refused():
    with pytest.raises(ValidationError):
        compare({'product_name': 'x', 'ean': 'x', 'statement': 'maybe', 'contains': [], 'may_contain': []}, CREAM, ())


def test_reader_makes_one_schema_constrained_photo_call():
    model = RecordedModel({'content': json.dumps({k: v for k, v in REPLY.items() if k != 'model'})})
    model.close = lambda: asyncio.sleep(0)
    result = asyncio.run(LabelReader(WorkerError, model_factory=lambda: model).read(PHOTO))
    assert result['statement'] == 'printed' and len(model.requests) == 1 and model.requests[0]['name'] == 'label_photo'


def test_worker_auth_and_kitchen_scope(monkeypatch):
    monkeypatch.setenv('GATEWAY_AGENT_TOKEN', 'test-agent')
    monkeypatch.setenv('GATEWAY_KITCHEN_ID', 'k1')
    class Reader:
        async def read(self, image):
            return {'product_name': 'x', 'ean': 'unknown', 'statement': 'printed', 'contains': [], 'may_contain': []}
    async def run():
        app = create_app(label_photo=Reader())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://worker') as client:
            body = {'kitchen_id': 'k1', 'image_base64': base64.b64encode(PHOTO).decode()}
            auth = {'Authorization': 'Bearer test-agent'}
            assert (await client.post('/label-photo', json=body)).status_code == 401
            assert (await client.post('/label-photo', headers=auth, json={**body, 'kitchen_id': 'k2'})).status_code == 403
            assert (await client.post('/label-photo', headers=auth, json=body)).status_code == 200
    asyncio.run(run())
