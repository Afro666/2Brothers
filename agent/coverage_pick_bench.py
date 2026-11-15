"""Read-only paired coverage-hint comparison on frozen quote snapshots (#2021)."""
import argparse
import asyncio
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

from agent.model import Nemotron, provider_settings
from agent.pick_holdout_bench import digest, save
from agent.single_pick import PICK_SCHEMA, SYSTEM, checked_reason, coverage_rows, minimal_indices
from agent.vision import parse_reply

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'agent/fixtures/coverage-pick-v3.json'


def inputs(fixture, case, mode):
    if mode not in ('before', 'after'):
        raise ValueError('unknown comparison arm')
    rows = copy.deepcopy(case['rows'])
    if mode == 'after':
        rows = coverage_rows(rows, case['need'], request_text=case['request'])
    system = fixture['before_system'] if mode == 'before' else SYSTEM
    return rows, [{'role': 'system', 'content': system + case['memory_tail']},
                  {'role': 'user', 'content': json.dumps({'request': case['request'],
                    'need': case['need'], 'products': rows}, ensure_ascii=False)}]


def score(case, rows, answer):
    reply = parse_reply(answer, PICK_SCHEMA)
    indices = [pick['index'] for pick in reply['picks']]
    if len(set(indices)) != len(indices) or any(i >= len(rows) for i in indices):
        raise ValueError('invalid shortlist indices')
    ids = [rows[i]['product_id'] for i in indices]
    expected = set(case['expected_includes'])
    reasons = True
    for pick in reply['picks']:
        try:
            checked_reason(pick['reason'], rows[pick['index']], case['need'])
        except ValueError:
            reasons = False  # production drops the reason, not the selected products
    guarded = [rows[i]['product_id'] for i in minimal_indices(indices, rows, case['need'])]
    return {'schema_valid': True, 'reasons_valid': reasons, 'raw_picks': ids,
            'guarded_picks': guarded, 'raw_exact': set(ids) == expected,
            'guarded_exact': set(guarded) == expected, 'first_correct': ids[0] == case['expected_first'],
            'redundant': len(expected) == 1 and ids[0] == case['expected_first'] and len(ids) > 1}


def summarize(results):
    summary = {}
    for group in sorted({r['group'] for r in results}):
        summary[group] = {}
        for mode in ('before', 'after'):
            rows = [r for r in results if r['group'] == group and r['mode'] == mode]
            summary[group][mode] = {'runs': len(rows), 'cases': len({r['case'] for r in rows}),
                **{key: sum(bool(r.get(key)) for r in rows) for key in
                   ('schema_valid', 'reasons_valid', 'raw_exact', 'guarded_exact', 'first_correct', 'redundant')},
                'incomplete': sum(r['attempt_state'] == 'started' for r in rows),
                'hinted_runs': sum(r.get('input_changed', False) for r in rows),
                'hinted_raw_exact': sum(r.get('input_changed', False) and r.get('raw_exact', False) for r in rows),
                'hinted_first_correct': sum(r.get('input_changed', False) and r.get('first_correct', False) for r in rows)}
    return summary


async def run(path, *, factory=Nemotron):
    content = FIXTURE.read_bytes()
    fixture = json.loads(content)
    cases = {case['id']: case for case in fixture['cases']}
    endpoint, model_id, _ = provider_settings()
    frozen = {'fixture_sha256': digest(content), 'before_system_sha256': digest(fixture['before_system'].encode()),
              'after_system_sha256': digest(SYSTEM.encode()), 'endpoint': endpoint, 'model': model_id,
              'thinking': False, 'temperature': 0, 'attempts_per_trial': 1, 'max_tokens': 512,
              'source_sha256': {name: digest((ROOT / name).read_bytes()) for name in
                  ('agent/coverage_pick_bench.py', 'agent/single_pick.py', 'agent/model.py', 'gateway/diet.py', 'store/buyer_picks.py')}}
    if path.exists():
        report = json.loads(path.read_text(encoding='utf-8'))
        if report['frozen'] != frozen:
            raise ValueError('Refusing to mix changed source, fixture or settings')
    else:
        report = {'label': 'Frozen paired synthetic selection comparison (#2021)',
            'started_utc': datetime.now(timezone.utc).isoformat(),
            'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'frozen': frozen, 'limitations': ['Known diagnostics are development data, not held-out evidence.',
                'Fresh cases are three-candidate synthetic snapshots, not live-catalog or whole-Buyer accuracy.',
                'Repeated replies are not independent real-world samples; the provider build is not pinned.',
                'Both arms use the existing guard, and no orders or approvals are made.'], 'results': []}
    done = {(r['case'], r['repeat'], r['mode']) for r in report['results']}
    schedule = fixture['schedule']
    allowed = {(r['case'], r['repeat'], r['mode']) for r in schedule}
    if len(done) != len(report['results']) or not done <= allowed:
        raise ValueError('Invalid report schedule')
    save(path, report)
    failures = 0
    for trial in schedule:
        if (trial['case'], trial['repeat'], trial['mode']) in done:
            continue
        case = cases[trial['case']]
        rows, messages = inputs(fixture, case, trial['mode'])
        input_changed = inputs(fixture, case, 'before')[1] != inputs(fixture, case, 'after')[1]
        model = factory(timeout=30, max_attempts=1)
        if model.thinking:
            await model.close()
            raise ValueError('Comparison requires thinking off')
        result = {**trial, 'input_changed': input_changed, 'input_sha256': digest(json.dumps(messages, sort_keys=True).encode()), 'attempt_state': 'started', 'error_type': 'InterruptedAttempt',
                  'schema_valid': False, 'raw_exact': False, 'guarded_exact': False}
        report['results'].append(result)
        save(path, report)  # checkpoint before network I/O; uncertain attempts are never reissued
        started = time.monotonic()
        try:
            answer = await asyncio.wait_for(model.complete_json(messages, PICK_SCHEMA, 'buyer_pick',
                max_tokens=512, role='coverage_pick_bench'), 30)
            result.update(score(case, rows, answer))
            result['attempt_state'] = 'completed'
            result.pop('error_type', None)
            failures = 0
        except Exception as exc:
            result['error_type'] = type(exc).__name__
            result['attempt_state'] = 'failed'
            failures += 1
        finally:
            result['seconds'] = round(time.monotonic() - started, 3)
            result['usage'] = model.meter.total()
            await model.close()
            report['summary'] = summarize(report['results'])
            save(path, report)
        print(json.dumps({'finished': len(report['results']), 'case': case['id'], 'mode': trial['mode'],
                          'raw_exact': result['raw_exact']}), flush=True)
        if failures >= 3:
            report['stopped_reason'] = 'Three consecutive errors; no retries'
            save(path, report)
            break
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if not args.live:
        parser.error('--live required: freeze the inputs before making model calls')
    try:
        report = asyncio.run(run(args.out))
    except Exception as exc:
        raise SystemExit(f'Comparison stopped: {type(exc).__name__}') from None
    print(json.dumps(report.get('summary', {}), indent=2))


if __name__ == '__main__':
    main()
