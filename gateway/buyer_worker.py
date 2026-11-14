"""Authenticated internal worker handoff for free-text proposal requests."""
import os
import httpx
from gateway.service import GatewayError


async def run_buyer(kitchen_id, body):
    url = os.environ.get('BUYER_WORKER_URL', '')
    token = os.environ.get('GATEWAY_AGENT_TOKEN', '')
    if not url or not token:
        raise GatewayError(503, 'BUYER_UNAVAILABLE', 'Buyer worker is not configured')
    payload = {k: body[k] for k in ('text', 'requested_date', 'idempotency_key') if k in body}
    if body.get('event') is True:
        payload['event'] = True     # one-off demand (S05): the need keeps it, every line gets EVENT_LINE (#530)
    payload['kitchen_id'] = kitchen_id
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
        raise GatewayError(response.status_code if response.status_code in (400, 403, 409, 422, 503, 504) else 503,
                           code if isinstance(code, str) and code in allowed else 'BUYER_UNAVAILABLE',
                           'Buyer request did not complete; reconcile the existing request before retrying',
                           fallback_safe=error.get('fallback_safe') is True)
    if not isinstance(data, dict) or not isinstance(data.get('proposal_id'), str):
        raise GatewayError(503, 'BUYER_RECONCILIATION_REQUIRED', 'Buyer did not return a proposal receipt')
    return data
