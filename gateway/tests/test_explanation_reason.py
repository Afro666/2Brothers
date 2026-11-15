"""The explanation states the price and the reason for the pick, from the record only (#1868)."""
from copy import deepcopy

import pytest

from agent.explanation import checked_reply
from agent.tests.test_explanation import reply_for
from gateway.explanation_facts import context

# The live card of 14 Nov: "1,000 L lactose-free milk by Monday".
MILK = {'proposal_id': 'p', 'status': 'READY', 'total_ex_vat': '2320.82', 'expected_total': '2634.13',
        'delivery_fee': '0.00', 'lines': [
            {'product_id': '463380', 'quantity': '698', 'unit': 'ST', 'unit_price': '2.65',
             'total': '1849.70', 'unknown_stock': False},
            {'product_id': '464201', 'quantity': '302', 'unit': 'ST', 'unit_price': '1.56',
             'total': '471.12', 'unknown_stock': True}],
        'alternative': {'total_ex_vat': '1560.00', 'lines': [
            {'product_id': '464201', 'quantity': '1000', 'unit': 'ST', 'total': '1560.00'}]}}
NAMES = {'463380': 'Arla Café milk 1 L UHT lactose free',
         '464201': 'Valio semi skimmed milk 1 l lactose free UHT'}


def fact(payload, kind):
    return next(f for f in payload['facts'] if f['kind'] == kind)


def test_the_chosen_sentence_gives_the_unit_price_of_the_line():
    chosen = fact(context(MILK, NAMES, 'en'), 'chosen')
    assert chosen['forms'][0] == ('The proposal includes 698 pieces of Arla Café milk 1 L UHT lactose free '
                                  'at EUR 2.65 per piece ex VAT; the supplier has confirmed availability.')
    fi = fact(context(MILK, NAMES, 'fi'), 'chosen')
    assert 'hintaan 2,65 EUR / kpl ilman ALV:a' in fi['forms'][0]


def test_a_line_with_no_price_in_the_record_gets_no_price():
    proposal = deepcopy(MILK)
    proposal['lines'][0]['unit_price'] = None
    text = fact(context(proposal, NAMES, 'en'), 'chosen')['forms'][0]
    assert text == ('The proposal includes 698 pieces of Arla Café milk 1 L UHT lactose free; '
                    'the supplier has confirmed availability.')


def test_the_required_warning_says_why_the_cheaper_option_was_not_picked():
    held = fact(context(MILK, NAMES, 'en'), 'held')
    assert held['required']
    assert held['forms'][0] == (
        'Supplier availability is unconfirmed for Valio semi skimmed milk 1 l lactose free UHT; '
        'a cheaper option was found, EUR 1560.00 ex VAT instead of EUR 2320.82 ex VAT, with all of it on '
        'Valio semi skimmed milk 1 l lactose free UHT, but its stock is not confirmed and the '
        'purchasing engine uses confirmed stock before price.')
    fi = fact(context(MILK, NAMES, 'fi'), 'held')['forms'][0]
    assert '1560,00 EUR ilman ALV:a eikä 2320,82 EUR ilman ALV:a' in fi
    assert 'ostomoottori käyttää vahvistetun varaston ennen hintaa' in fi


@pytest.mark.parametrize('language', ['en', 'fi'])
def test_the_whole_text_passes_the_checker_and_states_price_and_reason(language):
    payload = context(MILK, NAMES, language)
    text = checked_reply(reply_for(payload), payload['facts'], language)
    for number in ('2.65', '1560.00', '2320.82'):
        assert (number.replace('.', ',') if language == 'fi' else number) in text
    assert len([f for f in payload['facts'] if f['required']]) <= 3


@pytest.mark.parametrize('wrong', ['1460.00', '2.56'])
def test_a_changed_price_is_still_refused(wrong):
    payload = context(MILK, NAMES, 'en')
    reply = reply_for(payload)
    for row in reply['sentences']:
        row['text'] = row['text'].replace('1560.00', wrong).replace('2.65', wrong)
        row['numbers'] = [n.replace('1560', wrong).replace('2.65', wrong) for n in row['numbers']]
    with pytest.raises(ValueError):
        checked_reply(reply, payload['facts'], 'en')


@pytest.mark.parametrize('change', ['none', 'dearer', 'unreadable', 'confirmed', 'no_total', 'no_confirmed_line'])
def test_no_cheaper_claim_without_the_record(change):
    proposal = deepcopy(MILK)
    if change == 'none':
        proposal['alternative'] = None
    elif change == 'dearer':
        proposal['alternative']['total_ex_vat'] = '2320.82'
    elif change == 'unreadable':
        proposal['alternative']['total_ex_vat'] = 'n/a'
    elif change == 'confirmed':            # the record says its stock is confirmed: no such reason
        proposal['lines'][1]['unknown_stock'] = False
    elif change == 'no_total':
        proposal['total_ex_vat'] = None
    elif change == 'no_confirmed_line':
        proposal['lines'][0]['unknown_stock'] = True
    for language in ('en', 'fi'):
        text = ' '.join(form for f in context(proposal, NAMES, language)['facts'] for form in f['forms'])
        assert 'cheaper' not in text and 'halvempi' not in text


def test_a_cheaper_option_on_a_product_outside_the_lines_is_named_too():
    proposal = deepcopy(MILK)
    proposal['lines'] = proposal['lines'][:1]
    held = fact(context(proposal, NAMES, 'en'), 'held')
    assert held['required'] and held['forms'][0].startswith('A cheaper option was found, EUR 1560.00 ex VAT')
    assert 'Valio semi skimmed milk 1 l lactose free UHT' in held['forms'][0]


def test_the_source_hash_follows_the_cheaper_option():
    old = context(MILK, NAMES, 'en')['source_hash']
    proposal = deepcopy(MILK)
    proposal['alternative']['total_ex_vat'] = '1500.00'
    assert context(proposal, NAMES, 'en')['source_hash'] != old
