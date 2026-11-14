"""Internal single-call buying-note writer (#1176). The gateway picks the rows and checks
every number of the reply; this worker only holds the model key and makes the one call."""
import asyncio
import hmac
import os

from fastapi import Request

from agent.buying_note import LANGUAGES, MAX_ROWS, SCHEMA, messages
from agent.model import Nemotron
from agent.shelf_service import MODEL_NAME
from agent.usage import emit
from agent.vision import VisionError, parse_reply

TIMEOUT = 30      # seconds for the one call; the gateway waits a little longer
ROW_FIELDS = ('row', 'product_id', 'product_name', 'date', 'unit', 'demand', 'kitchens',
              'available', 'shortage', 'suggested_buy', 'risk')


def single_model():
    return Nemotron(max_attempts=1)


class BuyingNoteWriter:
    def __init__(self, error, *, model_factory=single_model, timeout=TIMEOUT):
        self.error, self.model_factory, self.timeout = error, model_factory, timeout

    async def write(self, rows, lang):
        try:
            model = self.model_factory()
        except ValueError:
            raise self.error(503, 'BUYING_NOTE_UNAVAILABLE') from None
        try:
            reply = await asyncio.wait_for(
                model.complete_json(messages(rows, lang), SCHEMA, 'buying_note', max_tokens=1200,
                                    role='buying_note'), self.timeout)
            data = parse_reply(reply, SCHEMA)
        except asyncio.TimeoutError:
            raise self.error(504, 'BUYING_NOTE_TIMEOUT') from None
        except VisionError:
            raise self.error(502, 'REPLY_INVALID') from None
        except RuntimeError:
            raise self.error(503, 'BUYING_NOTE_UNAVAILABLE') from None
        finally:
            emit(getattr(model, 'meter', None), run='buying_note')
            await model.close()
        return {'model': MODEL_NAME, **data}


def _rows(value):
    """Only the documented row fields pass to the model; anything else is a bad request."""
    if not isinstance(value, list) or not 0 < len(value) <= MAX_ROWS:
        return None
    out = []
    for i, row in enumerate(value):
        if not isinstance(row, dict) or row.get('row') != i or set(row) - set(ROW_FIELDS):
            return None
        out.append({k: row.get(k) for k in ROW_FIELDS})
    return out


def mount_buying_note(app, error, writer=None):
    @app.post('/buying-note')
    async def buying_note(request: Request):
        token = os.environ.get('GATEWAY_AGENT_TOKEN', '')
        if not token or not hmac.compare_digest(request.headers.get('authorization', '').encode(),
                                                ('Bearer ' + token).encode()):
            raise error(401, 'UNAUTHENTICATED')
        try:
            body = await request.json()
        except ValueError:
            raise error(422, 'INVALID_REQUEST') from None
        rows = _rows(body.get('rows')) if isinstance(body, dict) else None
        if rows is None or body.get('lang') not in LANGUAGES or not isinstance(body.get('supplier_id'), str):
            raise error(422, 'INVALID_REQUEST')
        try:
            return await (writer or BuyingNoteWriter(error)).write(rows, body['lang'])
        except error:
            raise
        except Exception:
            raise error(503, 'BUYING_NOTE_UNAVAILABLE') from None
