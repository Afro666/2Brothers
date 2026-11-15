import asyncio
import hashlib
import json

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
            assert json.loads(path.read_text())['results'][-1]['attempt_state'] == 'started'
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
    # An uncertain interrupted attempt is also never reissued on resume.
    report['results'][1]['attempt_state'] = 'started'
    path.write_text(json.dumps(report))
    asyncio.run(bench.run(path, factory=Fake))
    assert len(instances) == 20  # neither failures nor interrupted attempts are retried
    report['frozen']['fixture_sha256'] = 'changed'
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='refuse to mix'):
        asyncio.run(bench.run(path, factory=Fake))
    assert len(instances) == 20


def test_saved_live_report_matches_frozen_oracles_and_keeps_raw_miss_visible():
    report = json.loads((bench.ROOT / 'agent/benchmarks/pick-holdout-20-v1-report.json')
                        .read_text(encoding='utf-8'))
    fixture = json.loads(bench.FIXTURE.read_text(encoding='utf-8'))
    canonical = json.dumps(fixture, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    assert hashlib.sha256(canonical).hexdigest() == report['fixture_canonical_sha256']
    by_id = {c['id']: c for c in fixture['cases']}
    assert len(report['results']) == len({r['case'] for r in report['results']}) == 20
    assert report['summary'] == bench.summarize(report['results'])
    assert report['summary']['raw_exact'] == 19
    assert report['summary']['guarded_exact'] == 20
    assert report['summary']['incomplete_attempts'] == 0
    for row in report['results']:
        case = by_id[row['case']]
        expected = set(case['expected_includes'])
        assert row['raw_exact'] == (set(row['raw_picks']) == expected)
        assert row['guarded_exact'] == (set(row['guarded_picks']) == expected)
        assert row['first_correct'] == (row['raw_picks'][0] == case['expected_first'])
        assert row['usage']['calls'] == 1 and row['attempt_state'] == 'completed'
    miss = next(r for r in report['results'] if not r['raw_exact'])
    assert miss['case'] == 'feedback-cover'
    assert len(miss['raw_picks']) == 2 and len(miss['guarded_picks']) == 1
