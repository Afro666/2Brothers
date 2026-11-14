"""Checked sentence composition: quantities and claims stay bound to their source fact."""
import re
from decimal import Decimal

from jsonschema import validate

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['sentences'], 'properties': {
    'sentences': {'type': 'array', 'minItems': 2, 'maxItems': 3, 'items': {
        'type': 'object', 'additionalProperties': False,
        'required': ['fact_id', 'kind', 'product_id', 'text', 'numbers'], 'properties': {
            'fact_id': {'type': 'string'}, 'kind': {'type': 'string'},
            'product_id': {'type': ['string', 'null']}, 'text': {'type': 'string', 'maxLength': 1600},
            'numbers': {'type': 'array', 'maxItems': 50, 'items': {'type': 'string', 'maxLength': 80}}}}}}}

# A normalized comparison accepts Finnish decimal commas/grouping, never number words.
NUMBER = re.compile(r'(?<!\w)\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)*(?!\w)')


def numeric(value, language='en'):
    value = value.replace(' ', '').replace('\u00a0', '')
    if language == 'en' and re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', value):
        value = value.replace(',', '')
    return format(Decimal(value.replace(',', '.')).normalize(), 'f')


def normalized(text, language='en'):
    return NUMBER.sub(lambda m: '#' + numeric(m[0], language), text).casefold()


def numbers(text, language='en'):
    return [numeric(m[0], language) for m in NUMBER.finditer(text)]


def checked_reply(reply, facts, language='en'):
    """Metadata alone proves nothing: check the complete sentence against its own fact."""
    validate(reply, SCHEMA)
    by_id = {f['fact_id']: f for f in facts}
    seen, sentences = set(), []
    for row in reply['sentences']:
        fact = by_id.get(row['fact_id'])
        if fact is None or row['fact_id'] in seen:
            raise ValueError('unknown or repeated explanation fact')
        if row['kind'] != fact['kind'] or row['product_id'] != fact['product_id']:
            raise ValueError('explanation fact binding changed')
        candidates = [s for s in fact['forms'] if normalized(s, language) == normalized(row['text'], language)]
        if not candidates or sorted(numeric(n, language) for n in row['numbers']) != sorted(numbers(candidates[0], language)):
            raise ValueError('explanation sentence or numbers changed')
        seen.add(row['fact_id'])
        # Emit the server's original spelling/figures, not model formatting or extra text.
        sentences.append(candidates[0])
    if any(f.get('required') and f['fact_id'] not in seen for f in facts):
        raise ValueError('explanation omits an essential fact')
    return ' '.join(sentences)
