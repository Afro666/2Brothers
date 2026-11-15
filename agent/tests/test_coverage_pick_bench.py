import asyncio
import json

import pytest

from agent import coverage_pick_bench as bench


def fixture():
    return json.loads(bench.FIXTURE.read_text(encoding='utf-8'))


def test_comparison_changes_only_system_and_code_computed_hint():
    data = fixture()
    assert len(data['cases']) == 43 and len(data['schedule']) == 138
    assert len({(r['case'], r['repeat'], r['mode']) for r in data['schedule']}) == 138
    assert data['before_system'] == bench.SYSTEM
    for case in data['cases']:
        before, old_messages = bench.inputs(data, case, 'before')
        after, new_messages = bench.inputs(data, case, 'after')
        assert old_messages[0]['content'] == data['before_system'] + case['memory_tail']
        assert before == case['rows']
        assert [{k: v for k, v in row.items() if k != 'covers_need_alone'} for row in after] == before
        old_payload, new_payload = (json.loads(m[1]['content']) for m in (old_messages, new_messages))
        assert old_payload['request'] == new_payload['request'] == case['request']
        assert old_payload['need'] == new_payload['need'] == case['need']
        if any('covers_need_alone' in row for row in after):
            assert all(type(row['covers_need_alone']) is bool for row in after)
            assert any(row['covers_need_alone'] for row in after)
        else:
            assert old_messages == new_messages  # complex/partial inputs remain byte-identical


def test_scores_raw_failure_without_losing_valid_partial_complements():
    data = fixture()
    for cid, indices, raw, guarded in [('diag-orange-juice', [0, 1], False, True),
                                      ('partial-rounding', [0, 1], True, True),
                                      ('alias-partial', [0, 1], True, True),
                                      ('alias-before-full', [1, 0], False, True)]:
        case = next(c for c in data['cases'] if c['id'] == cid)
        rows, _ = bench.inputs(data, case, 'after')
        answer = {'content': json.dumps({'picks': [{'index': i, 'reason': 'Matches requested product'} for i in indices]})}
        result = bench.score(case, rows, answer)
        assert result['raw_exact'] is raw and result['guarded_exact'] is guarded


def test_comparison_checkpoints_failures_and_never_repeats_an_attempt(tmp_path, monkeypatch):
    data = fixture()
    case = data['cases'][0]
    data['cases'] = [case]
    data['schedule'] = [r for r in data['schedule'] if r['case'] == case['id'] and r['repeat'] <= 2]
    path = tmp_path / 'fixture.json'
    path.write_text(json.dumps(data))
    monkeypatch.setattr(bench, 'FIXTURE', path)
    monkeypatch.setenv('VERDA_INFERENCE_KEY', 'test-only-placeholder')
    output = tmp_path / 'report.json'
    models = []

    class Fake:
        thinking = False

        def __init__(self, **kwargs):
            assert kwargs == {'timeout': 30, 'max_attempts': 1}
            models.append(self)
            self.calls = 0
            self.meter = self
            self.closed = False

        async def complete_json(self, *args, **kwargs):
            self.calls += 1
            assert json.loads(output.read_text())['results'][-1]['attempt_state'] == 'started'
            if len(models) == 1:
                raise RuntimeError('PRIVATE_PROVIDER_TEXT')
            return {'content': '{"picks":[{"index":0,"reason":"Matches request"}]}'}

        def total(self):
            return {'calls': self.calls}

        async def close(self):
            self.closed = True

    report = asyncio.run(bench.run(output, factory=Fake))
    assert len(models) == 4 and all(m.calls == 1 and m.closed for m in models)
    assert report['results'][0]['attempt_state'] == 'failed'
    assert 'PRIVATE_PROVIDER_TEXT' not in output.read_text()
    asyncio.run(bench.run(output, factory=Fake))
    assert len(models) == 4
    report['frozen']['fixture_sha256'] = 'different'
    output.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='Refusing to mix'):
        asyncio.run(bench.run(output, factory=Fake))
