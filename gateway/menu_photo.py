"""Read a menu once, match kitchen recipes and create a normal pending plan proposal."""
import base64
from datetime import date
import hashlib
import json
import os
import re
import time

import httpx
from fastapi import Depends, Request
from jsonschema import ValidationError
from pydantic import BaseModel, Field

from agent.menu_photo import match_dishes
from gateway.request_docs import document_body
from gateway.service import GatewayError
from gateway.stock_photo import MODEL_NAME, STATUS, WORKER_TIMEOUT, _image
from store.menu_photos import cached_result
from store.repository import Repository


class MenuPhotoBody(BaseModel):
    image_base64: str
    from_date: date = Field(alias='from')
    to_date: date = Field(alias='to')
    requested_date: date | None = None
    covers: int | None = Field(default=None, ge=0)
    idempotency_key: str = Field(min_length=1, max_length=200)


def error(code):
    return GatewayError(STATUS.get(code, 503), code, 'Menu photo could not be read; plan the week by hand')


async def read_menu_photo(kitchen_id, encoded):
    url, token = os.environ.get('BUYER_WORKER_URL', ''), os.environ.get('GATEWAY_AGENT_TOKEN', '')
    if not url or not token:
        raise error('VISION_NOT_CONFIGURED')
    try:
        async with httpx.AsyncClient(timeout=WORKER_TIMEOUT, follow_redirects=False, trust_env=False) as client:
            r = await client.post(url.rstrip('/') + '/menu-photo',
                                 json={'kitchen_id': kitchen_id, 'image_base64': encoded},
                                 headers={'Authorization': 'Bearer '+token})
        data = r.json()
    except httpx.TimeoutException:
        raise error('VISION_TIMEOUT') from None
    except (httpx.HTTPError, ValueError):
        raise error('VISION_UNAVAILABLE') from None
    if not r.is_success:
        detail = data.get('error') if isinstance(data, dict) else None
        code = detail.get('code') if isinstance(detail, dict) else None
        raise error(code if isinstance(code, str) and code in STATUS else 'VISION_UNAVAILABLE')
    return data


def window(body):
    values = []
    for field in ('from', 'to', 'requested_date'):
        value = (body.get(field) or body.get('from')) if field == 'requested_date' else body.get(field)
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise GatewayError(422, 'INVALID_REQUEST', 'from, to and requested_date must be YYYY-MM-DD')
        try:
            values.append(date.fromisoformat(value))
        except ValueError:
            raise GatewayError(422, 'INVALID_REQUEST', 'invalid date') from None
    start, end, delivery = values
    if end < start or (end-start).days > 31:
        raise GatewayError(422, 'INVALID_REQUEST', 'from must be on or before to, at most 31 days apart')
    key, covers = body.get('idempotency_key'), body.get('covers')
    if not isinstance(key, str) or not key.strip() or len(key) > 200:
        raise GatewayError(422, 'INVALID_REQUEST', 'a nonempty idempotency_key up to 200 characters is required')
    if covers is not None and (type(covers) is not int or covers < 0):
        raise GatewayError(422, 'INVALID_REQUEST', 'covers must be a nonnegative integer')
    return start, end, delivery, key, covers


def mount_menu_photo(app, gw, principal, worker=None):
    busy = set()

    @app.post('/v1/kitchens/{kitchen_id}/menu-photo', openapi_extra=document_body(MenuPhotoBody))
    async def menu_photo(kitchen_id: str, request: Request, who=Depends(principal)):
        who.need('kitchen:write', kitchen_id)
        who.need('kitchen:propose', kitchen_id)
        encoded, body = await _image(request, with_body=True)
        start, end, delivery, key, covers = window(body)
        started = time.monotonic()
        facts = {'from': start.isoformat(), 'to': end.isoformat(), 'requested_date': delivery.isoformat(), 'covers': covers}
        fingerprint = hashlib.sha256(base64.b64decode(encoded) + b'\0' + json.dumps(facts, sort_keys=True).encode()).hexdigest()
        cached = cached_result(gw().db, kitchen_id, key)
        if cached is not None:
            if cached['fingerprint'] != fingerprint or cached['response'] is None:
                raise GatewayError(409, 'IDEMPOTENCY_KEY_REUSED', 'key used with another request')
            duration = round((time.monotonic()-started)*1000)
            gw()._audit(kitchen_id, 'menu_photo_read', who.name, window={'from': start.isoformat(), 'to': end.isoformat()},
                        statuses={kind: sum(d['status'] == kind for d in cached['response']['dishes'])
                                  for kind in ('MATCHED', 'NOT_KNOWN')},
                        proposal_id=cached['proposal']['proposal_id'], no_proposal_reason=None,
                        model=MODEL_NAME, duration_ms=duration)
            return {**cached['response'], 'proposal': cached['proposal'], 'duration_ms': duration}
        if kitchen_id in busy:
            raise GatewayError(429, 'MENU_PHOTO_BUSY', 'a menu photo is already being read for this kitchen')
        busy.add(kitchen_id)
        try:
            raw = await (worker or read_menu_photo)(kitchen_id, encoded)
            try:
                # Ignore only the worker's canonical model label; all model-read fields
                # are validated again before they can influence recipe selection.
                data = {k: v for k, v in raw.items() if k != 'model'}
                dishes = match_dishes(data, Repository(gw().db).recipes.list(kitchen_id), start, end, covers)
            except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
                raise error('VISION_REPLY_INVALID') from None
            if not any(d['status'] == 'MATCHED' for d in dishes):
                raise GatewayError(422, 'NOTHING_MATCHED', 'no dish matches one kitchen recipe', dishes=dishes)
            response = {'model': MODEL_NAME, 'from': start.isoformat(), 'to': end.isoformat(), 'dishes': dishes,
                        'no_proposal_reason': None}
            entries = [{'date': d['day'], 'recipe_id': d['recipe_id'], 'covers': d['covers']}
                       for d in dishes if d['in_proposal']]
            proposal = None
            if not entries:
                response['no_proposal_reason'] = 'NOT_SIZED'
            else:
                try:
                    made = gw().create_proposal(kitchen_id, {'from': start.isoformat(), 'to': end.isoformat(),
                            'requested_date': delivery.isoformat(), 'idempotency_key': key}, who.name,
                            auto_approve=False, plan_entries=entries,
                            menu_photo={'fingerprint': fingerprint, 'response': response})
                    proposal = {'proposal_id': made['proposal_id'], 'status': made['status']}
                except GatewayError as exc:
                    if exc.code != 'NOTHING_NEEDED':
                        raise
                    response['no_proposal_reason'] = 'NOTHING_NEEDED'
            duration = round((time.monotonic()-started)*1000)
            gw()._audit(kitchen_id, 'menu_photo_read', who.name, window={'from': start.isoformat(), 'to': end.isoformat()},
                        statuses={kind: sum(d['status'] == kind for d in dishes) for kind in ('MATCHED', 'NOT_KNOWN')},
                        proposal_id=proposal['proposal_id'] if proposal else None,
                        no_proposal_reason=response['no_proposal_reason'], model=MODEL_NAME, duration_ms=duration)
            return {**response, 'proposal': proposal, 'duration_ms': duration}
        except GatewayError as exc:
            gw()._audit(kitchen_id, 'menu_photo_failed', who.name, code=exc.code, model=MODEL_NAME,
                        duration_ms=round((time.monotonic()-started)*1000))
            raise
        finally:
            busy.discard(kitchen_id)
