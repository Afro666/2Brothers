"""Internal single-call menu reader. The gateway, not this model, matches and sizes."""
import asyncio
import base64
import binascii
import hmac
import os

from fastapi import Request

from agent.menu_photo import INSTRUCTION, SCHEMA
from agent.model import Nemotron
from agent.shelf_service import MAX_IMAGE_BYTES, MODEL_NAME, TIMEOUT, _Watched
from agent.usage import emit
from agent.vision import VisionError, image_part, read_image


def single_model():
    return Nemotron(max_attempts=1)


class MenuPhotoReader:
    def __init__(self, error, *, model_factory=single_model, timeout=TIMEOUT):
        self.error, self.model_factory, self.timeout = error, model_factory, timeout

    async def read(self, image):
        if len(image) > MAX_IMAGE_BYTES:
            raise self.error(413, 'IMAGE_TOO_LARGE')
        try:
            image_part(image)
        except VisionError:
            raise self.error(422, 'NOT_AN_IMAGE') from None
        try:
            model = self.model_factory()
        except ValueError:
            raise self.error(503, 'VISION_NOT_CONFIGURED') from None
        watched = _Watched(model)
        try:
            data = await asyncio.wait_for(read_image(watched, image, INSTRUCTION, SCHEMA, 'menu_photo'), self.timeout)
        except asyncio.TimeoutError:
            raise self.error(504, 'VISION_TIMEOUT') from None
        except VisionError:
            raise self.error(503 if watched.failed else 502,
                             'VISION_UNAVAILABLE' if watched.failed else 'VISION_REPLY_INVALID') from None
        finally:
            emit(getattr(model, 'meter', None), run='menu_photo')
            await model.close()
        return {'model': MODEL_NAME, **data}


def mount_menu_photo(app, error, reader=None):
    @app.post('/menu-photo')
    async def menu_photo(request: Request):
        token = os.environ.get('GATEWAY_AGENT_TOKEN', '')
        if not token or not hmac.compare_digest(request.headers.get('authorization', '').encode(), ('Bearer '+token).encode()):
            raise error(401, 'UNAUTHENTICATED')
        try:
            body = await request.json()
        except ValueError:
            raise error(422, 'INVALID_REQUEST') from None
        if not isinstance(body, dict) or not isinstance(body.get('image_base64'), str):
            raise error(422, 'INVALID_REQUEST')
        if body.get('kitchen_id') != os.environ.get('GATEWAY_KITCHEN_ID', 'demo-kitchen'):
            raise error(403, 'KITCHEN_SCOPE')
        if len(body['image_base64']) > MAX_IMAGE_BYTES * 4 // 3 + 4:
            raise error(413, 'IMAGE_TOO_LARGE')
        try:
            image = base64.b64decode(body['image_base64'], validate=True)
        except (binascii.Error, ValueError):
            raise error(422, 'INVALID_REQUEST') from None
        try:
            return await (reader or MenuPhotoReader(error)).read(image)
        except error:
            raise
        except Exception:
            raise error(503, 'VISION_UNAVAILABLE') from None
