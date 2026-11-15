"""Plain unit words and a partly covered request in the explanation facts (#1973)."""
from copy import deepcopy

import pytest

from agent.explanation import checked_reply
from agent.tests.test_explanation import reply_for
from gateway.explanation_facts import context
from gateway.explanations import pack_of
from gateway.tests.test_explanation_reason import MILK, NAMES, fact

PACKS = {'463380': {'unit': 'ST', 'size': '1', 'measure': 'L'}}
# The live "confirmed stock only" card of 14 Nov (proposal 17dfba54): no `alternative`,
# `shortfall` 0, the asked 1,000 L only in the request text.
ONLY = {'proposal_id': 'p', 'status': 'READY', 'total_ex_vat': '1849.70', 'expected_total': '2099.41',
        'delivery_fee': '0.00', 'shortfall': '0', 'measure': 'L', 'alternative': None, 'partial_fill': None,
        'request': {'product_ids': ['463380'], 'quantity': '698', 'unit': 'L', 'requested_date': '2026-11-16',
                    'text': '1,000 L lactose-free milk by Monday', 'made_by': 'confirmed_only'},
        'lines': [{'product_id': '463380', 'quantity': '698', 'unit': 'ST', 'unit_price': '2.65',
                   'total': '1849.70', 'unknown_stock': False}]}
# The first card for the same request: 698 L confirmed, 302 L on a product with unknown stock.
PART = {**MILK, 'shortfall': '0', 'measure': 'L',
        'request': {'quantity': '1000', 'unit': 'L', 'text': '1,000 L lactose-free milk by Monday'},
        'partial_fill': {'need': '1000', 'measure': 'L', 'remaining': '302',
                         'now': {'kind': 'NOW', 'quantity': '698', 'measure': 'L'}}}


def all_text(payload):
    return ' '.join(form for f in payload['facts'] for form in f['forms'])


def test_a_pack_size_from_the_catalog_replaces_the_unit_code():
    chosen = fact(context(MILK, NAMES, 'en', PACKS), 'chosen')
    assert chosen['forms'][0] == ('The proposal includes 698 x 1 L packs of Arla Café milk 1 L UHT lactose free '
                                  'at EUR 2.65 per 1 L pack ex VAT; the supplier has confirmed availability.')
    fi = fact(context(MILK, NAMES, 'fi', PACKS), 'chosen')['forms'][0]
    assert fi.startswith('Ehdotuksessa on 698 x 1 L pakkausta tuotetta Arla Café milk 1 L UHT lactose free '
                         'hintaan 2,65 EUR / 1 L pakkaus ilman ALV:a')


def test_without_a_pack_size_the_unit_is_the_sites_word_for_pieces():
    chosen = fact(context(MILK, NAMES, 'en'), 'chosen')['forms'][0]
    assert chosen.startswith('The proposal includes 698 pieces of Arla Café milk 1 L UHT lactose free '
                             'at EUR 2.65 per piece ex VAT')
    one = deepcopy(MILK)
    one['lines'][0].update(quantity='1', unit='KI')
    assert 'includes 1 case of' in all_text(context(one, NAMES, 'en'))
    assert 'on 698 kpl tuotetta' in fact(context(MILK, NAMES, 'fi'), 'chosen')['forms'][0]


@pytest.mark.parametrize('language', ['en', 'fi'])
@pytest.mark.parametrize('proposal', [MILK, ONLY, PART])
def test_no_raw_unit_code_reaches_the_model(language, proposal):
    for packs in (None, PACKS):
        text = all_text(context(proposal, NAMES, language, packs))
        assert ' ST ' not in text and 'per ST' not in text and '/ ST' not in text


def test_a_pack_size_for_another_sales_unit_is_not_used():
    packs = {'463380': {'unit': 'KI', 'size': '12', 'measure': 'L'}}
    assert '698 pieces of' in fact(context(MILK, NAMES, 'en', packs), 'chosen')['forms'][0]


def test_a_measured_unit_stays_as_it_is():
    proposal = deepcopy(MILK)
    proposal['lines'][0]['unit'] = 'KG'
    assert 'includes 698 KG of' in fact(context(proposal, NAMES, 'en', PACKS), 'chosen')['forms'][0]


@pytest.mark.parametrize('product,pack', [
    ({'sales_unit': 'ST', 'base_unit': 'ST', 'net_content': {'value': 1.0, 'unit': 'L'}, 'units': []},
     {'unit': 'ST', 'size': '1', 'measure': 'L'}),
    ({'sales_unit': 'KI', 'base_unit': 'ST', 'net_content': {'value': 0.5, 'unit': 'L'},
      'units': [{'unit': 'ST', 'size_in_base_units': 1}, {'unit': 'KI', 'size_in_base_units': 6}]},
     {'unit': 'KI', 'size': '3', 'measure': 'L'}),
    ({'sales_unit': 'ST', 'base_unit': 'ST', 'net_content': None, 'units': []}, None),
    ({'sales_unit': 'KI', 'base_unit': 'ST', 'net_content': {'value': 1.0, 'unit': 'L'}, 'units': []}, None),
    ({'sales_unit': 'KG', 'base_unit': 'KG', 'net_content': {'value': 1.0, 'unit': 'KG'}, 'units': []}, None),
    ({'sales_unit': 'ST', 'base_unit': 'ST', 'net_content': {'value': 'x', 'unit': 'L'}, 'units': []}, None),
])
def test_the_pack_size_is_read_from_the_catalog_row(product, pack):
    assert pack_of(product) == pack


def test_the_source_hash_follows_the_pack_size():
    assert context(MILK, NAMES, 'en')['source_hash'] != context(MILK, NAMES, 'en', PACKS)['source_hash']


def test_a_changed_pack_size_is_refused_by_the_checker():
    payload = context(MILK, NAMES, 'en', PACKS)
    reply = reply_for(payload)
    reply['sentences'][0]['text'] = reply['sentences'][0]['text'].replace('698 x 1 L', '698 x 2 L')
    reply['sentences'][0]['numbers'] = ['698', '2', '1', '2.65', '1']
    with pytest.raises(ValueError):
        checked_reply(reply, payload['facts'], 'en')


def test_a_partly_covered_request_says_what_is_confirmed_of_what_was_asked():
    payload = context(PART, NAMES, 'en', PACKS)
    chosen, held = fact(payload, 'chosen'), fact(payload, 'held')
    assert chosen['required'] and held['required']
    assert chosen['forms'][0].endswith('; the supplier has confirmed stock for 698 L of the 1000 L asked.')
    assert 'has confirmed availability' not in all_text(payload)
    assert held['forms'][0].startswith('302 L of the 1000 L asked is not covered by confirmed stock; '
                                       'supplier availability is unconfirmed for ')
    assert 'a cheaper option was found, EUR 1560.00 ex VAT' in held['forms'][0]
    fi = context(PART, NAMES, 'fi', PACKS)
    assert 'vahvistanut saatavuuden määrälle 698 L, pyydetty määrä on 1000 L' in fact(fi, 'chosen')['forms'][0]
    assert fact(fi, 'held')['forms'][0].startswith('Pyydetystä määrästä 1000 L jää 302 L ilman vahvistettua varastoa')


def test_a_shortfall_is_stated_against_the_asked_quantity():
    proposal = deepcopy(MILK)
    proposal['lines'] = proposal['lines'][:1]
    proposal.update(alternative=None, shortfall='302', measure='L', request={'quantity': '1000', 'unit': 'L'})
    payload = context(proposal, NAMES, 'en')
    assert fact(payload, 'held')['forms'][0] == '302 L of the 1000 L asked cannot be covered for this date.'
    assert fact(payload, 'chosen')['forms'][0].endswith('; the supplier has confirmed availability for this line.')
    fi = fact(context(proposal, NAMES, 'fi'), 'held')['forms'][0]
    assert fi == 'Pyydetystä määrästä 1000 L jää tälle päivälle kattamatta 302 L.'


def test_the_confirmed_only_card_says_it_covers_part_of_the_request():
    payload = context(ONLY, NAMES, 'en', PACKS)
    held = fact(payload, 'held')
    assert held['required']
    assert held['forms'][0] == ('The request was "1,000 L lactose-free milk by Monday"; this proposal covers only '
                                'the 698 L the supplier confirms in stock, and the rest of the request is not in it.')
    assert fact(payload, 'chosen')['forms'][0].endswith('; the supplier has confirmed availability for this line.')
    fi = fact(context(ONLY, NAMES, 'fi', PACKS), 'held')['forms'][0]
    assert fi == ('Pyyntö oli "1,000 L lactose-free milk by Monday"; tämä ehdotus kattaa vain toimittajan '
                  'vahvistaman määrän 698 L, eikä pyynnön loppuosa ole siinä mukana.')


@pytest.mark.parametrize('change', ['made_by', 'no_text', 'long_text', 'unknown_stock'])
def test_no_part_of_the_request_claim_without_the_record(change):
    proposal = deepcopy(ONLY)
    if change == 'made_by':
        proposal['request']['made_by'] = 'parser'
    elif change == 'no_text':
        proposal['request']['text'] = ''
    elif change == 'long_text':
        proposal['request']['text'] = 'milk ' * 80
    elif change == 'unknown_stock':
        proposal['lines'][0]['unknown_stock'] = True
    text = all_text(context(proposal, NAMES, 'en', PACKS))
    assert 'covers only' not in text and 'for this line' not in text


@pytest.mark.parametrize('language', ['en', 'fi'])
@pytest.mark.parametrize('proposal', [ONLY, PART])
def test_the_new_sentences_pass_the_checker_with_three_sentences(language, proposal):
    payload = context(proposal, NAMES, language, PACKS)
    assert len([f for f in payload['facts'] if f['required']]) <= 3
    text = checked_reply(reply_for(payload), payload['facts'], language)
    assert '698' in text and ('1,000' in text or '1000' in text)


def test_a_changed_covered_quantity_is_refused():
    payload = context(PART, NAMES, 'en', PACKS)
    reply = reply_for(payload)
    row = next(r for r in reply['sentences'] if r['kind'] == 'held')
    row['text'] = row['text'].replace('302 L of the 1000 L', '2 L of the 1000 L')
    row['numbers'] = ['2' if n == '302' else n for n in row['numbers']]
    with pytest.raises(ValueError):
        checked_reply(reply, payload['facts'], 'en')
