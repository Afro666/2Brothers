"""Checked kitchen briefs: source facts survive model failure, line by line (#1332)."""
import asyncio
import hashlib
import json
import os
import time

import httpx
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool

from gateway.claim_check import check_sentence
from gateway.service import GatewayError

MODEL = 'nemotron-3.5-super-vl'
CACHE_SECONDS = 300
FALLBACK_SECONDS = 30
MAX_CACHE = 128


def checked_lines(reply, rows, lang):
    """Only a complete sentence grounded in its own row may replace the rule line."""
    raw = reply.get('lines') if isinstance(reply, dict) else None
    raw = raw if isinstance(raw, list) else []
    out, accepted = [], 0
    for i, row in enumerate(rows):
        candidate = raw[i] if i < len(raw) and isinstance(raw[i], dict) else {}
        ok = (set(candidate) == {'text', 'kind', 'ref_id', 'numbers'}
              and candidate.get('kind') == row['kind']
              and candidate.get('ref_id') == row['ref_id']
              and candidate.get('text') in row['variants'])
        if ok:
            ok = check_sentence(candidate['text'], candidate.get('numbers'), row['numbers'], lang) is None
        accepted += int(ok)
        out.append({'text': candidate['text'] if ok else row['variants'][0],
                    'kind': row['kind'], 'ref_id': row['ref_id'], 'urgent': row['urgent']})
    return out, accepted


async def write_brief(kitchen, rows, lang):
    url, token = os.environ.get('BUYER_WORKER_URL'), os.environ.get('GATEWAY_AGENT_TOKEN')
    if not url or not token:
        return None
    payload = [{k: row[k] for k in ('kind', 'ref_id', 'variants', 'numbers')} for row in rows]
    async with httpx.AsyncClient(timeout=35, trust_env=False, follow_redirects=False) as client:
        result = await client.post(url.rstrip('/') + '/brief',
                                   json={'kitchen_id': kitchen, 'rows': payload, 'lang': lang},
                                   headers={'Authorization': 'Bearer ' + token})
        result.raise_for_status()
        return result.json()


def mount_brief(app, gw, principal, worker=None, *, collector=None, clock=time.monotonic):
    from gateway.brief_facts import collect
    cache, busy = {}, set()

    @app.get('/v1/kitchens/{kitchen_id}/brief')
    async def brief(kitchen_id: str, request: Request, who=Depends(principal)):
        started = clock()
        who.need('kitchen:read', kitchen_id)
        params = request.query_params
        if (set(params) != {'when', 'lang'} or any(len(params.getlist(k)) != 1 for k in params)
                or params['when'] not in ('morning', 'evening') or params['lang'] not in ('en', 'fi')):
            raise GatewayError(422, 'INVALID_REQUEST', 'when must be morning/evening and lang en/fi')
        when, lang = params['when'], params['lang']
        gateway = gw()
        rows = await run_in_threadpool(collector or collect, gateway, kitchen_id, when, lang)
        key = hashlib.sha256(json.dumps([kitchen_id, when, lang, rows], sort_keys=True).encode()).hexdigest()
        now = clock()
        for old, (at, result) in list(cache.items()):
            if now - at >= (CACHE_SECONDS if result['made_by'] == 'model' else FALLBACK_SECONDS):
                cache.pop(old, None)
        cached, accepted = False, 0
        if key in cache:
            result = dict(cache[key][1])
            accepted = result.pop('_accepted')
            cached = True
        else:
            reply = None
            attempted = bool(rows and (worker or (os.environ.get('BUYER_WORKER_URL')
                                                  and os.environ.get('GATEWAY_AGENT_TOKEN'))))
            if attempted and key not in busy:
                busy.add(key)
                try:
                    reply = await asyncio.wait_for((worker or write_brief)(kitchen_id, rows, lang), 35)
                except Exception:
                    # Upstream text can contain credentials; only deterministic facts leave here.
                    reply = None
                finally:
                    busy.discard(key)
                # Approval/recall state may change while the provider is queued.
                current = await run_in_threadpool(collector or collect, gateway, kitchen_id, when, lang)
                if current != rows:
                    rows, reply = current, None
                    key = hashlib.sha256(json.dumps([kitchen_id, when, lang, rows], sort_keys=True).encode()).hexdigest()
            else:
                attempted = False
            lines, accepted = checked_lines(reply, rows, lang)
            result = {'when': when, 'lang': lang, 'lines': lines,
                      'made_by': 'model' if rows and accepted == len(rows) else 'mixed' if accepted else 'rule',
                      'nothing_urgent': not bool(rows), 'model': MODEL if attempted else None}
            # A follower's immediate fallback must not overwrite an in-flight result.
            if key not in busy:
                if len(cache) >= MAX_CACHE:
                    cache.pop(next(iter(cache)))
                cache[key] = (clock(), {**result, '_accepted': accepted})
        result['duration_ms'] = round((clock() - started) * 1000)
        await run_in_threadpool(gateway._audit, kitchen_id, 'kitchen_brief_read', who.name,
                               rows=len(rows), model_lines=accepted, rule_lines=len(rows)-accepted,
                               duration_ms=result['duration_ms'], cached=cached, when=when, lang=lang)
        return result
