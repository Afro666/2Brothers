"""Internal worker endpoint for "Snap the shelf" (#373): POST /shelf.

The gateway's `POST /v1/kitchens/{k}/stock/photo` hands the photo to this worker, because
the model key (VERDA_INFERENCE_KEY) lives here and not in the gateway container. The
reading itself is agent/shelf.py and agent/vision.py, unchanged: this file only loads the
kitchen's products, calls `read_shelf` with the live Nemotron model and answers the rows
in the contract's shape (docs/contract.md "Count from a shelf photo").

It writes nothing. A number leaves this file only for a COUNTED row whose pack size is
known; everything else is `count: null` (unknown, never zero).
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from decimal import Decimal
import hmac
import os
from types import SimpleNamespace

from fastapi import Request

from agent.model import Nemotron
from agent.usage import emit
from agent.shelf import read_shelf
from agent.vision import VisionError, image_part

MODEL_NAME = 'nemotron-3.5-super-vl'
MAX_IMAGE_BYTES = 4 * 1024 * 1024
TIMEOUT = 75        # seconds for the one vision call; the gateway waits a little longer


def _pack_size(doc: dict, unit: str) -> str | None:
    """Kitchen units in one pack, or None when it is not known (never a guess)."""
    if unit == 'PCS':
        return '1'                                  # counted per pack: one pack is one piece
    content = doc.get('net_content') or {}
    if doc.get('net_content_source') == 'base_unit':
        return None                                 # sold by weight: a pack has no fixed size
    if content.get('unit') != unit or not content.get('value'):
        return None
    return format(Decimal(str(content['value'])).normalize(), 'f')


def kitchen_products(db, kitchen_id: str) -> list[dict]:
    """What a shelf label can match: the kitchen's stock list and its own products, as
    `{product_id, name, unit, pack_size}`. A product without a name cannot be matched."""
    from store.history import current_stock
    from store.products import get_products
    from store.repository import Repository
    units = {row['product_id']: row['unit'] for row in current_stock(db, kitchen_id)}
    own = [row['product_id'] for row in Repository(db).own_products.list(kitchen_id)]
    products = []
    for doc in get_products(db, list(units) + own, kitchen_id):
        name = (doc.get('names') or {}).get('en')
        if not name:
            continue
        # A product that was never counted is counted in its net content's unit, else in PCS.
        unit = units.get(doc['product_id']) or (doc.get('net_content') or {}).get('unit') or 'PCS'
        products.append({'product_id': doc['product_id'], 'name': name, 'unit': unit,
                         'pack_size': _pack_size(doc, unit)})
    return products


def contract_rows(rows: list[dict], products: list[dict]) -> list[dict]:
    """agent.shelf rows -> the contract's rows. A COUNTED row keeps its number only when
    the pack size is known and no other row for the same product asks for a count."""
    by_id = {p['product_id']: p for p in products}
    unsure = {r['product_id'] for r in rows if r['status'] == 'PLEASE_COUNT'}
    unsure |= {r['product_id'] for r in rows
               if r['status'] == 'COUNTED' and by_id[r['product_id']]['pack_size'] is None}
    out = []
    for r in rows:
        product = by_id.get(r['product_id'])
        kind = 'PLEASE_COUNT' if r['status'] == 'COUNTED' and r['product_id'] in unsure else r['status']
        packs = r['packs'] if kind == 'COUNTED' else None
        count = None if packs is None else format(
            (Decimal(packs) * Decimal(product['pack_size'])).normalize(), 'f')
        out.append({'row': kind, 'product_id': r['product_id'], 'product_name': r['name'],
                    'label': r['label'], 'confidence': r['confidence'], 'packs': packs,
                    'pack_size': product and product['pack_size'], 'count': count,
                    'unit': product and product['unit']})
    return out


class _Watched:
    """Passes calls to the model and remembers whether the model itself failed, so a
    failed call and a reply outside the schema get different error codes."""

    def __init__(self, model):
        self.model, self.failed = model, False

    async def complete_json(self, *args, **kwargs):
        try:
            return await self.model.complete_json(*args, **kwargs)
        except RuntimeError:
            self.failed = True
            raise


class ShelfReader:
    def __init__(self, db, error, *, model_factory=Nemotron, timeout=TIMEOUT):
        self.db, self.error, self.model_factory, self.timeout = db, error, model_factory, timeout

    async def read(self, kitchen_id: str, image: bytes) -> dict:
        if len(image) > MAX_IMAGE_BYTES:
            raise self.error(413, 'IMAGE_TOO_LARGE')
        try:
            image_part(image)                       # PNG or JPEG, not empty (agent/vision.py)
        except VisionError:
            raise self.error(422, 'NOT_AN_IMAGE') from None
        products = kitchen_products(self.db, kitchen_id)
        try:
            model = self.model_factory()
        except ValueError:                          # no VERDA_INFERENCE_KEY in this container
            raise self.error(503, 'VISION_NOT_CONFIGURED') from None
        watched = _Watched(model)
        photo = SimpleNamespace(read_bytes=lambda: image)   # read_shelf reads a Path
        try:
            rows = await asyncio.wait_for(read_shelf(photo, products, watched), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise self.error(504, 'VISION_TIMEOUT') from None
        except VisionError:
            if watched.failed:
                raise self.error(503, 'VISION_UNAVAILABLE') from None
            raise self.error(502, 'VISION_REPLY_INVALID') from None
        finally:
            emit(getattr(model, 'meter', None), run='shelf')
            await model.close()
        return {'model': MODEL_NAME, 'rows': contract_rows(rows, products)}


def mount_shelf(app, error, reader=None) -> None:
    """Add POST /shelf to the worker app. `error` is the worker's WorkerError; `reader` is
    for tests (a ShelfReader on a test database with a recorded model)."""
    state = {}

    @app.post('/shelf')
    async def shelf(request: Request):
        token = os.environ.get('GATEWAY_AGENT_TOKEN', '')
        given = request.headers.get('authorization', '')
        if not token or not hmac.compare_digest(given.encode(), ('Bearer ' + token).encode()):
            raise error(401, 'UNAUTHENTICATED')
        try:
            body = await request.json()
        except ValueError:
            raise error(422, 'INVALID_REQUEST') from None
        if not isinstance(body, dict) or not isinstance(body.get('image_base64'), str):
            raise error(422, 'INVALID_REQUEST')
        kitchen = os.environ.get('GATEWAY_KITCHEN_ID', 'demo-kitchen')
        if body.get('kitchen_id') != kitchen:
            raise error(403, 'KITCHEN_SCOPE')
        if len(body['image_base64']) > MAX_IMAGE_BYTES * 4 // 3 + 4:
            raise error(413, 'IMAGE_TOO_LARGE')
        try:
            image = base64.b64decode(body['image_base64'], validate=True)
        except (binascii.Error, ValueError):
            raise error(422, 'INVALID_REQUEST') from None
        current = reader
        if current is None:
            if not state:
                from store.db import get_db
                state['reader'] = ShelfReader(get_db(), error)
            current = state['reader']
        try:
            return await current.read(kitchen, image)
        except error:
            raise
        except Exception:
            raise error(503, 'VISION_UNAVAILABLE') from None
