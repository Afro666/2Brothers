"""Read-only development check of declined-product preference and its safeguards."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from agent.memory import kitchen_memory, prompt_block
from agent.model import Nemotron
from agent import single_pick
from agent.vision import parse_reply

FIXTURE = Path(__file__).parent / 'fixtures/feedback-choice-v1.json'


def messages(case, *, baseline=False, stage='after_feedback', fixture=None):
    fixture = fixture or json.loads(FIXTURE.read_text(encoding='utf-8'))
    facts = case['facts'] if stage == 'after_feedback' else []
    entries = kitchen_memory(facts, [r['product_id'] for r in case['rows']], [])
    if not baseline:
        entries = single_pick.choice_memory(entries, case['rows'])
    memory = prompt_block(entries)
    rows = case['rows'] if baseline else single_pick.feedback_rows(case['rows'], entries)
    system = fixture['baseline_system'] if baseline else single_pick.SYSTEM
    note = fixture['baseline_memory_note'] if baseline else single_pick.MEMORY_NOTE
    if memory:
        system += '\n' + note + '\n' + memory
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': json.dumps({
        'request': case['request'], 'need': case['need'], 'products': rows})}]


async def run(args):
    fixture_bytes = FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    report = {'fixture_sha256': hashlib.sha256(fixture_bytes).hexdigest(), 'mode': args.mode,
              'design': fixture['design'], 'runs': []}
    # Refuse to mix measurements from different prompt revisions in an old output.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as output:
        for case in fixture['cases']:
            stages = ['after_feedback']
            if case['expected_without'] is not None:
                stages += ['without_feedback', 'after_undo']
            for stage in stages:
                sent = messages(case, baseline=args.mode == 'baseline', stage=stage, fixture=fixture)
                expected = case['expected_after'] if stage == 'after_feedback' else case['expected_without']
                for repeat in range(args.repeats):
                    model = Nemotron(timeout=20, max_attempts=1)
                    row = {'case': case['id'], 'stage': stage, 'repeat': repeat, 'pass': False,
                           'expected': expected,
                           'prompt_sha256': hashlib.sha256(json.dumps(sent).encode()).hexdigest()}
                    try:
                        reply = parse_reply(await model.complete_json(sent, single_pick.PICK_SCHEMA,
                            'buyer_pick', max_tokens=512, role='feedback_choice_bench'), single_pick.PICK_SCHEMA)
                        indices = [p['index'] for p in reply['picks']]
                        if len(indices) != len(set(indices)) or any(i >= len(case['rows']) for i in indices):
                            raise ValueError('invalid shortlist index')
                        row['model_picks'] = [case['rows'][i]['product_id'] for i in indices]
                        indices = single_pick.minimal_indices(indices, case['rows'], case['need'])
                        ids = [case['rows'][i]['product_id'] for i in indices]
                        row.update(picks=ids, **{'pass': set(ids) == set(expected)})
                    except Exception as exc:
                        row['error_type'] = type(exc).__name__  # never provider text or credentials
                    finally:
                        row['usage'] = model.meter.total()
                        await model.close()
                    report['runs'].append(row)
                    print(json.dumps({k: row[k] for k in ('case', 'stage', 'repeat', 'pass')}), flush=True)
        json.dump(report, output, indent=2)
    print(json.dumps({'passed': sum(r['pass'] for r in report['runs']), 'total': len(report['runs'])}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('baseline', 'current'), required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('repeats must be positive')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
