"""Internal bounded Nemotron worker; proposes only, never approves or orders."""
import asyncio
from datetime import date, datetime, timedelta
import hmac
import os
import re
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.shared.memory import create_connected_server_and_client_session

from agent.model import Nemotron
from agent.runner import Buyer
from agent.usage import emit
from gateway.mcp_server import GatewayClient, build_server
from store import agent_runs
from store import buyer_context
from agent.substitutes import AllergenPolicy, SubstitutePlanner
from store.orders import IdempotencyConflict


class WorkerError(Exception):
    def __init__(self, status, code, *, fallback_safe=False):
        self.status, self.code, self.fallback_safe = status, code, fallback_safe


def parse_need(body, *, today=None):
    """Extract only an unambiguous explicit quantity; never ask a model to size it."""
    text = body.get('text')
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
        raise WorkerError(422, 'INVALID_REQUEST')
    matches = re.findall(r'(?<![\w.,+\-])((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(litres?|liters?|kg|kilograms?|pcs|pieces?|l)\b', text, re.I)
    if len(matches) != 1:
        raise WorkerError(422, 'NEED_DETAILS', fallback_safe=True)
    quantity, unit = matches[0]
    quantity = quantity.replace(',', '')
    if not 0 < float(quantity) <= 1_000_000:
        raise WorkerError(422, 'INVALID_QUANTITY')
    unit = 'L' if unit.lower() in ('l', 'litre', 'litres', 'liter', 'liters') else ('KG' if unit.lower() in ('kg', 'kilogram', 'kilograms') else 'PCS')
    requested = body.get('requested_date')
    if requested is None:
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        mentioned = [i for i, day in enumerate(days) if re.search(r'\b' + day + r'\b', text, re.I)]
        if len(mentioned) != 1:
            raise WorkerError(422, 'NEED_DATE', fallback_safe=True)
        today = today or datetime.now(ZoneInfo('Europe/Helsinki')).date()
        requested = (today + timedelta(days=(mentioned[0] - today.weekday()) % 7 or 7)).isoformat()
    try:
        requested = date.fromisoformat(requested).isoformat()
    except (ValueError, TypeError):
        raise WorkerError(422, 'INVALID_DATE') from None
    need = {'quantity': quantity, 'unit': unit, 'requested_date': requested, 'text': text.strip()}
    if body.get('event') is True:
        need['event'] = True    # one-off demand: the gateway marks every line EVENT_LINE (#530)
    return need


class BuyerWorker:
    def __init__(self, db, gateway, *, model_factory=Nemotron, timeout=150, now=None):
        self.db, self.gateway, self.model_factory, self.timeout = db, gateway, model_factory, timeout
        self.now = now

    async def run(self, kitchen_id, body):
        need = parse_need(body)
        key = body.get('idempotency_key')
        if not isinstance(key, str) or not 1 <= len(key.strip()) <= 200:
            raise WorkerError(422, 'MISSING_IDEMPOTENCY_KEY')
        exclusions = buyer_context.excluded_allergens(self.db, kitchen_id)
        try:
            policy = AllergenPolicy(tuple(exclusions)) if exclusions is not None else None
        except ValueError:
            # A misspelt allergen code must never silently widen what is safe: fail closed.
            raise WorkerError(503, 'KITCHEN_POLICY_INVALID', fallback_safe=True) from None
        try:
            row, created = agent_runs.claim(self.db, kitchen_id, key, need)
        except IdempotencyConflict:
            raise WorkerError(409, 'IDEMPOTENCY_KEY_REUSED') from None
        if not created:
            if row['state'] == 'READY':
                return row['result']
            raise WorkerError(409, 'BUYER_RECONCILIATION_REQUIRED')
        model, buyer, status = None, None, 'FAILED'
        async def execute():
            nonlocal model, buyer
            stored = await self.gateway.request('POST', f'/v1/kitchens/{kitchen_id}/needs', payload=need)
            model = self.model_factory()
            lookup = lambda pid: buyer_context.product(self.db, kitchen_id, pid)
            # The model does not finish every run (seen live: about 1 in 3 stopped without asking
            # for approval). A run that wrote nothing is safe to start once more, under its own
            # run id so its audit steps stay separate. A run that wrote something is never repeated.
            for attempt in (1, 2):
                run_id = row['_id'] if attempt == 1 else f"{row['_id']}-retry"
                async with create_connected_server_and_client_session(build_server(self.gateway)) as session:
                    buyer = Buyer(model, session, self.gateway, need_id=stored['need_id'],
                                  requested_date=need['requested_date'],
                                  run_id=run_id,
                                  max_steps=12, now=self.now,
                                  catalog_lookup=lookup, allergen_policy=policy,
                                  substitute_planner=SubstitutePlanner(lookup, policy) if policy else None)
                    outcome = await buyer.run(need['text'])
                if outcome['status'] == 'SENT_FOR_APPROVAL' or buyer.mutations:
                    break
            if outcome['status'] != 'SENT_FOR_APPROVAL':
                raise WorkerError(503, 'BUYER_INCOMPLETE', fallback_safe=not buyer.mutations)
            proposals = await self.gateway.request('GET', f'/v1/kitchens/{kitchen_id}/proposals')
            result = next((p for p in proposals['proposals'] if p.get('approval_id') == outcome['approval_id']), None)
            if result is None:
                raise WorkerError(503, 'BUYER_RECONCILIATION_REQUIRED')
            if outcome.get('substitute_options'):
                buyer_context.save_options(self.db, kitchen_id, result['proposal_id'], outcome['substitute_options'])
                result['substitute_options'] = outcome['substitute_options']
            result = {**result, 'buyer_run_id': run_id, 'buyer_model': 'nemotron-3.5-super-vl'}
            meter = getattr(model, 'meter', None)
            if meter is not None:
                # Model calls, tokens and seconds of this request, both attempts (agent/usage.py).
                result['buyer_usage'] = meter.total()
            return result
        try:
            result = await asyncio.wait_for(execute(), timeout=self.timeout)
            agent_runs.finish(self.db, row['_id'], state='READY', result=result)
            status = 'READY'
            return result
        except asyncio.TimeoutError:
            agent_runs.finish(self.db, row['_id'], state='RECONCILE', result=None)
            raise WorkerError(504, 'BUYER_TIMEOUT', fallback_safe=buyer is None or not buyer.mutations) from None
        except Exception as exc:
            agent_runs.finish(self.db, row['_id'], state='RECONCILE', result=None)
            if isinstance(exc, WorkerError):
                raise
            raise WorkerError(503, 'BUYER_UNAVAILABLE', fallback_safe=buyer is None or not buyer.mutations) from None
        finally:
            if model is not None:
                emit(getattr(model, 'meter', None), run='buyer', status=status,
                     thinking=getattr(model, 'thinking', None), max_tokens=getattr(model, 'max_tokens', None))
                await model.close()


def create_app(worker=None, shelf=None):
    state = {}
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            if state:
                await state['worker'].gateway.close()
    app = FastAPI(title='Internal Nemotron Buyer', lifespan=lifespan)

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.exception_handler(WorkerError)
    async def error(request, exc):
        return JSONResponse(status_code=exc.status, content={'error': {
            'code': exc.code, 'message': 'Buyer request did not complete; check request details or reconcile the existing run.',
            'fallback_safe': exc.fallback_safe}})

    @app.post('/run')
    async def run(request: Request):
        token = os.environ.get('GATEWAY_AGENT_TOKEN', '')
        given = request.headers.get('authorization', '')
        if not token or not hmac.compare_digest(given.encode(), ('Bearer ' + token).encode()):
            raise WorkerError(401, 'UNAUTHENTICATED')
        try:
            body = await request.json()
        except ValueError:
            raise WorkerError(422, 'INVALID_REQUEST') from None
        if not isinstance(body, dict):
            raise WorkerError(422, 'INVALID_REQUEST')
        kitchen = os.environ.get('GATEWAY_KITCHEN_ID', 'demo-kitchen')
        if body.get('kitchen_id') != kitchen:
            raise WorkerError(403, 'KITCHEN_SCOPE')
        current = worker
        try:
            if current is None:
                if not state:
                    from store.db import get_db
                    gateway = GatewayClient(token=token)
                    state['worker'] = BuyerWorker(get_db(), gateway)
                current = state['worker']
            return await current.run(kitchen, body)
        except WorkerError:
            raise
        except Exception:
            raise WorkerError(503, 'BUYER_UNAVAILABLE') from None

    # Snap the shelf (#373): POST /shelf reads a photo into a stock count to confirm.
    from agent.shelf_service import mount_shelf
    mount_shelf(app, WorkerError, shelf)
    return app


def main():
    import uvicorn
    uvicorn.run('agent.service:create_app', factory=True, host='0.0.0.0', port=8001, access_log=False)
