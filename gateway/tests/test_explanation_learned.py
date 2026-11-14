"""The learned proposal line becomes a required, copyable explanation fact (#1173)."""
from copy import deepcopy

import pytest

from agent.explanation import checked_reply, numbers
from agent.tests.test_explanation import PROPOSAL
from gateway.explanation_facts import MAX_FACTS, context

NAMES = {'milk': 'Milk', 'cream': 'Cream'}
EN = ('10 L instead of 20 L of Milk: you changed this product to 50 % of the forecast '
      'in your last 3 changes.')
FI = ('10 L eik\u00e4 20 L (Milk): muutitte t\u00e4t\u00e4 tuotetta 50 %:iin ennusteesta '
      'viimeisiss\u00e4 3 muutoksessanne.')


def learned_proposal():
    proposal = deepcopy(PROPOSAL)
    proposal['lines'][0]['learned'] = {
        'fact_id': 'lf-milk', 'from_qty': '20', 'to_qty': '10', 'unit': 'L',
        'ratio': 0.5, 'evidence': {'rows': 3, 'last': '2026-11-09'}}
    return proposal


def learned_fact(payload):
    return next(fact for fact in payload['facts'] if fact['kind'] == 'learned')


def bound_reply(payload, language):
    sentences = []
    for fact in payload['facts']:
        if not fact.get('required'):
            continue
        last = language == 'fi' and fact['kind'] == 'learned'
        form = fact['forms'][-1] if last else fact['forms'][0]
        sentences.append({'fact_id': fact['fact_id'], 'kind': fact['kind'],
                          'product_id': fact['product_id'], 'text': form,
                          'numbers': numbers(form, language)})
    return {'sentences': sentences}


@pytest.mark.parametrize('language', ['en', 'fi'])
def test_learned_line_adds_one_required_fact_in_the_readers_language_with_exact_numbers(language):
    payload = context(learned_proposal(), NAMES, language)
    fact = learned_fact(payload)

    assert fact['product_id'] == 'milk' and fact['required'] is True
    assert fact['forms'] == [FI if language == 'fi' else EN]     # never the other language
    assert all(numbers(form, language) == ['10', '20', '50', '3'] for form in fact['forms'])


@pytest.mark.parametrize('language', ['en', 'fi'])
def test_a_reply_that_copies_the_learned_sentence_passes_checked_reply(language):
    payload = context(learned_proposal(), NAMES, language)
    text = checked_reply(bound_reply(payload, language), payload['facts'], language)

    assert (FI if language == 'fi' else EN) in text


def test_a_reply_that_changes_a_learned_number_fails_the_whole_check():
    payload = context(learned_proposal(), NAMES, 'en')
    reply = bound_reply(payload, 'en')
    line = next(row for row in reply['sentences'] if row['kind'] == 'learned')
    line['text'] = line['text'].replace('10 L', '999 L', 1)
    line['numbers'] = numbers(line['text'], 'en')

    with pytest.raises(ValueError):
        checked_reply(reply, payload['facts'])


def test_a_proposal_without_learned_lines_gives_the_existing_facts_unchanged():
    payload = context(PROPOSAL, NAMES, 'en')

    assert [fact['kind'] for fact in payload['facts']] == ['chosen', 'chosen', 'total', 'approval']
    assert all('learned' not in fact['kind'] for fact in payload['facts'])


def test_the_learned_field_changes_the_source_hash():
    assert context(learned_proposal(), NAMES, 'en')['source_hash'] != context(PROPOSAL, NAMES, 'en')['source_hash']


def test_a_learned_fact_survives_the_explanation_fact_cap():
    proposal = deepcopy(PROPOSAL)
    proposal['lines'] = [
        {'product_id': f'p{number}', 'quantity': '10', 'unit': 'L', 'unknown_stock': False,
         'learned': {'fact_id': f'lf-{number}', 'from_qty': '20', 'to_qty': '10', 'unit': 'L',
                     'ratio': 0.5, 'evidence': {'rows': 3}}}
        for number in range(8)]
    proposal['excluded'] = [{'product_id': f'e{number}', 'reason': 'ALLERGEN_RULE:x'}
                            for number in range(4)]
    proposal['shortfall'], proposal['measure'] = '1', 'L'

    payload = context(proposal, {}, 'en')

    assert len(payload['facts']) <= MAX_FACTS
    assert len([fact for fact in payload['facts'] if fact['kind'] == 'learned']) == 8
