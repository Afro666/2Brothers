"""Internal single-call brief writer. The gateway prepares the rows and checks that every
number is one it supplied; this worker only holds the model key and makes the one call."""
import asyncio
import hmac
import os

from fastapi import Request

from agent.brief import (KINDS, LANGUAGES, MAX_NUMBER_CHARS, MAX_NUMBERS, MAX_REF_CHARS,
                         MAX_ROWS, MAX_VARIANT_CHARS, MAX_VARIANTS, SCHEMA, messages)
from agent.model import Nemotron
from agent.shelf_service import MODEL_NAME
from agent.usage import emit
from agent.vision import VisionError, parse_reply

TIMEOUT = 30      # seconds for the one call; the gateway waits a little longer
ROW_FIELDS = ('kind', 'ref_id', 'variants', 'numbers')
MAX_KITCHEN_CHARS = 64


def single_model():
    return Nemotron(max_attempts=1)


class BriefWriter:
    def __init__(self, error, *, model_factory=single_model, timeout=TIMEOUT):
        self.error, self.model_factory, self.timeout = error, model_factory, timeout

    async def write(self, rows, lang):
        try:
            model = self.model_factory()
        except ValueError:
            raise self.error(503, 'BRIEF_UNAVAILABLE') from None
        try:
            reply = await asyncio.wait_for(
                model.complete_json(messages(rows, lang), SCHEMA, 'kitchen_brief',
                                    max_tokens=1600, role='kitchen_brief'), self.timeout)
            data = parse_reply(reply, SCHEMA)
        except asyncio.TimeoutError:
            raise self.error(504, 'BRIEF_TIMEOUT') from None
        except VisionError:
            raise self.error(502, 'REPLY_INVALID') from None
        except RuntimeError:
            raise self.error(503, 'BRIEF_UNAVAILABLE') from None
        finally:
            emit(getattr(model, 'meter', None), run='kitchen_brief')
            await model.close()
        return {'model': MODEL_NAME, 'lines': data['lines'],
                'usage': model.meter.total() if getattr(model, 'meter', None) else None}


def _short(value, limit):
    return isinstance(value, str) and 0 < len(value) <= limit


def _rows(value):
    """Only the documented, well-formed row fields pass to the model; else a bad request."""
    if not isinstance(value, list) or not 0 < len(value) <= MAX_ROWS:
        return None
    out = []
    for row in value:
        if not isinstance(row, dict) or set(row) != set(ROW_FIELDS):
            return None
        variants = row['variants']
        if (row['kind'] not in KINDS or not _short(row['ref_id'], MAX_REF_CHARS)
                or not isinstance(variants, list) or not 0 < len(variants) <= MAX_VARIANTS
                or any(not _short(v, MAX_VARIANT_CHARS) for v in variants)
                or not isinstance(row['numbers'], list) or len(row['numbers']) > MAX_NUMBERS
                or any(not _short(n, MAX_NUMBER_CHARS) for n in row['numbers'])):
            return None
        out.append({'kind': row['kind'], 'ref_id': row['ref_id'],
                    'variants': list(variants), 'numbers': list(row['numbers'])})
    return out


def mount_brief(app, error, writer=None):
    @app.post('/brief')
    async def brief(request: Request):
        token = os.environ.get('GATEWAY_AGENT_TOKEN', '')
        if not token or not hmac.compare_digest(request.headers.get('authorization', '').encode(),
                                                ('Bearer ' + token).encode()):
            raise error(401, 'UNAUTHENTICATED')
        try:
            body = await request.json()
        except ValueError:
            raise error(422, 'INVALID_REQUEST') from None
        rows = _rows(body.get('rows')) if isinstance(body, dict) else None
        if (rows is None or not isinstance(body.get('lang'), str) or body['lang'] not in LANGUAGES
                or not _short(body.get('kitchen_id'), MAX_KITCHEN_CHARS)):
            raise error(422, 'INVALID_REQUEST')
        try:
            return await (writer or BriefWriter(error)).write(rows, body['lang'])
        except error:
            raise
        except Exception:
            raise error(503, 'BRIEF_UNAVAILABLE') from None
