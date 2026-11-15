"""Bound, bilingual facts from the same stored inputs as the decision record."""
import hashlib
import json
from decimal import Decimal, InvalidOperation

MAX_FACTS = 20  # the explanation wire contract accepts at most this many facts
MAX_SENTENCES = 3  # agent/explanation.py SCHEMA: a reply has at most this many sentences
FACTS_VERSION = 3  # the sentences changed (#1868, #1973): a text cached from the old ones is not served

# A counted sales unit in the words the web uses (web/src/lib/format.ts PEOPLE_UNITS,
# web/src/i18n/fi/common.ts): (one, many). A measured unit (L, KG) stays as it is.
UNIT_WORDS = {
    'en': {'ST': ('piece', 'pieces'), 'PCS': ('piece', 'pieces'), 'KI': ('case', 'cases'),
           'BOT': ('bottle', 'bottles'), 'PRK': ('pack', 'packs')},
    'fi': {'ST': ('kpl', 'kpl'), 'PCS': ('kpl', 'kpl'), 'KI': ('laatikko', 'laatikkoa'),
           'BOT': ('pullo', 'pulloa'), 'PRK': ('pakkaus', 'pakkausta')}}
# With a pack size from the catalog a piece is a pack: "698 x 1 L packs" (#1973).
PACK_WORDS = {'en': {'ST': ('pack', 'packs'), 'PCS': ('pack', 'packs')},
              'fi': {'ST': ('pakkaus', 'pakkausta'), 'PCS': ('pakkaus', 'pakkausta')}}
MAX_REQUEST_TEXT = 200  # a longer request text is not quoted


def positive(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number > 0 else None


def coverage(proposal):
    """What the record says about a request that is only partly covered (#1973), or None.

    Every quantity is copied from the record, never calculated:
    - 'partial': `partial_fill` gives the asked, the confirmed and the remaining quantity;
    - 'short': `shortfall` against the asked `request.quantity`;
    - 'only': the request was re-made for the confirmed stock alone (`made_by`
      `confirmed_only`, gateway/options.py), so the asked quantity is only in its text."""
    request = proposal.get('request') if isinstance(proposal.get('request'), dict) else {}
    part = proposal.get('partial_fill')
    if isinstance(part, dict) and isinstance(part.get('now'), dict) and part.get('measure') and all(
            positive(v) for v in (part.get('need'), part.get('remaining'), part['now'].get('quantity'))):
        return {'kind': 'partial', 'asked': part['need'], 'covered': part['now']['quantity'],
                'rest': part['remaining'], 'measure': part['measure']}
    short, asked = positive(proposal.get('shortfall')), positive(request.get('quantity'))
    if short and proposal.get('measure'):
        if asked and asked > short and request.get('unit') == proposal['measure']:
            return {'kind': 'short', 'asked': request['quantity'], 'rest': proposal['shortfall'],
                    'measure': proposal['measure']}
        return None
    text = request.get('text')
    lines = proposal.get('lines') or []
    if (request.get('made_by') == 'confirmed_only' and asked and request.get('unit') and isinstance(text, str)
            and 0 < len(text.strip()) <= MAX_REQUEST_TEXT and '\n' not in text.strip()
            and lines and all(line.get('unknown_stock') is False for line in lines)):
        return {'kind': 'only', 'text': text.strip(), 'covered': request['quantity'], 'measure': request['unit']}
    return None


def cheaper(proposal, name, amount, fi):
    """Why the cheaper option was not picked (#1868), or None when the record does not say.

    The engine fills confirmed stock first and puts the rest on the cheapest offer with
    unknown stock. `alternative` exists only when putting everything on that offer is cheaper
    (engine/offers.py, `plan_request`), so its being there is the recorded reason. Both
    totals are copied from the record; they are compared here, never calculated."""
    alt, total = proposal.get('alternative'), proposal.get('total_ex_vat')
    if not isinstance(alt, dict) or total is None or alt.get('total_ex_vat') is None:
        return None
    try:
        if not Decimal(str(alt['total_ex_vat'])) < Decimal(str(total)):
            return None
    except InvalidOperation:
        return None
    ids = [row['product_id'] for row in alt.get('lines') or []]
    stock = {line['product_id']: line.get('unknown_stock') for line in proposal.get('lines', [])}
    # The reason holds only when the record agrees: a confirmed line was picked, and no line
    # says the cheaper product's stock is confirmed.
    if not ids or False not in stock.values() or any(stock.get(pid) is False for pid in ids):
        return None
    label = ', '.join(name(pid) for pid in ids[:4])
    low, high = amount(alt['total_ex_vat']), amount(total)
    if fi:
        return (f'löytyi halvempi vaihtoehto, {low} EUR ilman ALV:a eikä {high} EUR ilman ALV:a, jossa kaikki on '
                f'tuotetta {label}, mutta sen saatavuutta ei ole vahvistettu, ja ostomoottori käyttää '
                'vahvistetun varaston ennen hintaa')
    return (f'a cheaper option was found, EUR {low} ex VAT instead of EUR {high} ex VAT, with all of it on '
            f'{label}, but its stock is not confirmed and the purchasing engine uses confirmed stock before price')


def context(proposal, names, language, packs=None):
    """`packs`: {product_id: {'unit', 'size', 'measure'}}, one sales unit's content from the catalog."""
    fi = language == 'fi'
    packs = packs or {}
    facts = []
    def add(kind, pid, text, required=False, alternative=None):
        facts.append({'fact_id': f'{kind}:{len(facts)}', 'kind': kind, 'product_id': pid,
                      'forms': [text] + ([alternative] if alternative else []), 'required': required})
    def amount(value):
        text = str(value)
        return text.replace('.', ',') if fi else text
    def name(pid):
        return names.get(pid) or pid
    def word(unit, quantity=None):
        """The unit in plain words: "pieces" for ST, never the raw code (#1973)."""
        words = UNIT_WORDS['fi' if fi else 'en'].get(str(unit).upper())
        return (words[0] if positive(quantity) == 1 else words[1]) if words else unit
    def packed(pid, unit, quantity):
        """("698 x 1 L packs", "1 L pack") when the catalog gives the pack size, else the unit word twice."""
        pack, code = packs.get(pid), str(unit).upper()
        if code not in UNIT_WORDS['en'] or not isinstance(pack, dict) or pack.get('unit') != unit:
            return f'{amount(quantity)} {word(unit, quantity)}', word(unit, 1)
        one, many = PACK_WORDS['fi' if fi else 'en'].get(code) or UNIT_WORDS['fi' if fi else 'en'][code]
        size = f"{amount(pack['size'])} {pack['measure']}"
        return f'{amount(quantity)} x {size} {one if positive(quantity) == 1 else many}', f'{size} {one}'
    cover = coverage(proposal)

    for line in proposal.get('lines', [])[:8]:
        pid = line['product_id']
        qty, unit = packed(pid, line['unit'], line['quantity'])
        confirmed = line.get('unknown_stock') is False
        text = (f'Ehdotuksessa on {qty} tuotetta {name(pid)}' if fi else
                f'The proposal includes {qty} of {name(pid)}')
        if line.get('unit_price') is not None:
            # The line's own price, per its sales unit (#1868): copied, never calculated.
            price = amount(line['unit_price'])
            text += f' hintaan {price} EUR / {unit} ilman ALV:a' if fi else f' at EUR {price} per {unit} ex VAT'
        if not confirmed:
            reason = ''
        elif cover and cover['kind'] == 'partial':
            # Confirmed for a part of what was asked, never for the whole request (#1973).
            done, asked = f"{amount(cover['covered'])} {cover['measure']}", f"{amount(cover['asked'])} {cover['measure']}"
            reason = (f'; toimittaja on vahvistanut saatavuuden määrälle {done}, pyydetty määrä on {asked}' if fi else
                      f'; the supplier has confirmed stock for {done} of the {asked} asked')
        elif cover:
            reason = ('; toimittaja on vahvistanut tämän rivin saatavuuden' if fi else
                      '; the supplier has confirmed availability for this line')
        else:
            reason = '; toimittaja on vahvistanut saatavuuden' if fi else '; the supplier has confirmed availability'
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
    if cover and cover['kind'] == 'partial':
        rest, asked = f"{amount(cover['rest'])} {cover['measure']}", f"{amount(cover['asked'])} {cover['measure']}"
        warnings.append(f'pyydetystä määrästä {asked} jää {rest} ilman vahvistettua varastoa' if fi else
                        f'{rest} of the {asked} asked is not covered by confirmed stock')
    elif cover and cover['kind'] == 'only':
        # The asked quantity is only in the request's own words: quoted, never read as a number.
        done = f"{amount(cover['covered'])} {cover['measure']}"
        warnings.append(f'pyyntö oli "{cover["text"]}"; tämä ehdotus kattaa vain toimittajan vahvistaman määrän '
                        f'{done}, eikä pyynnön loppuosa ole siinä mukana' if fi else
                        f'the request was "{cover["text"]}"; this proposal covers only the {done} the supplier '
                        'confirms in stock, and the rest of the request is not in it')
    if unknown:
        label = ', '.join(unknown[:8])
        if len(unknown) > 8:
            label += f' (+{len(unknown)-8})'
        warnings.append(f'toimittajan saatavuus on vahvistamatta: {label}' if fi else
                        f'supplier availability is unconfirmed for {label}')
    short = proposal.get('shortfall')
    try:
        has_short = short is not None and Decimal(str(short)) > 0
    except InvalidOperation:
        has_short = False
    if has_short and proposal.get('measure'):
        gap, unit = amount(short), proposal['measure']
        if cover and cover['kind'] == 'short':
            asked = f"{amount(cover['asked'])} {unit}"
            warnings.append(f'pyydetystä määrästä {asked} jää tälle päivälle kattamatta {gap} {unit}' if fi else
                            f'{gap} {unit} of the {asked} asked cannot be covered for this date')
        else:
            warnings.append(f'tälle päivälle jää kattamatta {gap} {unit}' if fi else
                            f'{gap} {unit} cannot be covered for this date')
    elif proposal.get('shortfalls'):
        for row in proposal['shortfalls']:
            label = f"{name(row['product_id'])}: {amount(row['shortfall'])} {word(row['unit'], row['shortfall'])}"
            warnings.append(f'kattamatta jää {label}' if fi else f'uncovered need for {label}')
    why = cheaper(proposal, name, amount, fi)
    if why:
        warnings.append(why)
    if warnings:
        # One bound warning sentence leaves room for the chosen line and human approval.
        text = '; '.join(warnings) + '.'
        add('held', None, text[0].upper() + text[1:], required=True)
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
    for line in proposal.get('lines', []):
        info = line.get('learned')
        if not isinstance(info, dict):
            continue
        pid = line['product_id']
        unit = word(info.get('unit') or line['unit'])
        rows = (info.get('evidence') or {}).get('rows', 0)
        try:
            percent = round(float(info.get('ratio')) * 100)
        except (TypeError, ValueError):
            continue            # no trustworthy ratio: no learned sentence, never "0 %"
        to_qty, from_qty = amount(info.get('to_qty')), amount(info.get('from_qty'))
        # One sentence in the reader's language, like every other fact here: `alternative`
        # is another wording in the same language (both go into `forms`), never a translation.
        sentence = (f'{to_qty} {unit} eikä {from_qty} {unit} ({name(pid)}): muutitte '
                    f'tätä tuotetta {percent} %:iin ennusteesta viimeisissä {amount(rows)} muutoksessanne.'
                    if fi else
                    f'{to_qty} {unit} instead of {from_qty} {unit} of {name(pid)}: you changed '
                    f'this product to {percent} % of the forecast in your last {amount(rows)} changes.')
        add('learned', pid, sentence)
    # A reply has at most MAX_SENTENCES sentences and must cover every required fact,
    # so only the learned facts that still fit the budget become required.
    budget = MAX_SENTENCES - sum(1 for fact in facts if fact['required'])
    for fact in [f for f in facts if f['kind'] == 'learned'][:max(budget, 0)]:
        fact['required'] = True
    if len(facts) > MAX_FACTS:
        # Required facts first, then a learned correction outranks every ordinary fact.
        required = [i for i, fact in enumerate(facts) if fact['required']]
        learned = [i for i, fact in enumerate(facts)
                   if fact['kind'] == 'learned' and not fact['required']]
        optional = [i for i, fact in enumerate(facts)
                    if fact['kind'] != 'learned' and not fact['required']]
        keep = set((required + learned + optional)[:MAX_FACTS])
        facts = [fact for i, fact in enumerate(facts) if i in keep]
    source = {k: proposal.get(k) for k in ('proposal_id', 'offer_id', 'offer_hash', 'status', 'request',
        'lines', 'excluded', 'alternative', 'total_ex_vat', 'expected_total', 'delivery_fee', 'shortfall', 'shortfalls', 'measure', 'mandate', 'recall_alerts', 'valid_until', 'partial_fill')}
    source['names'] = names
    source['packs'] = packs
    source['facts'] = FACTS_VERSION
    digest = hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()
    return {'source_hash': digest, 'language': language, 'facts': facts}
