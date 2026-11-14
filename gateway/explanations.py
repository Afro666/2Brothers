"""Optional, asynchronous proposal detail enrichment; never on an approval/write path."""
import asyncio
from datetime import datetime, timezone
import logging
import os
import time

import httpx

from agent.explanation import checked_reply
from gateway.explanation_facts import context
from store import explanations
from store.products import get_products

MODEL = 'nemotron-3.5-super-vl'


def source(gateway, proposal, language):
    ids = [l['product_id'] for l in proposal.get('lines', [])] + [l['product_id'] for l in proposal.get('excluded', [])]
    names = {p['product_id']: ((p.get('names') or {}).get(language) or (p.get('names') or {}).get('en'))
             for p in get_products(gateway.db, ids, proposal['kitchen_id'])}
    return context(proposal, names, language)


async def read_worker(kitchen, payload):
    url, token = os.environ.get('BUYER_WORKER_URL'), os.environ.get('GATEWAY_AGENT_TOKEN')
    if not url or not token:
        raise ValueError('explanation worker is not configured')
    async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as client:
        response = await client.post(url.rstrip('/') + '/explain', json={'kitchen_id': kitchen, **payload},
                                     headers={'Authorization': 'Bearer '+token})
        response.raise_for_status()
        return response.json()


def eligible(proposal, now):
    if proposal['status'] != 'READY':
        return False
    until = proposal['valid_until']
    if isinstance(until, str):
        until = datetime.fromisoformat(until.replace('Z', '+00:00'))
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until > now


def enrich(gateway, kitchen, proposal, language, tasks, actor, worker=None):
    """Return immediately; duplicate viewers share the same durable claim."""
    proposal = {**proposal, 'kitchen_id': kitchen, 'explanation': None}
    if not eligible(proposal, gateway.now()):
        return proposal
    payload = source(gateway, proposal, language)
    result = explanations.cached(gateway.db, kitchen, proposal['proposal_id'], payload['source_hash'], language)
    if result:
        proposal['explanation'] = result
        return proposal
    if len(payload['facts']) < 2:
        return proposal
    lease = explanations.claim(gateway.db, kitchen, proposal['proposal_id'], payload['source_hash'], language,
                               datetime.now(timezone.utc))
    if lease:
        tasks.add_task(generate, gateway, kitchen, proposal['proposal_id'], payload, lease, actor, worker)
    return proposal


async def generate(gateway, kitchen, ident, payload, lease, actor, worker):
    started, result, count = time.monotonic(), None, 0
    code = 'EXPLANATION_UNAVAILABLE'
    try:
        raw = await asyncio.wait_for((worker or read_worker)(kitchen, payload), 20)
        text = checked_reply({'sentences': raw['sentences']}, payload['facts'], payload['language'])
        def current_matches():
            current = {**gateway.get_proposal(kitchen, ident), 'kitchen_id': kitchen}
            return eligible(current, gateway.now()) and source(gateway, current, payload['language'])['source_hash'] == payload['source_hash']
        if not await asyncio.to_thread(current_matches):
            code = 'EXPLANATION_STALE'
        else:
            count = len(raw['sentences'])
            result = {'text': text, 'language': payload['language'], 'model': MODEL, 'checked': True,
                'source_hash': payload['source_hash'], 'duration_ms': round((time.monotonic()-started)*1000)}
    except Exception as exc:
        # Failure is optional UI enrichment, never an HTTP/card/approval failure.
        # The reason is one of our own fixed sentences or a status code, never model text (#1774).
        reason = (f'worker status {exc.response.status_code}' if isinstance(exc, httpx.HTTPStatusError)
                  else str(exc) if type(exc) is ValueError else '')
        logging.getLogger(__name__).warning('explanation generate failed proposal_id=%s code=%s error=%s reason=%s',
                                            ident, code, type(exc).__name__, reason)
    finally:
        try:
            await asyncio.to_thread(explanations.finish, gateway.db, lease, result, datetime.now(timezone.utc))
        except Exception:
            # An interrupted/unavailable store leaves a bounded lease, recoverable later.
            result = None
        try:
            await asyncio.to_thread(gateway._audit, kitchen, 'proposal_explanation_ready' if result else 'proposal_explanation_failed', actor,
                proposal_id=ident, source_hash=payload['source_hash'], language=payload['language'], model=MODEL,
                duration_ms=round((time.monotonic()-started)*1000), sentence_count=count,
                **({} if result else {'code': code}))
        except Exception:
            pass
