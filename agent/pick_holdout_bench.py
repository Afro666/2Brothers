"""One-pass synthetic product-selection holdout; no gateway, database or order writes.

Freeze and commit the fixture before using --live. A resumed report skips every
recorded case, including failures: no best-of reruns or tuning against this set.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import time

from agent.memory import prompt_block
from agent.model import Nemotron, provider_settings
from agent.pick_context_bench import inputs
from agent.single_pick import (MEMORY_NOTE, PICK_SCHEMA, SYSTEM, checked_reason,
                               choice_memory, feedback_rows, minimal_indices)
from agent.vision import parse_reply

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'agent/fixtures/pick-holdout-20-v1.json'
SOURCES = ('agent/single_pick.py', 'agent/pick_context_bench.py',
           'agent/pick_holdout_bench.py', 'agent/memory.py', 'agent/model.py',
           'engine/offers.py', 'engine/packs.py', 'engine/selection_facts.py')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build(case):
    rows, messages = inputs(case, True)
    entries = [{'kind': 'DECLINED_PRODUCT', 'product_id': pid, 'evidence': {'rows': 3}}
               for pid in case.get('declined_products', [])]
    entries = choice_memory(entries, rows)
    rows = feedback_rows(rows, entries)
    memory = prompt_block(entries)
    messages[0]['content'] = SYSTEM + ('\n' + MEMORY_NOTE + '\n' + memory if memory else '')
    messages[1]['content'] = json.dumps({'request': case['request'], 'need': case['need'],
                                       'products': rows}, ensure_ascii=False)
    return rows, messages


def score(case, rows, answer):
    reply = parse_reply(answer, PICK_SCHEMA)
    indices = [pick['index'] for pick in reply['picks']]
    if len(set(indices)) != len(indices) or any(i >= len(rows) for i in indices):
        raise ValueError('invalid shortlist index')
    ids = [rows[i]['product_id'] for i in indices]
    expected = set(case['expected_includes'])
    result = {'schema_valid': True, 'raw_picks': ids, 'raw_exact': set(ids) == expected,
              'first_correct': ids[0] == case['expected_first'], 'reasons_valid': True}
    try:
        for pick in reply['picks']:
            checked_reason(pick['reason'], rows[pick['index']], case['need'])
    except ValueError:
        result['reasons_valid'] = False
    guarded = minimal_indices(indices, rows, case['need']) if result['reasons_valid'] else []
    result['guarded_picks'] = [rows[i]['product_id'] for i in guarded]
    result['guarded_exact'] = set(result['guarded_picks']) == expected
    return result


def engine_result(case, rows):
    """Offer sizing/coverage only, not the full parser's upstream semantic guards."""
    ids = [row['product_id'] for row in rows if row['engine_selected']]
    return {'picks': ids, 'exact': set(ids) == set(case['expected_includes'])}


def summarize(results):
    finished_seconds = [r['seconds'] for r in results if 'seconds' in r]
    usage = {key: sum(r.get('usage', {}).get(key, 0) for r in results)
             for key in ('calls', 'failed', 'prompt_tokens', 'completion_tokens')}
    return {'cases': len(results), 'schema_valid': sum(r['schema_valid'] for r in results),
            'reason_valid': sum(r['reasons_valid'] for r in results),
            'raw_exact': sum(r['raw_exact'] for r in results),
            'guarded_exact': sum(r['guarded_exact'] for r in results),
            'engine_exact': sum(r['engine']['exact'] for r in results),
            'incomplete_attempts': sum(r.get('attempt_state') == 'started' for r in results),
            'median_model_roundtrip_seconds': round(statistics.median(finished_seconds), 3)
                if finished_seconds else None, 'usage': usage,
            'by_family': {family: {'cases': len(group),
                'raw_exact': sum(r['raw_exact'] for r in group),
                'guarded_exact': sum(r['guarded_exact'] for r in group),
                'engine_exact': sum(r['engine']['exact'] for r in group)}
                for family in sorted({r['family'] for r in results})
                if (group := [r for r in results if r['family'] == family])}}


def save(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(path)


async def run(out, *, factory=Nemotron):
    content = FIXTURE.read_bytes()
    cases = json.loads(content)['cases']
    endpoint, model_id, _ = provider_settings()
    frozen = {'fixture_sha256': digest(content), 'system_sha256': digest(SYSTEM.encode()),
              'source_sha256': {name: digest((ROOT / name).read_bytes()) for name in SOURCES},
              'model': model_id, 'endpoint': endpoint, 'temperature': 0, 'thinking': False, 'attempts_per_case': 1,
              'timeout_seconds': 30, 'max_tokens': 512, 'case_ids': [c['id'] for c in cases]}
    if out.exists():
        report = json.loads(out.read_text(encoding='utf-8'))
        if report['frozen'] != frozen:
            raise ValueError('Fixture, source or model changed: refuse to mix runs')
    else:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        report = {'label': 'Fresh synthetic 20-case selection holdout, one pass (#2000)',
                  'started_utc': datetime.now(timezone.utc).isoformat(), 'git_commit': commit,
                  'limitations': ['Three synthetic candidates per request; no live catalog or whole-Buyer test.',
                    'Known policy families, fresh combinations: not a representative real-world accuracy estimate.',
                    'No real-phone-photo evidence. No model or prompt tuning from these replies.',
                    'Engine comparator omits upstream parser kind/diet filters; not a full parser comparison.',
                    'Raw and guarded scores reuse the same model reply; not independent experiments.'],
                  'frozen': frozen, 'results': []}
    done = {r['case'] for r in report['results']}
    if len(done) != len(report['results']) or not done <= set(frozen['case_ids']):
        raise ValueError('Invalid or duplicate report cases')
    save(out, report)
    for case in cases:
        if case['id'] in done:
            continue
        rows, messages = build(case)
        model = factory(timeout=30, max_attempts=1)
        if model.thinking:
            await model.close()
            raise ValueError('Holdout requires NEMOTRON_BUYER_THINKING=off')
        started = time.monotonic()
        result = {'case': case['id'], 'family': case['family'],
                  'schema_valid': False, 'reasons_valid': False, 'raw_exact': False,
                  'guarded_exact': False, 'first_correct': False, 'engine': engine_result(case, rows),
                  'attempt_state': 'started', 'error_type': 'InterruptedAttempt'}
        # Persist intent before network I/O: even a hard stop cannot rerun an uncertain attempt.
        report['results'].append(result)
        report['summary'] = summarize(report['results'])
        save(out, report)
        try:
            answer = await asyncio.wait_for(model.complete_json(messages, PICK_SCHEMA,
                'buyer_pick', max_tokens=512, role='pick_holdout_2000'), 30)
            result.update(score(case, rows, answer))
            result['attempt_state'] = 'completed'
            result.pop('error_type', None)
        except Exception as exc:
            result['attempt_state'] = 'failed'
            result['error_type'] = type(exc).__name__  # never store provider text or credentials
        finally:
            result['seconds'] = round(time.monotonic() - started, 3)
            result['usage'] = model.meter.total()
            await model.close()
            report['summary'] = summarize(report['results'])
            save(out, report)
        print(json.dumps({'finished': len(report['results']), 'case': case['id'],
                          'schema_valid': result['schema_valid']}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--live', action='store_true', help='Make up to twenty read-only model calls')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live is required; freeze and commit the fixture first')
    try:
        report = asyncio.run(run(args.out))
    except Exception as exc:
        # Initialization errors may mention environment/provider settings: no raw exception logging.
        raise SystemExit(f'Benchmark stopped: {type(exc).__name__}') from None
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
