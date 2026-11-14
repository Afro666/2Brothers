import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from agent.explanation import checked_reply, numbers
from agent.explanation_service import ExplanationWriter
from agent.service import WorkerError
from gateway.explanation_facts import context

PROPOSAL = {'proposal_id': 'p', 'status': 'READY', 'lines': [
    {'product_id': 'milk', 'quantity': '698', 'unit': 'L', 'unknown_stock': False},
    {'product_id': 'cream', 'quantity': '302', 'unit': 'L', 'unknown_stock': False}],
    'expected_total': '1250.50'}


def test_synthetic_fixture_has_valid_bound_claims():
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/proposal-explanation.json').read_text())
    payload = context(PROPOSAL, {'milk': 'Milk', 'cream': 'Cream'}, fixture['language'])
    assert checked_reply(fixture['reply'], payload['facts']).startswith('The proposal includes 698 L of Milk;')


def reply_for(payload):
    facts = payload['facts']
    chosen = [f for f in facts if f.get('required')]
    chosen = [next(f for f in facts if f['kind'] == 'chosen')] + chosen
    return {'sentences': [{'fact_id': f['fact_id'], 'kind': f['kind'], 'product_id': f['product_id'],
        'text': f['forms'][0], 'numbers': numbers(f['forms'][0], payload['language'])} for f in chosen]}


@pytest.mark.parametrize('language', ['en', 'fi'])
def test_complete_bound_sentences_pass_in_both_languages(language):
    payload = context(PROPOSAL, {'milk': 'Milk', 'cream': 'Cream'}, language)
    text = checked_reply(reply_for(payload), payload['facts'], language)
    assert '698' in text
    assert ('Nothing is ordered' if language == 'en' else 'Mitään ei tilata') in text


@pytest.mark.parametrize('mutation', ['invented', 'swap', 'reason', 'placed', 'words', 'metadata', 'omitted'])
def test_false_claims_fail_whole_even_when_numbers_exist_elsewhere(mutation):
    payload = context(PROPOSAL, {'milk': 'Milk', 'cream': 'Cream'}, 'en')
    reply = reply_for(payload)
    line = reply['sentences'][0]
    if mutation == 'invented':
        line['text'] = line['text'].replace('698', '999')
        line['numbers'] = ['999']
    elif mutation == 'swap':
        line['text'] = line['text'].replace('698', '302')
        line['numbers'] = ['302']  # valid elsewhere, wrong for Milk
    elif mutation == 'reason':
        line['text'] += ' It was chosen because it is allergen-free.'
    elif mutation == 'placed':
        line['text'] = 'Ordered 698 L of Milk.'
    elif mutation == 'words':
        line['text'] = line['text'].replace('698', 'six hundred and ninety-eight')
    elif mutation == 'metadata':
        line['product_id'] = 'cream'
    else:
        reply['sentences'][1] = deepcopy(line)
    with pytest.raises(ValueError):
        checked_reply(reply, payload['facts'])


def test_finnish_numeric_formatting_and_english_grouping_keep_value():
    p = deepcopy(PROPOSAL)
    p['lines'][0]['quantity'] = '1000.50'
    payload = context(p, {'milk': 'Milk'}, 'fi')
    reply = reply_for(payload)
    reply['sentences'][0]['text'] = reply['sentences'][0]['text'].replace('1000,50', '1 000,50').replace(' L ', ' l ')
    reply['sentences'][0]['numbers'] = ['1 000,50']
    assert '1000,50' in checked_reply(reply, payload['facts'], 'fi')
    payload = context(p, {'milk': 'Milk'}, 'en')
    reply = reply_for(payload)
    reply['sentences'][0]['text'] = reply['sentences'][0]['text'].replace('1000.50', '1,000.50')
    reply['sentences'][0]['numbers'] = ['1,000.50']
    assert '1000.50' in checked_reply(reply, payload['facts'])


@pytest.mark.parametrize('timeout', [False, True])
def test_writer_is_single_call_closes_client_and_uses_short_json_budget(timeout):
    payload = context(PROPOSAL, {'milk': 'Milk'}, 'en')
    class Model:
        calls, closed = 0, False
        async def complete_json(self, messages, schema, name, **kw):
            self.calls += 1
            assert kw == {'max_tokens': 768, 'role': 'proposal_explanation'}
            if timeout:
                await asyncio.sleep(10)
            return {'content': json.dumps(reply_for(payload))}
        async def close(self):
            self.closed = True
    model = Model()
    async def run():
        writer = ExplanationWriter(WorkerError, model_factory=lambda: model, timeout=0.01)
        if timeout:
            with pytest.raises(WorkerError) as err:
                await writer.write(payload)
            assert err.value.code == 'EXPLANATION_TIMEOUT'
        else:
            result = await writer.write(payload)
            assert len(result['sentences']) == 2
    asyncio.run(run())
    assert model.calls == 1 and model.closed
