import asyncio
import json
from pathlib import Path

import pytest

from agent import pick_holdout_bench as bench
from agent.single_pick import SYSTEM


def cases():
    return json.loads(bench.FIXTURE.read_text(encoding='utf-8'))['cases']


def test_frozen_cases_have_valid_oracles_and_production_feedback_inputs():
    fixture = cases()
    assert len(fixture) == len({case['id'] for case in fixture}) == 20
    old = json.loads((bench.ROOT / 'agent/fixtures/pick-context-v1.json').read_text())['cases']
    assert not {c['request'] for c in fixture} & {c['request'] for c in old}
    for case in fixture:
        rows, messages = bench.build(case)
        ids = {row['product_id'] for row in rows}
        assert len(rows) == 3 and set(case['expected_includes']) <= ids
        assert case['expected_first'] in case['expected_includes']
        assert messages[0]['content'].startswith(SYSTEM)
        assert json.loads(messages[1]['content'])['need'] == case['need']
    alias = next(c for c in fixture if c['id'] == 'alias-sauce')
    rows, _ = bench.build(alias)
    assert rows[1]['alias'] is True and rows[1]['kitchen_declined'] is False
    feedback = next(c for c in fixture if c['id'] == 'feedback-cover')
    assert bench.build(feedback)[0][0]['kitchen_declined'] is True


def test_raw_and_guarded_scores_are_distinct_and_grounding_failures_are_visible():
    case = cases()[0]
    rows, _ = bench.build(case)
    correct = next(i for i, row in enumerate(rows) if row['product_id'] == case['expected_first'])
    answer = {'content': json.dumps({'picks': [
        {'index': correct, 'reason': 'Matches the request'},
        {'index': (correct + 1) % 3, 'reason': 'Another option'}]})}
    result = bench.score(case, rows, answer)
    assert result['raw_exact'] is False and result['guarded_exact'] is True
    answer['content'] = json.dumps({'picks': [{'index': correct, 'reason': 'Costs 987654321 euros'}]})
    result = bench.score(case, rows, answer)
    assert result['raw_exact'] is True and result['reasons_valid'] is False
    assert result['guarded_picks'] == [] and result['guarded_exact'] is False
    for indices in ([0, 0], [19]):
        answer['content'] = json.dumps({'picks': [{'index': i, 'reason': 'Fits'} for i in indices]})
        with pytest.raises(ValueError):
            bench.score(case, rows, answer)


def test_one_pass_persists_failures_resumes_without_reruns_and_rejects_changed_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv('VERDA_INFERENCE_KEY', 'test-only-placeholder')
    monkeypatch.delenv('NEMOTRON_MODEL', raising=False)
    instances = []

    class Fake:
        thinking = False

        def __init__(self, **kwargs):
            assert kwargs == {'timeout': 30, 'max_attempts': 1}
            self.closed = False
            self.meter = self
            self.calls = 0
            instances.append(self)

        async def complete_json(self, messages, schema, name, **kwargs):
            self.calls += 1
            if len(instances) == 1:
                raise RuntimeError('PRIVATE_PROVIDER_TEXT')
            return {'content': '{"picks":[{"index":0,"reason":"Matches the request"}]}'}

        def total(self):
            return {'calls': self.calls, 'failed': int(len(instances) == 1),
                    'prompt_tokens': 10, 'completion_tokens': 5}

        async def close(self):
            self.closed = True

    path = tmp_path / 'report.json'
    report = asyncio.run(bench.run(path, factory=Fake))
    assert len(instances) == 20 and all(m.closed and m.calls == 1 for m in instances)
    assert len(report['results']) == 20 and report['summary']['usage']['calls'] == 20
    assert report['results'][0]['error_type'] == 'RuntimeError'
    assert 'PRIVATE_PROVIDER_TEXT' not in path.read_text() and 'test-only-placeholder' not in path.read_text()
    asyncio.run(bench.run(path, factory=Fake))
    assert len(instances) == 20  # even the failed first call is not retried
    report['frozen']['fixture_sha256'] = 'changed'
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='refuse to mix'):
        asyncio.run(bench.run(path, factory=Fake))
    assert len(instances) == 20
