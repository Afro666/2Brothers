"""Optional, asynchronous proposal detail enrichment; never on an approval/write path."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import logging
import os
import time

import httpx

from agent.explanation import checked_reply
from gateway.explanation_facts import context
from store import explanations
from store.products import get_products

MODEL = 'nemotron-3.5-super-vl'
ATTEMPTS = 2   # one retry inside the same lease and the same 20 s limit, never more (#1973)


class NotConfigured(ValueError):
    """No worker URL or token: a second try cannot help."""


def pack_of(product):
    """What one sales unit holds, from the catalog row: {'unit': 'ST', 'size': '1', 'measure': 'L'}.

    Net content of one base unit times the base units in one sales unit (store/products.py).
    None when the catalog does not give it, or when the product is sold by weight or volume."""
    unit, content = product.get('sales_unit'), product.get('net_content') or {}
    if not unit or unit in ('KG', 'L') or content.get('unit') not in ('KG', 'L'):
        return None
    count = 1 if unit == product.get('base_unit') else next(
        (row.get('size_in_base_units') for row in product.get('units') or [] if row.get('unit') == unit), None)
    try:
        size = Decimal(str(content.get('value'))) * Decimal(str(count))
    except InvalidOperation:
        return None
    if not size.is_finite() or size <= 0:
        return None
    return {'unit': unit, 'size': format(size.normalize(), 'f'), 'measure': content['unit']}


def source(gateway, proposal, language):
    ids = [l['product_id'] for l in proposal.get('lines', [])] + [l['product_id'] for l in proposal.get('excluded', [])]
    ids += [l['product_id'] for l in (proposal.get('alternative') or {}).get('lines') or []]   # named in the reason (#1868)
    products = get_products(gateway.db, ids, proposal['kitchen_id'])
    names = {p['product_id']: ((p.get('names') or {}).get(language) or (p.get('names') or {}).get('en'))
             for p in products}
    packs = {p['product_id']: pack for p in products if (pack := pack_of(p))}
    return context(proposal, names, language, packs)


async def read_worker(kitchen, payload):
    url, token = os.environ.get('BUYER_WORKER_URL'), os.environ.get('GATEWAY_AGENT_TOKEN')
    if not url or not token:
        raise NotConfigured('explanation worker is not configured')
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
    payload = source(gateway, proposal, language)
    # A stored, checked text explains a past decision: it stays readable after the offer
    # ends (#1973). Only making a new text needs a proposal that can still be approved.
    result = explanations.cached(gateway.db, kitchen, proposal['proposal_id'], payload['source_hash'], language)
    if result:
        proposal['explanation'] = result
        return proposal
    if not eligible(proposal, gateway.now()) or len(payload['facts']) < 2:
        return proposal
    lease = explanations.claim(gateway.db, kitchen, proposal['proposal_id'], payload['source_hash'], language,
                               datetime.now(timezone.utc))
    if lease:
        tasks.add_task(generate, gateway, kitchen, proposal['proposal_id'], payload, lease, actor, worker)
    return proposal


def failure(exc):
    """The reason for the log: one of our own fixed sentences or a status code, never model text (#1774)."""
    return (f'worker status {exc.response.status_code}' if isinstance(exc, httpx.HTTPStatusError)
            else str(exc) if type(exc) in (ValueError, NotConfigured) else '')


def retryable(exc):
    """A refused or broken reply can be right on a second try: the model does not answer the
    same way twice. A time-out, a missing setting or a request the worker rejects cannot."""
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException, NotConfigured)):
        return False
    return not (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500)


async def ask(worker, kitchen, ident, payload):
    """The worker's reply and its checked text. At most ATTEMPTS calls, one after the other."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            raw = await worker(kitchen, payload)
            return raw, checked_reply({'sentences': raw['sentences']}, payload['facts'], payload['language'])
        except Exception as exc:
            if attempt == ATTEMPTS or not retryable(exc):
                raise
            logging.getLogger(__name__).warning(
                'explanation attempt %s failed, one retry proposal_id=%s error=%s reason=%s',
                attempt, ident, type(exc).__name__, failure(exc))


async def generate(gateway, kitchen, ident, payload, lease, actor, worker):
    started, result, count = time.monotonic(), None, 0
    code = 'EXPLANATION_UNAVAILABLE'
    try:
        # One limit for both tries: the lease (45 s, store/explanations.py) outlives them.
        raw, text = await asyncio.wait_for(ask(worker or read_worker, kitchen, ident, payload), 20)
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
        logging.getLogger(__name__).warning('explanation generate failed proposal_id=%s code=%s error=%s reason=%s',
                                            ident, code, type(exc).__name__, failure(exc))
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
