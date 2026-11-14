"""Bound, bilingual facts from the same stored inputs as the decision record."""
import hashlib
import json
from decimal import Decimal, InvalidOperation


def context(proposal, names, language):
    fi = language == 'fi'
    facts = []
    def add(kind, pid, text, required=False, alternative=None):
        facts.append({'fact_id': f'{kind}:{len(facts)}', 'kind': kind, 'product_id': pid,
                      'forms': [text] + ([alternative] if alternative else []), 'required': required})
    def amount(value):
        text = str(value)
        return text.replace('.', ',') if fi else text
    def name(pid):
        return names.get(pid) or pid

    for line in proposal.get('lines', [])[:8]:
        pid, qty, unit = line['product_id'], amount(line['quantity']), line['unit']
        confirmed = line.get('unknown_stock') is False
        text = (f'Ehdotuksessa on {qty} {unit} tuotetta {name(pid)}' if fi else
                f'The proposal includes {qty} {unit} of {name(pid)}')
        reason = ('; toimittaja on vahvistanut saatavuuden' if fi else '; the supplier has confirmed availability') if confirmed else ''
        add('chosen', pid, text + reason + '.', required=len(facts) == 0, alternative=text +
            ('; määrä on ostomoottorin laskema.' if fi else '; the purchasing engine sized this quantity.'))
    for row in proposal.get('excluded', [])[:4]:
        pid, reason = row['product_id'], row.get('reason', '')
        # A reason is a claim too: only supported, exact source reasons get translated.
        if reason.startswith('ALLERGEN_RULE:'):
            why = 'keittiön allergeenisääntö estää sen' if fi else "the kitchen's allergen rule excludes it"
        else:
            why = 'katso syy päätöstiedoista' if fi else 'see the decision record for the reason'
        add('left_out', pid, f'Tuote {name(pid)} jätettiin pois: {why}.' if fi else f'{name(pid)} was left out; {why}.')
    unknown = [name(l['product_id']) for l in proposal.get('lines', []) if l.get('unknown_stock') is not False]
    warnings = []
    if unknown:
        label = ', '.join(unknown[:8])
        if len(unknown) > 8:
            label += f' (+{len(unknown)-8})'
        warnings.append(f'Toimittajan saatavuus on vahvistamatta: {label}' if fi else
                        f'Supplier availability is unconfirmed for {label}')
    short = proposal.get('shortfall')
    try:
        has_short = short is not None and Decimal(str(short)) > 0
    except InvalidOperation:
        has_short = False
    if has_short and proposal.get('measure'):
        gap, unit = amount(short), proposal['measure']
        warnings.append(f'tälle päivälle jää kattamatta {gap} {unit}' if fi else
                        f'{gap} {unit} cannot be covered for this date')
    elif proposal.get('shortfalls'):
        for row in proposal['shortfalls']:
            label = f"{name(row['product_id'])}: {amount(row['shortfall'])} {row['unit']}"
            warnings.append(f'kattamatta jää {label}' if fi else f'uncovered need for {label}')
    if warnings:
        # One bound warning sentence leaves room for the chosen line and human approval.
        add('held', None, '; '.join(warnings) + '.', required=True)
    if proposal.get('lines') and proposal.get('expected_total') is not None:
        total = amount(proposal['expected_total'])
        fee = ('; toimitusmaksu ei ole tiedossa' if fi else '; the delivery fee is unknown') if proposal.get('delivery_fee') is None else ''
        add('total', None, (f'Ehdotuksen tiedossa oleva summa on {total} EUR' if fi else f'The known proposal total is EUR {total}') + fee + '.')
    if proposal['status'] == 'READY':
        add('approval', None, 'Mitään ei tilata ennen henkilön hyväksyntää.' if fi else
            'Nothing is ordered until a person approves.', required=True)
    elif proposal['status'] == 'REJECTED':
        add('approval', None, 'Ehdotus on hylätty eikä mitään tilata.' if fi else
            'The proposal is rejected and nothing is ordered.', required=True)
    source = {k: proposal.get(k) for k in ('proposal_id', 'offer_id', 'offer_hash', 'status', 'request',
        'lines', 'excluded', 'expected_total', 'delivery_fee', 'shortfall', 'shortfalls', 'measure', 'mandate', 'recall_alerts', 'valid_until')}
    source['names'] = names
    digest = hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()
    return {'source_hash': digest, 'language': language, 'facts': facts}
