"""Internal single-call request splitter (#1375). The gateway checks every quantity of the
split against the person's text; this worker only holds the model key and makes the one call."""
import asyncio
import hmac
import os

from fastapi import Request

from agent.brief_service import single_model
from agent.shelf_service import MODEL_NAME
from agent.split import MAX_TEXT, SCHEMA, messages
from agent.usage import emit
from agent.vision import VisionError, parse_reply

TIMEOUT = 35      # seconds for the one call; the gateway waits a little longer
MAX_KITCHEN_CHARS = 64


class Splitter:
    def __init__(self, error, *, model_factory=single_model, timeout=TIMEOUT):
        self.error, self.model_factory, self.timeout = error, model_factory, timeout

    async def split(self, text):
        try:
            model = self.model_factory()
        except ValueError:
            raise self.error(503, 'SPLIT_UNAVAILABLE') from None
        try:
            reply = await asyncio.wait_for(
                model.complete_json(messages(text), SCHEMA, 'request_split',
                                    max_tokens=1200, role='request_split'), self.timeout)
            data = parse_reply(reply, SCHEMA)
        except asyncio.TimeoutError:
            raise self.error(504, 'SPLIT_TIMEOUT') from None
        except VisionError:
            raise self.error(502, 'REPLY_INVALID') from None
        except RuntimeError:
            raise self.error(503, 'SPLIT_UNAVAILABLE') from None
        finally:
            emit(getattr(model, 'meter', None), run='request_split')
            await model.close()
        return {'model': MODEL_NAME, 'needs': data['needs'],
                'usage': model.meter.total() if getattr(model, 'meter', None) else None}


def mount_split(app, error, splitter=None):
    @app.post('/split')
    async def split(request: Request):
        token = os.environ.get('GATEWAY_AGENT_TOKEN', '')
        if not token or not hmac.compare_digest(request.headers.get('authorization', '').encode(),
                                                ('Bearer ' + token).encode()):
            raise error(401, 'UNAUTHENTICATED')
        try:
            body = await request.json()
        except ValueError:
            raise error(422, 'INVALID_REQUEST') from None
        text = body.get('text') if isinstance(body, dict) else None
        kitchen = body.get('kitchen_id') if isinstance(body, dict) else None
        if (not isinstance(text, str) or not 0 < len(text.strip()) <= MAX_TEXT
                or not isinstance(kitchen, str) or not 0 < len(kitchen) <= MAX_KITCHEN_CHARS):
            raise error(422, 'INVALID_REQUEST')
        try:
            return await (splitter or Splitter(error)).split(text)
        except error:
            raise
        except Exception:
            raise error(503, 'SPLIT_UNAVAILABLE') from None
