"""Checked sentence composition: quantities and claims stay bound to their source fact."""
import re
from decimal import Decimal, InvalidOperation

from jsonschema import validate

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['sentences'], 'properties': {
    'sentences': {'type': 'array', 'minItems': 2, 'maxItems': 3, 'items': {
        'type': 'object', 'additionalProperties': False,
        'required': ['fact_id', 'kind', 'product_id', 'text', 'numbers'], 'properties': {
            'fact_id': {'type': 'string'}, 'kind': {'type': 'string'},
            'product_id': {'type': ['string', 'null']}, 'text': {'type': 'string', 'maxLength': 1600},
            'numbers': {'type': 'array', 'maxItems': 50, 'items': {'type': 'string', 'maxLength': 80}}}}}}}

# A normalized comparison accepts Finnish decimal commas/grouping, never number words.
NUMBER = re.compile(r'(?<!\w)\d+(?:[ \u00a0]\d{3})*(?:(?:,\d{3})+(?:\.\d+)?|[.,]\d+)?(?!\w)')


def numeric(value, language='en'):
    value = value.replace(' ', '').replace('\u00a0', '')
    if language == 'en' and re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?', value):
        value = value.replace(',', '')
    try:
        number = Decimal(value.replace(',', '.'))
        if not number.is_finite():
            raise ValueError('nonfinite explanation number')
        return format(number.normalize(), 'f')
    except InvalidOperation:
        raise ValueError('invalid explanation number') from None


def normalized(text, language='en'):
    return NUMBER.sub(lambda m: '#' + numeric(m[0], language), text).casefold()


def numbers(text, language='en'):
    return [numeric(m[0], language) for m in NUMBER.finditer(text)]


# The same number, also when it is glued to a unit or a sign: the "1" of "1L", "1,5%" (#1774).
GLUED = re.compile(NUMBER.pattern.replace(r'(?<!\w)', '').replace(r'(?!\w)', ''))


def glued_numbers(text, language='en'):
    return [numeric(m[0], language) for m in GLUED.finditer(text)]


def listed_numbers(values, language='en'):
    """The reply's `numbers` as values. An entry may carry its unit ("1L"), never no number."""
    out = []
    for value in values:
        found = glued_numbers(value, language)
        if not found:
            raise ValueError('invalid explanation number')
        out += found
    return sorted(out)


def numbers_match(listed, sentence, language='en'):
    """The prompt asks for every printed number, so a model also lists one glued to a unit
    in a product name. Both readings of the server's own sentence are right, nothing else."""
    got = listed_numbers(listed, language)
    return got in (sorted(numbers(sentence, language)), sorted(glued_numbers(sentence, language)))


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
        if not candidates or not numbers_match(row['numbers'], candidates[0], language):
            raise ValueError('explanation sentence or numbers changed')
        seen.add(row['fact_id'])
        # Emit the server's original spelling/figures, not model formatting or extra text.
        sentences.append(candidates[0])
    if any(f.get('required') and f['fact_id'] not in seen for f in facts):
        raise ValueError('explanation omits an essential fact')
    return ' '.join(sentences)
