"""Authenticated internal worker handoff for free-text proposal requests."""
from datetime import date, datetime
import os
import time
from zoneinfo import ZoneInfo

import httpx
from gateway.parse import ParseError, named_day
from gateway.service import GatewayError


BREAKER_SECONDS = 120


def _clock() -> float:
    return time.monotonic()


class Breaker:
    """After one BUYER_TIMEOUT, typed requests skip the model for BREAKER_SECONDS and the
    parser answers at once (live 2026-11-14: Nemotron did not answer, each request waited
    about 150 s). The first request after the window asks the model again; an answer closes
    it. No restart, no flag: when the model is back, nothing changes."""

    def __init__(self, now=None):
        self._now = now or (lambda: _clock())
        self._open_until = 0.0

    def is_open(self) -> bool:
        return self._now() < self._open_until

    def trip(self) -> None:
        self._open_until = self._now() + BREAKER_SECONDS

    def reset(self) -> None:
        self._open_until = 0.0


def _today() -> date:
    return datetime.now(ZoneInfo('Europe/Helsinki')).date()     # the worker's own "today"


def buyer_payload(kitchen_id, body):
    """What the worker gets. A day named in the text wins over `requested_date` of the body
    (the date picked in a form): live on 2026-11-14 "by Monday" was quoted for the form's
    Tuesday. The worker reads the body's date first, so the gateway reads the text here."""
    payload = {k: body[k] for k in ('text', 'requested_date', 'idempotency_key') if k in body}
    if body.get('event') is True:
        payload['event'] = True     # one-off demand (S05): the need keeps it, every line gets EVENT_LINE (#530)
    payload['kitchen_id'] = kitchen_id
    try:
        named = named_day(body['text'], _today()) if isinstance(body.get('text'), str) else None
    except ParseError:
        named = None                # not a real date: the worker and the parser say so
    if named is not None:
        payload['requested_date'] = named.isoformat()
    return payload


async def run_buyer(kitchen_id, body):
    url = os.environ.get('BUYER_WORKER_URL', '')
    token = os.environ.get('GATEWAY_AGENT_TOKEN', '')
    if not url or not token:
        raise GatewayError(503, 'BUYER_UNAVAILABLE', 'Buyer worker is not configured')
    payload = buyer_payload(kitchen_id, body)
    try:
        async with httpx.AsyncClient(timeout=165, follow_redirects=False, trust_env=False) as client:
            response = await client.post(url.rstrip('/') + '/run', json=payload,
                                         headers={'Authorization': 'Bearer ' + token})
        data = response.json()
    except (httpx.HTTPError, ValueError):
        raise GatewayError(503, 'BUYER_RECONCILIATION_REQUIRED', 'Check existing proposals before retrying') from None
    if not response.is_success:
        error = data.get('error', {}) if isinstance(data, dict) else {}
        allowed = {'NEED_DETAILS', 'NEED_DATE', 'INVALID_REQUEST', 'INVALID_QUANTITY', 'INVALID_DATE',
                   'MISSING_IDEMPOTENCY_KEY', 'IDEMPOTENCY_KEY_REUSED', 'BUYER_TIMEOUT',
                   'BUYER_INCOMPLETE', 'BUYER_UNAVAILABLE', 'BUYER_RECONCILIATION_REQUIRED', 'KITCHEN_SCOPE',
                   'KITCHEN_POLICY_INVALID'}
        code = error.get('code')
        code = code if isinstance(code, str) and code in allowed else 'BUYER_UNAVAILABLE'
        status = response.status_code if response.status_code in (400, 403, 409, 422, 503, 504) else 503
        if code == 'KITCHEN_POLICY_INVALID':
            status = 409    # one status per code, as docs/contract.md lists it
        raise GatewayError(status, code,
                           'Buyer request did not complete; reconcile the existing request before retrying',
                           fallback_safe=error.get('fallback_safe') is True)
    if not isinstance(data, dict) or not isinstance(data.get('proposal_id'), str):
        raise GatewayError(503, 'BUYER_RECONCILIATION_REQUIRED', 'Buyer did not return a proposal receipt')
    return data
